import Foundation
import AVFoundation
import SoundAnalysis
import CreateML

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

    /// 麦克风权限（Catalyst 需要显式请求；拒绝则返回 false）
    nonisolated static func ensureMicPermission() async -> Bool {
        #if os(iOS) || targetEnvironment(macCatalyst)
        if #available(iOS 17.0, macOS 14.0, *) {
            return await AVAudioApplication.requestRecordPermission()
        } else {
            return await withCheckedContinuation { cont in
                AVAudioSession.sharedInstance().requestRecordPermission { granted in
                    cont.resume(returning: granted)
                }
            }
        }
        #else
        return true
        #endif
    }

    private var recEngine: AVAudioEngine?
    private var recFile: AVAudioFile?
    private var recURL: URL?
    private var recStart: Date?
    private var recSpeaker: String?

    /// 开始录音：创建引擎 + 文件（后台线程启动，绝不在主线程 start）
    func beginRecording(forSpeaker name: String) async throws -> Bool {
        guard await Self.ensureMicPermission() else {
            print("❌ 麦克风权限被拒绝")
            return false
        }
        guard recEngine == nil else { return false }  // 已在录音

        let fm = FileManager.default
        guard let docs = fm.urls(for: .documentDirectory, in: .userDomainMask).first else { return false }
        let safeName = Self.sanitize(name)
        let speakerDir = docs.appendingPathComponent("speaker_samples/\(safeName)", isDirectory: true)
        try? fm.createDirectory(at: speakerDir, withIntermediateDirectories: true)

        let timestamp = ISO8601DateFormatter().string(from: Date())
            .replacingOccurrences(of: ":", with: "-")
        let fileURL = speakerDir.appendingPathComponent("\(timestamp).m4a")

        let engine = AVAudioEngine()
        let format = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: sampleRate,
            channels: AVAudioChannelCount(channelCount),
            interleaved: false
        )!
        let recorder = try AVAudioFile(forWriting: fileURL, settings: format.settings)

        engine.inputNode.installTap(onBus: 0, bufferSize: 4096, format: format) { buffer, _ in
            try? recorder.write(from: buffer)
        }

        // ⚠️ Catalyst 血泪教训（同 VoiceInputManager）：
        // AVAudioEngine.start() 在 Catalyst + USB 麦克风上会卡住主线程 →
        // 必须后台线程启动，主线程绝不能被阻塞。
        let engineBox = AudioEngineBox(engine)
        try await withCheckedThrowingContinuation { (cont: CheckedContinuation<Void, Error>) in
            Task.detached(priority: .userInitiated) {
                do {
                    try engineBox.engine.start()
                    cont.resume()
                } catch {
                    cont.resume(throwing: error)
                }
            }
        }

        recEngine = engine
        recFile = recorder
        recURL = fileURL
        recStart = Date()
        recSpeaker = name
        print("🔴 开始录音: \(fileURL.path)")
        return true
    }

    /// 停止录音并保存样本，返回 (文件 URL, 时长秒数)
    func stopRecording() -> (url: URL, duration: TimeInterval)? {
        guard let engine = recEngine, let start = recStart else { return nil }
        engine.stop()
        engine.inputNode.removeTap(onBus: 0)
        let duration = Date().timeIntervalSince(start)
        let url = recURL
        let name = recSpeaker
        recEngine = nil
        recFile = nil
        recURL = nil
        recStart = nil
        recSpeaker = nil

        if let url, let name, !enrolledSpeakers.contains(name) {
            enrolledSpeakers.append(name)
            saveEnrolledSpeakers()
        }
        print("✅ 样本已保存 (\(Int(duration))s): \(url?.path ?? "?")")
        return url.map { ($0, duration) }
    }

    /// 丢弃当前未完成的录音（用户中途离开录音页）
    func cancelRecording() {
        guard let engine = recEngine else { return }
        engine.stop()
        engine.inputNode.removeTap(onBus: 0)
        if let url = recURL {
            try? FileManager.default.removeItem(at: url)
        }
        recEngine = nil
        recFile = nil
        recURL = nil
        recStart = nil
        recSpeaker = nil
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
