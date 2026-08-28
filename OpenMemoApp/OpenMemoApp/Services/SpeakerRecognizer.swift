import Foundation
import AVFoundation
import SoundAnalysis
#if canImport(CreateML)
import CreateML
#endif

/// 录音文件盒子：tap 回调线程里懒创建 + 写入（音频线程安全）
final class RecorderBox: @unchecked Sendable {
    var file: AVAudioFile?
    var error: String?
    var written: Int = 0
}

/// Speaker recognition service using Apple's SoundAnalysis framework.
/// Reads speaker models written by tools/train_speaker.swift
/// Detects who is speaking in an audio file and returns results with confidence scores.
///
/// This service provides speaker identification functionality for OpenMemo.
/// The main use case is identifying who is speaking in voice messages.
///
/// Usage:
///   1. Train a model using tools/train_speaker.swift (creates SpeakerModel.mlmodel)
///   2. Copy SpeakerModel.mlmodel to the OpenMemo app bundle
///   3. SpeakerRecognizer.shared.isModelReady becomes true
///   4. Use identifySpeaker(audioURL:) to identify who is speaking

/// Speaker identification service using Apple's SoundAnalysis framework
@MainActor
final class SpeakerRecognizer: NSObject, SNResultsObserving {
    static let shared = SpeakerRecognizer()    
    /// Speaker identification model ready flag
    var isModelReady: Bool { mlModel != nil }
    
    /// List of enrolled speakers
    var enrolledSpeakers: [String] = []
    
    /// Audio file sample rate (Hz)
    private let sampleRate: Double = 16000
    
    /// Channel count
    private let channelCount: Int = 1
    
    /// Trained speaker model
    private var mlModel: MLModel?
    
    /// Sound analysis request
    private var classificationRequest: SNClassifySoundRequest?
    
    /// Temporary result storage
    private var lastResult: (speaker: String, confidence: Double)?
    
    /// Flag for completion
    private var isComplete = false
    
    private override init() {
        super.init()
        loadModel()
        loadEnrolledSpeakers()
    }
    
    // MARK: - Model Management
    
    /// Load SpeakerModel.mlmodel —— 优先 App 内置（旧流程），
    /// 其次 Documents 里 App 内训练生成的模型（新流程，无需 Xcode）
    private func loadModel() {
        // 1) App bundle（开发者手动拖入的模型）
        if let modelURL = Bundle.main.url(forResource: "SpeakerModel", withExtension: "mlmodel"),
           let model = try? MLModel(contentsOf: modelURL) {
            apply(model: model)
            print("✅ SpeakerRecognizer: Model loaded (bundle)")
            return
        }
        // 2) Documents 里 App 内训练出来的模型
        if let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first {
            let pkg = docs.appendingPathComponent("SpeakerModel.mlmodel")
            if FileManager.default.fileExists(atPath: pkg.path),
               let compiled = try? MLModel.compileModel(at: pkg),
               let model = try? MLModel(contentsOf: compiled) {
                apply(model: model)
                print("✅ SpeakerRecognizer: Model loaded (documents)")
                return
            }
        }
        print("⚠️ SpeakerModel.mlmodel not found")
    }

    private func apply(model: MLModel) {
        mlModel = model
        classificationRequest = try? SNClassifySoundRequest(mlModel: model)
    }
    
    /// Load enrolled speakers from UserDefaults
    private func loadEnrolledSpeakers() {
        if let saved = UserDefaults.standard.array(forKey: "enrolledSpeakers") as? [String] {
            enrolledSpeakers = saved
            print("📋 SpeakerRecognizer: Loaded \(enrolledSpeakers.count) speakers")
        }
    }
    
    /// Save enrolled speakers to UserDefaults
    private func saveEnrolledSpeakers() {
        UserDefaults.standard.set(enrolledSpeakers, forKey: "enrolledSpeakers")
        UserDefaults.standard.set(isModelReady, forKey: "speakerModelReady")
    }

