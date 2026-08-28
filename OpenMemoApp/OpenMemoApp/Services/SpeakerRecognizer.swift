import Foundation
import AVFoundation
import SoundAnalysis
import CreateML

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
    
    /// Load SpeakerModel.mlmodel from app bundle
    private func loadModel() {
        guard let modelURL = Bundle.main.url(forResource: "SpeakerModel", withExtension: "mlmodel"),
              let model = try? MLModel(contentsOf: modelURL) else {
            print("⚠️ SpeakerModel.mlmodel not found")
            return
        }
        
        mlModel = model
        
        // Create sound classification request
        classificationRequest = try? SNClassifySoundRequest(mlModel: model)
        
        print("✅ SpeakerRecognizer: Model loaded")
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
    
    // MARK: - Speaker Identification
    
    /// Identify speaker in audio file
    func identifySpeaker(audioURL: URL) async -> [(String, Double)] {
        guard let mlModel = mlModel else {
            print("⚠️ SpeakerRecognizer: Model not ready")
            return []
        }
        
        guard let classificationRequest = classificationRequest else {
            print("⚠️ SpeakerRecognizer: Classification request not available")
            return []
        }
        
        do {
            let fileRequest = try SNAudioFileAnalyzer(url: audioURL)
            
            // Reset state
            lastResult = nil
            isComplete = false
            
            // Add observer (self is the SNResultsObserving)
            try fileRequest.add(classificationRequest, withObserver: self)
            
            // Start analysis
            try await fileRequest.analyze()
            
            // Wait for completion (max 5 seconds)
            let timeout = Date().addingTimeInterval(5)
            while !isComplete && Date() < timeout {
                try? await Task.sleep(nanoseconds: 100_000_000) // 100ms
            }
            
            fileRequest.cancelAnalysis()
            
            // Return results
            if let result = lastResult {
                return [(result.speaker, result.confidence)]
            }
            return []
            
        } catch {
            print("❌ SpeakerRecognizer: Analysis failed - \(error)")
            return []
        }
    }
    
    // MARK: - SNResultsObserving
    
    nonisolated func request(_ request: SNRequest, didProduce result: SNResult) {
        guard let classification = result as? SNClassificationResult,
              let top = classification.classifications.first else { return }
        
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
