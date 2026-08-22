import Foundation
import AVFoundation
import SoundAnalysis

// MARK: - 说话人识别（Apple 原生：Create ML + SoundAnalysis）
//
// Apple 的 Speech 框架（SFSpeechRecognizer / SpeechAnalyzer）没有公开的
// 说话人识别 API。最接近的 Apple 原生方案：
//   1. 用 Create ML 训练「声音分类器」（每个人 = 一个类别）
//   2. App 内用 SoundAnalysis 的 SNClassifySoundRequest(mlModel:) 推理
//
// 本服务负责：
//   - 录音采样（麦克风 → AAC 文件，供训练/推理）
//   - 对一段音频做说话人推理（返回 [名字, 置信度]）
//   - 管理已登记说话人（名字 + 若干采样音频）
//
// 训练流程（在 Mac 上用 Create ML / 脚本完成，见 tools/train_speaker.py）：
//   收集每个人 ~30s 音频 → 训练 → 导出 SpeakerModel.mlmodel → 放进 App

@MainActor
final class SpeakerRecognizer: NSObject, ObservableObject {
    static let shared = SpeakerRecognizer()

    // 已登记说话人（UserDefaults 持久化名字列表）
    @Published var enrolledSpeakers: [String] = []
    /// 模型是否存在且可用
    @Published var isModelReady = false

    private var model: MLModel?

    // 推理状态
    private var analyzer: SNAudioFileAnalyzer?
    private var pendingResults: [(String, Double)] = []
    private var inferenceContinuation: CheckedContinuation<[(String, Double)], Error>?

    // 录音（采样用）
    private var audioEngine: AVAudioEngine?
    private var audioFile: AVAudioFile?
    private var isRecording = false
    private var recordingURL: URL?

    override init() {
        super.init()
        loadEnrolledSpeakers()
        loadModel()
    }

    // MARK: - 模型加载

    /// 从 App bundle 加载 SpeakerModel.mlmodel（训练好后放入）
    private func loadModel() {
        guard let url = Bundle.main.url(forResource: "SpeakerModel", withExtension: "mlmodelc") ??
                        Bundle.main.url(forResource: "SpeakerModel", withExtension: "mlmodel") else {
            print("[说话人] 未找到 SpeakerModel（尚未训练）")
            isModelReady = false
            return
        }
        do {
            model = try MLModel(contentsOf: url)
            isModelReady = true
            print("[说话人] 模型加载成功")
        } catch {
            print("[说话人] 模型加载失败: \(error)")
            isModelReady = false
        }
    }

    private func loadEnrolledSpeakers() {
        enrolledSpeakers = UserDefaults.standard.stringArray(forKey: "speaker_names") ?? []
    }

    func saveEnrolledSpeakers() {
        UserDefaults.standard.set(enrolledSpeakers, forKey: "speaker_names")
    }

    // MARK: - 说话人推理

    /// 对一段音频文件做说话人识别。
    /// 返回 [(说话人, 置信度)]，按置信度降序；模型不可用时返回空。
    func identifySpeaker(audioURL: URL) async -> [(String, Double)] {
        guard isModelReady, let model else { return [] }

        do {
            let request = try SNClassifySoundRequest(mlModel: model)
            request.windowDuration = CMTime(seconds: 1.0, preferredTimescale: 100)
            request.overlapFactor = 0.5

            let analyzer = try SNAudioFileAnalyzer(url: audioURL)
            self.analyzer = analyzer
            try analyzer.add(request, withObserver: self)

            return try await withCheckedThrowingContinuation { continuation in
                self.inferenceContinuation = continuation
                self.pendingResults = []
                do {
                    try analyzer.analyze()
                } catch {
                    continuation.resume(throwing: error)
                }
            }
        } catch {
            print("[说话人] 推理失败: \(error)")
            return []
        }
    }

    // MARK: - 录音采样（登记说话人 / 收集训练数据）

    /// 开始录音采样（存成 m4a，用于登记/训练）
    func startRecordingSample(forSpeaker name: String) async -> Bool {
        guard !isRecording else { return false }
        let session = AVAudioSession.sharedInstance()
        do {
            try session.setCategory(.record, mode: .measurement)
            try session.setActive(true)
        } catch {
            print("[说话人] 音频会话失败: \(error)")
            return false
        }

        let engine = AVAudioEngine()
        let input = engine.inputNode
        let format = input.outputFormat(forBus: 0)

        let dir = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("speaker_samples", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)

        let filename = "\(name)_\(Int(Date().timeIntervalSince1970)).m4a"
        let url = dir.appendingPathComponent(filename)
        recordingURL = url

        do {
            let file = try AVAudioFile(forWriting: url, settings: [
                AVFormatIDKey: kAudioFormatMPEG4AAC,
                AVSampleRateKey: 44100,
                AVNumberOfChannelsKey: 1,
                AVEncoderAudioQualityKey: AVAudioQuality.high.rawValue,
            ])
            input.installTap(onBus: 0, bufferSize: 4096, format: format) { [weak self] buffer, _ in
                guard let self, let audioFile = self.audioFile else { return }
                // 转成文件格式再写
                if let converter = AVAudioConverter(from: format, to: file.processingFormat) {
                    let ratio = file.processingFormat.sampleRate / format.sampleRate
                    let capacity = AVAudioFrameCount(Double(buffer.frameLength) * ratio) + 1024
                    if let outBuf = AVAudioPCMBuffer(pcmFormat: file.processingFormat, frameCapacity: capacity) {
                        var error: NSError?
                        let status = converter.convert(to: outBuf, error: &error) { _, outStatus in
                            outStatus.pointee = .haveData
                            return buffer
                        }
                        if status == .haveData {
                            try? file.write(from: outBuf)
                        }
                    }
                }
            }
            audioFile = file
            try engine.start()
            self.audioEngine = engine
            isRecording = true
            return true
        } catch {
            print("[说话人] 录音启动失败: \(error)")
            return false
        }
    }

    /// 停止录音采样，返回保存的文件 URL
    func stopRecordingSample() -> URL? {
        guard isRecording else { return nil }
        isRecording = false
        audioEngine?.stop()
        audioEngine?.inputNode.removeTap(onBus: 0)
        audioEngine = nil
        audioFile = nil
        let url = recordingURL
        recordingURL = nil
        return url
    }
}

// MARK: - SNResultsObserving
extension SpeakerRecognizer: SNResultsObserving {
    func request(_ request: SNRequest, didProduce result: SNResult) {
        guard let result = result as? SNClassificationResult else { return }
        // 聚合每个窗口的分类
        for classification in result.classifications {
            let label = classification.identifier
            let confidence = classification.confidence
            if let idx = pendingResults.firstIndex(where: { $0.0 == label }) {
                pendingResults[idx].1 = max(pendingResults[idx].1, confidence)
            } else {
                pendingResults.append((label, confidence))
            }
        }
    }

    func request(_ request: SNRequest, didFailWithError error: Error) {
        inferenceContinuation?.resume(throwing: error)
        inferenceContinuation = nil
    }

    func requestDidComplete(_ request: SNRequest) {
        let sorted = pendingResults.sorted { $0.1 > $1.1 }
        inferenceContinuation?.resume(returning: sorted)
        inferenceContinuation = nil
    }
}
