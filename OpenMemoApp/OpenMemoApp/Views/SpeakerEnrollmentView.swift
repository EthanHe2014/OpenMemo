import SwiftUI

/// Speaker registration UI for identifying different people in voice messages.
/// Allows adding speakers and recording samples for training.
struct SpeakerEnrollmentView: View {
    @Environment(\.dismiss) private var dismiss
    @State private var speakerName = ""
    @State private var samples: [String: Int] = [:]
    @State private var isRecording = false
    @State private var modelReady = false
    @State private var recordingSpeaker: String?
    @State private var errorMessage: String?
    @State private var lastRecorded: String?
    
    var body: some View {
        NavigationStack {
            ZStack {
                OMBackground(.settings)
                
                ScrollView {
                    VStack(spacing: 20) {
                        modelStatusCard
                        addSpeakerSection
                        enrolledSpeakersList
                        trainingGuideCard
                    }
                    .padding()
                }
                .navigationTitle("说话人登记")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) {
                        Button("完成") { dismiss() }
                    }
                }
            }
            .onAppear { refreshModelStatus() }
        }
    }
    
    private var modelStatusCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Image(systemName: modelReady ? "checkmark.circle.fill" : "xmark.circle.fill")
                    .font(.title3)
                    .foregroundStyle(modelReady ? OMColors.success : OMColors.error)
                Text(modelReady ? "模型就绪" : "模型未就绪")
                    .font(OMFonts.title3)
                    .foregroundStyle(.white)
                Spacer()
            }
            Text(modelReady ? "可以识别 \(samples.count) 位说话人" : "请先训练 SpeakerModel.mlmodel")
                .font(OMFonts.caption)
                .foregroundStyle(.white.opacity(0.7))
        }
        .padding()
        .glass(cornerRadius: 16)
    }
    
    private var addSpeakerSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("添加说话人")
                .font(OMFonts.title3)
                .foregroundStyle(.white)
            HStack {
                TextField("输入名字", text: $speakerName)
                    .font(OMFonts.body)
                    .foregroundStyle(.white)
                    .padding()
                    .glass(cornerRadius: 12)
                Button { Task { await startRecording() } } label: {
                    if isRecording { ProgressView().tint(.white) }
                    else { Image(systemName: "mic.fill").font(.title3).foregroundStyle(.white) }
                }
                .buttonStyle(.plain)
                .frame(width: 50, height: 50)
                .glass(cornerRadius: 12)
                .disabled(speakerName.isEmpty || isRecording)
            }
            if isRecording {
                Text("正在为 \(recordingSpeaker ?? "") 录音... (3秒，请开始说话)")
                    .font(OMFonts.caption)
                    .foregroundStyle(OMColors.warning)
            }
            if let err = errorMessage {
                Label(err, systemImage: "exclamationmark.triangle.fill")
                    .font(OMFonts.caption)
                    .foregroundStyle(OMColors.error)
            }
            if let done = lastRecorded {
                Label("已保存 \(done) 的样本", systemImage: "checkmark.circle.fill")
                    .font(OMFonts.caption)
                    .foregroundStyle(OMColors.success)
            }
        }
        .padding()
        .glass(cornerRadius: 16)
    }
    
    private var enrolledSpeakersList: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("已登记说话人")
                .font(OMFonts.title3)
                .foregroundStyle(.white)
            if samples.isEmpty {
                Text("暂无说话人").font(OMFonts.body).foregroundStyle(.white.opacity(0.5))
                    .frame(maxWidth: .infinity, alignment: .center).padding()
            } else {
                ForEach(samples.sorted(by: { $0.key < $1.key }), id: \.key) { name, count in
                    HStack {
                        Image(systemName: "person.circle.fill").font(.title3).foregroundStyle(OMColors.info)
                        Text(name).font(OMFonts.body).foregroundStyle(.white)
                        Spacer()
                        Text("\(count) 个样本").font(OMFonts.caption).foregroundStyle(.white.opacity(0.5))
                    }
                    .padding(.vertical, 4)
                }
            }
        }
        .padding()
        .glass(cornerRadius: 16)
    }
    
    private var trainingGuideCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Image(systemName: "book.fill").font(.title3).foregroundStyle(OMColors.info)
                Text("训练指南").font(OMFonts.title3).foregroundStyle(.white)
            }
            Text("""
                1. 添加说话人并录音（每人至少 3 个样本）
                2. 在 Mac 上运行 tools/train_speaker.swift
                3. 将生成的 SpeakerModel.mlmodel 拖入 Xcode
                4. 重新编译 App
                """)
                .font(OMFonts.caption).foregroundStyle(.white.opacity(0.7)).lineSpacing(4)
        }
        .padding()
        .glass(cornerRadius: 16)
    }
    
    private func startRecording() async {
        guard !speakerName.isEmpty else { return }
        errorMessage = nil
        lastRecorded = nil
        isRecording = true
        recordingSpeaker = speakerName
        let success = await SpeakerRecognizer.shared.startRecordingSample(forSpeaker: speakerName)
        isRecording = false
        recordingSpeaker = nil
        if success {
            lastRecorded = speakerName
            refreshModelStatus()
        } else {
            errorMessage = "录音失败：请检查麦克风权限"
        }
    }
    
    private func refreshModelStatus() {
        modelReady = SpeakerRecognizer.shared.isModelReady
        var counts: [String: Int] = [:]
        for name in SpeakerRecognizer.shared.enrolledSpeakers {
            if let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first {
                let dir = docs.appendingPathComponent("speaker_samples/\(name)")
                if let files = try? FileManager.default.contentsOfDirectory(atPath: dir.path) {
                    counts[name] = files.count
                }
            }
        }
        samples = counts
    }
}