    // MARK: - In-app training (no terminal / Xcode needed)

#if canImport(CreateML)
    /// 在 App 内用 Create ML 训练说话人模型（macOS/Catalyst 支持 CreateML）。
    /// 输入：Documents/speaker_samples/<名字>/ 下的样本；
    /// 输出：Documents/SpeakerModel.mlmodel（编译后直接加载，立即可用）。
    func trainModelInApp() async -> Result<String, Error> {
        guard let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first else {
            return .failure(NSError(domain: "SpeakerRecognizer", code: 3,
                                    userInfo: [NSLocalizedDescriptionKey: "无法访问文档目录"]))
        }
        let samplesDir = docs.appendingPathComponent("speaker_samples", isDirectory: true)
        Self.logToFile("train: samples at \(samplesDir.path)")

        // 校验：至少有一个说话人目录且含样本文件
        let fm = FileManager.default
        guard let dirs = try? fm.contentsOfDirectory(at: samplesDir, includingPropertiesForKeys: nil,
                                                     options: [.skipsHiddenFiles]) else {
            return .failure(NSError(domain: "SpeakerRecognizer", code: 4,
                                    userInfo: [NSLocalizedDescriptionKey: "没有找到样本目录"]))
        }
        var total = 0
        let speakerDirs = dirs.filter(\.hasDirectoryPath)
        for d in speakerDirs {
            total += (try? fm.contentsOfDirectory(atPath: d.path))?.count ?? 0
        }
        guard total > 0 else {
            return .failure(NSError(domain: "SpeakerRecognizer", code: 5,
                                    userInfo: [NSLocalizedDescriptionKey: "没有样本可训练，请先录音"]))
        }
        Self.logToFile("train: \(total) samples, \(speakerDirs.count) speakers")

        let outPackage = docs.appendingPathComponent("SpeakerModel.mlmodel")

        do {
            // Create ML 训练很重 → 后台线程跑，绝不卡主线程（只回 URL，模型在 MainActor 上加载）
            let compiledURL = try await Task.detached(priority: .userInitiated) { () -> URL in
                // Create ML 要求至少两个类别：只有一个人时，自动补一个合成“背景噪音”类
                if speakerDirs.count < 2 {
                    try Self.generateBackgroundClass(in: samplesDir)
                }
                let classifier = try MLSoundClassifier(trainingData: .labeledDirectories(at: samplesDir))
                let metadata = MLModelMetadata(
                    author: "OpenMemo",
                    shortDescription: "OpenMemo 说话人识别（App 内训练）",
                    version: "1.0"
                )
                try classifier.write(to: outPackage, metadata: metadata)
                return try MLModel.compileModel(at: outPackage)
            }.value
            let model = try MLModel(contentsOf: compiledURL)
            apply(model: model)
            Self.logToFile("train: success -> \(outPackage.path)")
            return .success("训练完成，模型已就绪")
        } catch {
            Self.logToFile("train: FAILED \(error)")
            return .failure(error)
        }
    }


#else
    /// 训练仅支持 macOS / Catalyst（Create ML 不适用于 iOS）
    func trainModelInApp() async -> Result<String, Error> {
        return .failure(NSError(domain: "SpeakerRecognizer", code: 9,
                                userInfo: [NSLocalizedDescriptionKey: "训练功能仅支持 Mac 版"]))
    }
#endif

#if canImport(CreateML)
    /// 生成合成“背景噪音”类别（Create ML 需要至少两类才能训练）
    nonisolated static func generateBackgroundClass(in samplesDir: URL) throws {
        let bgDir = samplesDir.appendingPathComponent("__background__", isDirectory: true)
        try? FileManager.default.createDirectory(at: bgDir, withIntermediateDirectories: true)

        let format = AVAudioFormat(commonFormat: .pcmFormatFloat32,
                                   sampleRate: 16000, channels: 1, interleaved: false)!
        let specs: [(String, Float, Float)] = [
            ("silence", 0.001, 0),     // 静音
            ("noise", 0.03, 0),        // 白噪音
            ("hum", 0.01, 0.005),      // 低频哼声 + 噪音
        ]
        for (i, spec) in specs.enumerated() {
            let url = bgDir.appendingPathComponent("bg_\(i).wav")
            let frameCount = AVAudioFrameCount(3.0 * 16000)
            guard let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: frameCount) else { continue }
            buffer.frameLength = frameCount
            let ch = buffer.floatChannelData![0]
            for f in 0..<Int(frameCount) {
                let noise = Float.random(in: -1...1) * spec.1
                let hum = spec.2 * sinf(2 * Float.pi * 50 * Float(f) / 16000)
                ch[f] = noise + hum
            }
            let file = try AVAudioFile(forWriting: url, settings: format.settings)
            try file.write(from: buffer)
        }
    }
    
    // MARK: - Manual sample recording (wizard: tap start → speak → tap stop)

    /// 麦克风权限（Catalyst 用 AVAudioSession —— 与 VoiceInputManager 同路径，绝对可用）
    nonisolated static func ensureMicPermission() async -> Bool {
        await withCheckedContinuation { cont in
            AVAudioSession.sharedInstance().requestRecordPermission { granted in
                cont.resume(returning: granted)
            }
        }
    }

    /// 写录音调试日志（崩溃后能定位到底死在哪一步）
    nonisolated static func logToFile(_ msg: String) {
        let line = "\(Date().timeIntervalSince1970) \(msg)\n"
        if let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first {
            let url = docs.appendingPathComponent("speaker_recording.log")
            if let data = line.data(using: .utf8) {
                if FileManager.default.fileExists(atPath: url.path) {
                    if let fh = try? FileHandle(forWritingTo: url) {
                        fh.seekToEndOfFile()
                        fh.write(data)
                        try? fh.close()
                    }
                } else {
                    try? data.write(to: url)
                }
            }
        }
    }

    private var recorder: AVAudioRecorder?
    private var recURL: URL?
    private var recStart: Date?
    private var recSpeaker: String?

    /// 开始录音：用 AVAudioRecorder（高层 API，Catalyst 稳定，无 engine/tap 崩溃面）
    func beginRecording(forSpeaker name: String) async throws -> Bool {
        Self.logToFile("== beginRecording(\(name)) ==")
        guard await Self.ensureMicPermission() else {
            Self.logToFile("mic permission denied")
            print("❌ 麦克风权限被拒绝")
            return false
        }
        Self.logToFile("mic permission ok")
        guard recorder == nil else { return false }  // 已在录音

        // 先停掉唤醒词引擎（避免两个音频客户端抢同一个麦克风）
        await VoiceInputManager.suspendAllForRecording()
        Self.logToFile("wake engines suspended")

        let fm = FileManager.default
        guard let docs = fm.urls(for: .documentDirectory, in: .userDomainMask).first else { return false }
        let safeName = Self.sanitize(name)
        let speakerDir = docs.appendingPathComponent("speaker_samples/\(safeName)", isDirectory: true)
        try? fm.createDirectory(at: speakerDir, withIntermediateDirectories: true)

        let timestamp = ISO8601DateFormatter().string(from: Date())
            .replacingOccurrences(of: ":", with: "-")
        let fileURL = speakerDir.appendingPathComponent("\(timestamp).m4a")
        Self.logToFile("file: \(fileURL.path)")

        let settings: [String: Any] = [
            AVFormatIDKey: Int(kAudioFormatMPEG4AAC),
            AVSampleRateKey: 44100,
            AVNumberOfChannelsKey: 1,
            AVEncoderAudioQualityKey: AVAudioQuality.high.rawValue,
        ]
        let rec: AVAudioRecorder
        do {
            rec = try AVAudioRecorder(url: fileURL, settings: settings)
        } catch {
            Self.logToFile("ERROR: AVAudioRecorder create: \(error)")
            throw error
        }
        Self.logToFile("AVAudioRecorder created")

        guard rec.record() else {
            Self.logToFile("ERROR: recorder.record() returned false")
            throw NSError(domain: "SpeakerRecognizer", code: 2,
                          userInfo: [NSLocalizedDescriptionKey: "无法开始录音"])
        }
        Self.logToFile("recording started")

        recorder = rec
        recURL = fileURL
        recStart = Date()
        print("🔴 开始录音: \(fileURL.path)")
        return true
    }

    /// 停止录音并保存样本，返回 (文件 URL, 时长秒数)
    func stopRecording() -> (url: URL, duration: TimeInterval)? {
        guard let rec = recorder, let start = recStart else {
            Self.logToFile("stopRecording: nothing to stop")
            return nil
        }
        rec.stop()
        let duration = Date().timeIntervalSince(start)
        let url = recURL
        let name = recSpeaker
        recorder = nil
        recURL = nil
        recStart = nil
        recSpeaker = nil

        if let url, let name, !enrolledSpeakers.contains(name) {
            enrolledSpeakers.append(name)
            saveEnrolledSpeakers()
        }
        Self.logToFile("stopRecording: saved \(url?.path ?? "?") (\(Int(duration))s)")
        print("✅ 样本已保存 (\(Int(duration))s): \(url?.path ?? "?")")
        return url.map { ($0, duration) }
    }

    /// 丢弃当前未完成的录音（用户中途离开录音页）
    func cancelRecording() {
        guard let rec = recorder else { return }
        rec.stop()
        if let url = recURL {
            try? FileManager.default.removeItem(at: url)
        }
        recorder = nil
        recURL = nil
        recStart = nil
        recSpeaker = nil
        Self.logToFile("cancelRecording")
    }

    /// 删除某个样本文件（重录时用）
    func deleteSample(at url: URL) {
        try? FileManager.default.removeItem(at: url)
    }

    /// 某个说话人已有的样本数
    func sampleCount(forSpeaker name: String) -> Int {
        guard let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first else { return 0 }
        let dir = docs.appendingPathComponent("speaker_samples/\(Self.sanitize(name))")
        return (try? FileManager.default.contentsOfDirectory(atPath: dir.path))?.count ?? 0
    }

    nonisolated private static func sanitize(_ name: String) -> String {
        let bad = CharacterSet(charactersIn: "/:\\\"")
        return name.components(separatedBy: bad).joined(separator: "_")
    }
    

