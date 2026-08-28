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
    
    // MARK: - Recording Samples (for training)

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

    func startRecordingSample(forSpeaker name: String) async -> Bool {
        // 1. 权限：没授权直接失败（不再 try! 崩溃）
        guard await Self.ensureMicPermission() else {
            print("❌ 麦克风权限被拒绝")
            return false
        }

        let fm = FileManager.default
        guard let docs = fm.urls(for: .documentDirectory, in: .userDomainMask).first else { return false }

        // Create speaker directory
        let speakerDir = docs.appendingPathComponent("speaker_samples/\(name)", isDirectory: true)
        try? fm.createDirectory(at: speakerDir, withIntermediateDirectories: true)

        // Generate filename
        let timestamp = ISO8601DateFormatter().string(from: Date())
            .replacingOccurrences(of: ":", with: "-")
        let filename = "\(timestamp).m4a"
        let fileURL = speakerDir.appendingPathComponent(filename)

        let engine = AVAudioEngine()
        let format = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: sampleRate,
            channels: AVAudioChannelCount(channelCount),
            interleaved: false
        )!

        do {
            let recorder = try AVAudioFile(forWriting: fileURL, settings: format.settings)

            engine.inputNode.installTap(onBus: 0, bufferSize: 4096, format: format) { buffer, _ in
                try? recorder.write(from: buffer)
            }

            // ⚠️ Catalyst 血泪教训（同 VoiceInputManager）：
            // AVAudioEngine.start() 在 Catalyst + USB 麦克风上会卡住主线程 →
            // 必须后台线程启动，主线程绝不能被阻塞。
            // （用 @unchecked Sendable 盒子绕开 Swift 6 sending 检查，同 AudioEngineBox）
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

            // Wait 3 seconds to collect sample
            try await Task.sleep(nanoseconds: 3_000_000_000)

            engine.stop()
            engine.inputNode.removeTap(onBus: 0)
        } catch {
            print("❌ 录音失败: \(error)")
            if engine.isRunning { engine.stop() }
            return false
        }

        // Update speaker list
        if !enrolledSpeakers.contains(name) {
            enrolledSpeakers.append(name)
            saveEnrolledSpeakers()
        }

        print("✅ Sample saved: \(fileURL.path)")
        return true
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
