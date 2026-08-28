import SwiftUI

/// Speaker registration wizard — multi-step:
///   1. Enter name
///   2-4. Record 3 samples (tap start → speak → tap stop)
///   5. Model training guide
///   6. Done
struct SpeakerEnrollmentView: View {
    @Environment(\.dismiss) private var dismiss

    private let totalSamples = 3

    @State private var step = 1
    @State private var speakerName = ""
    @State private var isRecording = false
    @State private var elapsed = 0
    @State private var savedInfo: String?
    @State private var lastSavedURL: URL?
    @State private var errorMessage: String?
    @State private var modelReady = false
    @State private var timer: Timer?

    private var samplePhrase: String { "我是\(speakerName)，这是我的声音样本" }

    var body: some View {
        NavigationStack {
            ZStack {
                OMBackground(.settings)

                ScrollView {
                    VStack(spacing: 24) {
                        progressHeader
                        switch step {
                        case 1: namePage
                        case 2, 3, 4: recordingPage(sampleIndex: step - 1)
                        case 5: trainingPage
                        default: donePage
                        }
                        navFooter
                    }
                    .padding()
                }
                .navigationTitle("说话人登记")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) {
                        Button("关闭") { cancelWizard() }
                    }
                }
            }
            .onAppear { modelReady = SpeakerRecognizer.shared.isModelReady }
            .onDisappear { cancelRecordingIfActive() }
        }
        .preferredColorScheme(.dark)
    }

    // MARK: - 顶部进度

    private var progressHeader: some View {
        HStack(spacing: 6) {
            ForEach(1...6, id: \.self) { s in
                Capsule()
                    .fill(s <= step ? AnyShapeStyle(OMColors.primaryGradient) : AnyShapeStyle(Color.white.opacity(0.15)))
                    .frame(height: 4)
            }
        }
        .padding(.horizontal, 4)
    }

    // MARK: - 第 1 页：输入名字

    private var namePage: some View {
        VStack(spacing: 20) {
            Image(systemName: "person.crop.circle.badge.plus")
                .font(.system(size: 56))
                .foregroundStyle(OMColors.info)
                .padding(.top, 12)
            Text("先告诉我你的名字")
                .font(OMFonts.title3.weight(.semibold))
                .foregroundStyle(.white)
            Text("之后每次录音都会存到你的名字下，用来训练识别模型")
                .font(OMFonts.caption)
                .foregroundStyle(.white.opacity(0.6))
                .multilineTextAlignment(.center)
            TextField("输入名字（如 Ethan）", text: $speakerName)
                .font(OMFonts.body)
                .foregroundStyle(.white)
                .padding()
                .background(OMColors.surface.opacity(0.8))
                .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                .padding(.horizontal, 8)
            if let err = errorMessage {
                Text(err).font(OMFonts.caption).foregroundStyle(OMColors.error)
            }
            Spacer(minLength: 8)
        }
        .padding()
        .darkCard()
    }

    // MARK: - 第 2~4 页：录音

    private func recordingPage(sampleIndex: Int) -> some View {
        VStack(spacing: 20) {
            Text("样本 \(sampleIndex) / \(totalSamples)")
                .font(OMFonts.title3.weight(.semibold))
                .foregroundStyle(.white)
                .padding(.top, 8)

            VStack(spacing: 6) {
                Text("请说：")
                    .font(OMFonts.caption)
                    .foregroundStyle(.white.opacity(0.6))
                Text("「\(samplePhrase)」")
                    .font(OMFonts.body.weight(.semibold))
                    .foregroundStyle(.white)
                    .multilineTextAlignment(.center)
            }
            .padding()
            .frame(maxWidth: .infinity)
            .background(OMColors.surface.opacity(0.8))
            .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))

            // 录音按钮：开始 / 停止
            Button { Task { await toggleRecording() } } label: {
                ZStack {
                    Circle()
                        .fill(isRecording ? AnyShapeStyle(OMColors.error) : AnyShapeStyle(OMColors.primaryGradient))
                        .frame(width: 88, height: 88)
                        .shadow(color: (isRecording ? OMColors.error : OMColors.info).opacity(0.5), radius: isRecording ? 18 : 10)
                    Image(systemName: isRecording ? "stop.fill" : "mic.fill")
                        .font(.system(size: 34, weight: .bold))
                        .foregroundStyle(.white)
                }
            }
            .buttonStyle(.plain)
            .disabled(!isRecording && savedInfo != nil)   // 保存后本页不能再录（除非重录）

            if isRecording {
                HStack(spacing: 8) {
                    Circle()
                        .fill(OMColors.error)
                        .frame(width: 8, height: 8)
                    Text("正在录音… \(elapsed) 秒，说完再点一次停止")
                        .font(OMFonts.caption.weight(.medium))
                        .foregroundStyle(.white.opacity(0.9))
                }
            } else if let info = savedInfo {
                Label(info, systemImage: "checkmark.circle.fill")
                    .font(OMFonts.caption.weight(.medium))
                    .foregroundStyle(OMColors.success)
            }
            if let err = errorMessage {
                Text(err).font(OMFonts.caption).foregroundStyle(OMColors.error)
            }

            if !isRecording && savedInfo != nil {
                Button("重录这个样本") { reRecord() }
                    .font(OMFonts.caption.weight(.medium))
                    .foregroundStyle(OMColors.info)
                    .buttonStyle(.plain)
            }
            Spacer(minLength: 8)
        }
        .padding()
        .darkCard()
    }

    // MARK: - 第 5 页：训练模型

    private var trainingPage: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(spacing: 8) {
                Image(systemName: modelReady ? "checkmark.circle.fill" : "cpu")
                    .foregroundStyle(modelReady ? OMColors.success : OMColors.info)
                Text(modelReady ? "模型已就绪" : "训练模型（在 Mac 上做一次）")
                    .font(OMFonts.title3.weight(.semibold))
                    .foregroundStyle(.white)
            }
            VStack(alignment: .leading, spacing: 10) {
                trainStep("1", "把样本从 App 里导出到 Mac 的 speaker_samples 文件夹")
                trainStep("2", "打开终端，运行 tools/train_speaker.swift")
                trainStep("3", "等训练完成，生成 SpeakerModel.mlmodel")
                trainStep("4", "把模型拖进 Xcode 工程（勾上 target membership）")
                trainStep("5", "重新编译运行 App，本页会显示「模型已就绪」")
            }
            Text("样本已存：\(SpeakerRecognizer.shared.sampleCount(forSpeaker: speakerName)) 个")
                .font(OMFonts.caption)
                .foregroundStyle(.white.opacity(0.6))
        }
        .padding()
        .darkCard()
    }

    private func trainStep(_ n: String, _ text: String) -> some View {
        HStack(alignment: .top, spacing: 10) {
            Text(n)
                .font(OMFonts.caption.weight(.bold))
                .foregroundStyle(OMColors.info)
                .frame(width: 18, height: 18)
                .background(OMColors.info.opacity(0.15))
                .clipShape(Circle())
            Text(text).font(OMFonts.caption).foregroundStyle(.white.opacity(0.75)).lineSpacing(3)
        }
    }

    // MARK: - 第 6 页：完成

    private var donePage: some View {
        VStack(spacing: 20) {
            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 56))
                .foregroundStyle(OMColors.success)
                .padding(.top, 12)
            Text("完成！")
                .font(OMFonts.title3.weight(.semibold))
                .foregroundStyle(.white)
            VStack(spacing: 8) {
                infoRow("说话人", speakerName)
                infoRow("已录样本", "\(SpeakerRecognizer.shared.sampleCount(forSpeaker: speakerName)) 个")
            }
            Text("下一步：按第 5 页的步骤训练模型，训练完模型就绪，聊天时会自动识别是谁在说话")
                .font(OMFonts.caption)
                .foregroundStyle(.white.opacity(0.6))
                .multilineTextAlignment(.center)
            Spacer(minLength: 8)
        }
        .padding()
        .darkCard()
    }

    private func infoRow(_ k: String, _ v: String) -> some View {
        HStack {
            Text(k).font(OMFonts.caption).foregroundStyle(.white.opacity(0.5))
            Spacer()
            Text(v).font(OMFonts.body.weight(.medium)).foregroundStyle(.white)
        }
        .padding(.horizontal, 4)
    }

    // MARK: - 底部导航

    private var navFooter: some View {
        HStack {
            if step > 1 && step <= 5 {
                Button("上一步") { goBack() }
                    .buttonStyle(plainNav())
            }
            Spacer()
            if step == 1 {
                Button("下一步") { goNext() }
                    .buttonStyle(plainNav(accent: true))
                    .disabled(speakerName.trimmingCharacters(in: .whitespaces).isEmpty)
            } else if step <= 4 {
                Button("下一步") { goNext() }
                    .buttonStyle(plainNav(accent: true))
                    .disabled(savedInfo == nil || isRecording)
            } else if step == 5 {
                Button("下一步") { goNext() }
                    .buttonStyle(plainNav(accent: true))
            } else {
                Button("完成") { dismiss() }
                    .buttonStyle(plainNav(accent: true))
            }
        }
        .padding(.horizontal, 4)
    }

    // MARK: - 动作

    private func goNext() {
        stopTimer()
        if step == 1 {
            step = 2
            return
        }
        if step >= 2 && step <= 4 {
            guard savedInfo != nil, !isRecording else { return }
            step += 1
            savedInfo = nil
            lastSavedURL = nil
            errorMessage = nil
            if step >= 6 { modelReady = SpeakerRecognizer.shared.isModelReady }
            return
        }
        step += 1
    }

    private func goBack() {
        stopTimer()
        if isRecording {
            SpeakerRecognizer.shared.cancelRecording()
            isRecording = false
        }
        savedInfo = nil
        lastSavedURL = nil
        errorMessage = nil
        step -= 1
    }

    private func cancelWizard() {
        stopTimer()
        cancelRecordingIfActive()
        dismiss()
    }

    private func cancelRecordingIfActive() {
        if isRecording {
            SpeakerRecognizer.shared.cancelRecording()
            isRecording = false
        }
    }

    private func toggleRecording() async {
        if isRecording {
            // 停止并保存
            if let (url, duration) = SpeakerRecognizer.shared.stopRecording() {
                savedInfo = "样本 \(step - 1) 已保存（\(Int(duration)) 秒）"
                lastSavedURL = url
                errorMessage = nil
            } else {
                errorMessage = "停止录音失败，请重试"
            }
            isRecording = false
            stopTimer()
        } else {
            errorMessage = nil
            savedInfo = nil
            lastSavedURL = nil
            do {
                let ok = try await SpeakerRecognizer.shared.beginRecording(forSpeaker: speakerName)
                guard ok else {
                    errorMessage = "无法开始录音：请检查麦克风权限（系统设置 → 隐私与安全性 → 麦克风）"
                    return
                }
                isRecording = true
                elapsed = 0
                startTimer()
            } catch {
                errorMessage = "无法开始录音：\(error.localizedDescription)"
            }
        }
    }

    private func reRecord() {
        if let url = lastSavedURL {
            SpeakerRecognizer.shared.deleteSample(at: url)
        }
        savedInfo = nil
        lastSavedURL = nil
    }

    private func startTimer() {
        timer?.invalidate()
        timer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { _ in
            Task { @MainActor in
                if isRecording { elapsed += 1 }
            }
        }
    }

    private func stopTimer() {
        timer?.invalidate()
        timer = nil
    }
}

// 深色实心卡片
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

// 导航按钮样式
struct plainNav: ButtonStyle {
    var accent = false
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(OMFonts.subheadline.weight(.semibold))
            .foregroundStyle(accent ? .white : .white.opacity(0.7))
            .padding(.horizontal, 20)
            .padding(.vertical, 10)
            .background(accent ? AnyShapeStyle(OMColors.primaryGradient) : AnyShapeStyle(Color.white.opacity(0.1)))
            .clipShape(Capsule())
            .opacity(configuration.isPressed ? 0.7 : 1)
    }
}

#Preview {
    SpeakerEnrollmentView()
        .preferredColorScheme(.dark)
}
