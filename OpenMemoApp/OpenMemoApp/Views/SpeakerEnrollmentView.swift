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

    /// 录音时建议说的话（固定句式，训练效果最好）
    private let samplePhrase = "我是{名字}，这是我的声音样本"
    var body: some View {
        NavigationStack {
            ZStack {
                OMBackground(.settings)

                ScrollView {
                    VStack(spacing: 16) {
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
        .preferredColorScheme(.dark)   // 强制深色：玻璃材质在亮色系统下会发白，文字看不清
    }

    // MARK: - 模型状态

    private var modelStatusCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Image(systemName: modelReady ? "checkmark.circle.fill" : "xmark.circle.fill")
                    .font(.title3)
                    .foregroundStyle(modelReady ? OMColors.success : OMColors.warning)
                Text(modelReady ? "模型就绪" : "模型未就绪")
                    .font(OMFonts.title3.weight(.semibold))
                    .foregroundStyle(.white)
                Spacer()
            }
            Text(modelReady
                 ? "可以识别 \(samples.count) 位说话人"
                 : "先录样本（下面第 1~2 步），再在 Mac 上训练模型（第 3 步）")
                .font(OMFonts.caption)
                .foregroundStyle(.white.opacity(0.65))        }
        .padding()
        .darkCard()
    }

    // MARK: - 添加说话人 + 录音

    private var addSpeakerSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("1. 添加说话人并录音")
                .font(OMFonts.title3.weight(.semibold))
                .foregroundStyle(.white)

            HStack {
                TextField("输入名字（如 Ethan）", text: $speakerName)
                    .font(OMFonts.body)
                    .foregroundStyle(.white)
                    .padding()
                    .background(OMColors.surface.opacity(0.8))
                    .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                Button { Task { await startRecording() } } label: {
                    if isRecording {
                        ProgressView().tint(.white)
                    } else {
                        Image(systemName: "mic.fill").font(.title3).foregroundStyle(.white)
                    }
                }
                .buttonStyle(.plain)
                .frame(width: 50, height: 50)
                .background(OMColors.primaryGradient)
                .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                .disabled(speakerName.isEmpty || isRecording)
            }

            if isRecording {
                HStack(spacing: 8) {
                    Circle()
                        .fill(OMColors.error)
                        .frame(width: 8, height: 8)
                        .shadow(color: OMColors.error, radius: 4)
                    Text("正在录音… 请说：「\(samplePhrase.replacingOccurrences(of: "{名字}", with: recordingSpeaker ?? ""))」")
                        .font(OMFonts.caption.weight(.medium))
                        .foregroundStyle(.white.opacity(0.9))
                }
            }
            if let err = errorMessage {
                Label(err, systemImage: "exclamationmark.triangle.fill")
                    .font(OMFonts.caption)
                    .foregroundStyle(OMColors.error)
            }
            if let done = lastRecorded {
                Label("已保存 \(done) 的样本 — 建议再录 2 次（共 3 个样本）", systemImage: "checkmark.circle.fill")
                    .font(OMFonts.caption)
                    .foregroundStyle(OMColors.success)
            }
        }
        .padding()
        .darkCard()
    }

    // MARK: - 已登记说话人

    private var enrolledSpeakersList: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("已登记说话人")
                .font(OMFonts.title3.weight(.semibold))
                .foregroundStyle(.white)
            if samples.isEmpty {
                Text("暂无说话人 — 按上面第 1 步录一个吧")
                    .font(OMFonts.body)
                    .foregroundStyle(.white.opacity(0.5))
                    .frame(maxWidth: .infinity, alignment: .center)
                    .padding()
            } else {
                ForEach(samples.sorted(by: { $0.key < $1.key }), id: \.key) { name, count in
                    HStack {
                        Image(systemName: "person.circle.fill").font(.title3).foregroundStyle(OMColors.info)
                        Text(name).font(OMFonts.body).foregroundStyle(.white)
                        Spacer()
                        Text("\(count) 个样本")
                            .font(OMFonts.caption)
                            .foregroundStyle(count >= 3 ? OMColors.success : .white.opacity(0.5))
                    }
                    .padding(.vertical, 4)
                }
            }
        }
        .padding()
        .darkCard()
    }

    // MARK: - 训练指南

    private var trainingGuideCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Image(systemName: "book.fill").font(.title3).foregroundStyle(OMColors.info)
                Text("2. 训练模型（在 Mac 上，一次性）").font(OMFonts.title3.weight(.semibold)).foregroundStyle(.white)
            }
            VStack(alignment: .leading, spacing: 8) {
                guideStep("1", "每人至少录 3 个样本（上面点 3 次麦克风，每次说同一句话）")
                guideStep("2", "把 App 的样本导出到 Mac：Documents/speaker_samples/")
                guideStep("3", "运行训练脚本：tools/train_speaker.swift")
                guideStep("4", "把生成的 SpeakerModel.mlmodel 拖进 Xcode 工程")
                guideStep("5", "重新编译运行 App → 模型就绪，聊天时自动识别说话人")
            }
        }
        .padding()
        .darkCard()
    }

    private func guideStep(_ n: String, _ text: String) -> some View {
        HStack(alignment: .top, spacing: 10) {
            Text(n).font(OMFonts.subheadline.weight(.bold)).foregroundStyle(OMColors.info)
            Text(text).font(OMFonts.caption).foregroundStyle(.white.opacity(0.75)).lineSpacing(3)
        }
    }

    // MARK: - 录音动作

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
            errorMessage = "录音失败：请检查麦克风权限（系统设置 → 隐私 → 麦克风）"
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

// 深色实心卡片：不透明背景，任何系统外观下文字都清晰
extension View {
    func darkCard() -> some View {
        self
            .background(OMColors.surfaceElevated.opacity(0.95))
            .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .stroke(Color.white.opacity(0.1), lineWidth: 1)
            )
    }
}

#Preview {
    SpeakerEnrollmentView()
        .preferredColorScheme(.dark)
}