#endif

    // MARK: - Speaker Identification
    
    /// Identify speaker in audio file
    func identifySpeaker(audioURL: URL) async -> [(String, Double)] {
        Self.logToFile("identifySpeaker: url=\(audioURL.path)")
        guard let mlModel = mlModel else {
            Self.logToFile("identifySpeaker: MODEL NIL")
            return []
        }
        guard let classificationRequest = classificationRequest else {
            Self.logToFile("identifySpeaker: REQUEST NIL")
            return []
        }
        Self.logToFile("identifySpeaker: model+request ok, file size=\((try? audioURL.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? -1)")

        do {
            let fileRequest = try SNAudioFileAnalyzer(url: audioURL)
            Self.logToFile("identifySpeaker: analyzer created")

            // Reset state
            lastResult = nil
            isComplete = false

            // Add observer (self is the SNResultsObserving)
            try fileRequest.add(classificationRequest, withObserver: self)
            Self.logToFile("identifySpeaker: observer added")

            // Start analysis
            try await fileRequest.analyze()
            Self.logToFile("identifySpeaker: analyze() returned")

            // Wait for completion (max 5 seconds)
            let timeout = Date().addingTimeInterval(5)
            while !isComplete && Date() < timeout {
                try? await Task.sleep(nanoseconds: 100_000_000) // 100ms
            }
            Self.logToFile("identifySpeaker: polling done, isComplete=\(isComplete), lastResult=\(String(describing: lastResult))")

            fileRequest.cancelAnalysis()

            // Return results
            if let result = lastResult {
                return [(result.speaker, result.confidence)]
            }
            return []

        } catch {
            Self.logToFile("identifySpeaker: ANALYSIS FAILED - \(error)")
            print("❌ SpeakerRecognizer: Analysis failed - \(error)")
            return []
        }
    }
    
    // MARK: - SNResultsObserving
    
    nonisolated func request(_ request: SNRequest, didProduce result: SNResult) {
        guard let classification = result as? SNClassificationResult,
              let top = classification.classifications.first else { return }

        // 合成背景噪音类：不当作说话人
        if top.identifier == "__background__" {
            return
        }

        // Copy Sendable values out of isolation before sending to MainActor
        let speaker = top.identifier
        let confidence = top.confidence
        Task { @MainActor in
            self.lastResult = (speaker, confidence)
        }
    }
    
    nonisolated func request(_ request: SNRequest, didFailWithError error: Error) {
        print("❌ SpeakerRecognizer request failed: \(error)")
        Task { @MainActor in
            self.isComplete = true
        }
    }
    
    nonisolated func requestDidComplete(_ request: SNRequest) {
        Task { @MainActor in
            self.isComplete = true
        }
    }
}
