import SwiftUI

// MARK: - Settings View New
struct SettingsViewNew: View {
    @AppStorage("serverURL") private var storedServerURL = "http://127.0.0.1:18890"
    @State private var serverURL: String
    @State private var saved = false
    @State private var isConnected: Bool? = nil
    @State private var backendModel: String? = nil
    @State private var checking = false
    @State private var healthStatus: String? = nil
    @AppStorage("wakeWordEnabled") private var wakeWordEnabled = true
    @State private var showingClearConfirmation = false

    init() {
        // 启动时把持久化的地址应用到 API 客户端
        let stored = UserDefaults.standard.string(forKey: "serverURL") ?? "http://127.0.0.1:18890"
        OpenMemoAPI.shared.baseURL = stored
        _serverURL = State(initialValue: stored)
    }

    var body: some View {
        ZStack {
            // Background — settings wallpaper (teal/cyan aurora)
            OMBackground(.settings)

            ScrollView {
                VStack(spacing: 24) {
                    // Header
                    HStack {
                        Text("设置")
                            .font(OMFonts.largeTitle)
                            .foregroundStyle(.white)
                        Spacer()
                    }
                    .padding(.horizontal)
                    .padding(.top, 8)

                    // Server section
                    settingsSection(title: "服务器") {
                        VStack(alignment: .leading, spacing: 12) {
                            Text("服务器地址")
                                .font(OMFonts.subheadline)
                                .foregroundStyle(.white.opacity(0.7))

                            TextField("", text: $serverURL)
                                .font(OMFonts.body)
                                .foregroundStyle(.white)
                                .padding()
                                .glass(cornerRadius: 14)
                                .keyboardType(.URL)
                                .autocapitalization(.none)
                                .onChange(of: serverURL) { _, _ in saved = false }

                            HStack(spacing: 12) {
                                // 保存 + 应用新地址
                                Button {
                                    applyServerURL()
                                } label: {
                                    HStack(spacing: 6) {
                                        Image(systemName: "checkmark.circle.fill")
                                        Text("保存并连接")
                                    }
                                    .font(OMFonts.subheadline.weight(.semibold))
                                    .foregroundStyle(.white)
                                    .padding(.horizontal, 16)
                                    .padding(.vertical, 10)
                                    .glass(cornerRadius: 12)
                                    .hoverGlow(cornerRadius: 12)
                                }
                                .buttonStyle(.plain)
                                .disabled(checking)

                                // 测试连接（使用当前输入框地址）
                                Button {
                                    check()
                                } label: {
                                    if checking {
                                        ProgressView()
                                            .scaleEffect(0.7)
                                            .frame(width: 24)
                                    } else {
                                        Image(systemName: "bolt.horizontal.circle")
                                            .font(.title3)
                                            .foregroundStyle(.white.opacity(0.8))
                                            .frame(width: 24)
                                    }
                                }
                                .buttonStyle(.plain)
                                .disabled(checking)

                                Spacer()

                                if saved {
                                    Label("已保存", systemImage: "checkmark.circle.fill")
                                        .font(OMFonts.caption)
                                        .foregroundStyle(OMColors.success)
                                } else if let status = healthStatus {
                                    Text(status)
                                        .font(OMFonts.caption)
                                        .foregroundStyle(isConnected == true ? OMColors.success : OMColors.error)
                                }
                            }
                        }
                    }

                    // Voice section
                    settingsSection(title: "语音") {
                        VStack(spacing: 14) {
                            Toggle(isOn: $wakeWordEnabled) {
                                HStack(spacing: 12) {
                                    ZStack {
                                        Circle()
                                            .fill(OMColors.success.opacity(0.2))
                                            .frame(width: 36, height: 36)
                                        Image(systemName: "ear")
                                            .font(.system(size: 16))
                                            .foregroundStyle(OMColors.success)
                                    }

                                    VStack(alignment: .leading, spacing: 2) {
                                        Text("「小麦小麦」唤醒")
                                            .font(OMFonts.subheadline.weight(.medium))
                                            .foregroundStyle(.white)
                                        Text("说出唤醒词即可开始对话")
                                            .font(OMFonts.caption2)
                                            .foregroundStyle(.white.opacity(0.5))
                                    }
                                }
                            }
                            .tint(OMColors.success)

                            Divider()
                                .background(Color.white.opacity(0.1))

                            // 自动检测的 STT 引擎（跨平台：Apple/Android/本地）
                            HStack(spacing: 12) {
                                ZStack {
                                    Circle()
                                        .fill(OMColors.info.opacity(0.2))
                                        .frame(width: 36, height: 36)
                                    Image(systemName: "waveform")
                                        .font(.system(size: 16))
                                        .foregroundStyle(OMColors.info)
                                }

                                VStack(alignment: .leading, spacing: 2) {
                                    Text("语音识别引擎")
                                        .font(OMFonts.subheadline.weight(.medium))
                                        .foregroundStyle(.white)
                                    Text("自动检测：\(STTEngine.currentPlatform.rawValue)")
                                        .font(OMFonts.caption2)
                                        .foregroundStyle(.white.opacity(0.5))
                                }
                                Spacer()
                            }

                            Divider()
                                .background(Color.white.opacity(0.1))

                            // 说话人识别（Apple 原生：Create ML + SoundAnalysis）
                            HStack(spacing: 12) {
                                ZStack {
                                    Circle()
                                        .fill(OMColors.info.opacity(0.2))
                                        .frame(width: 36, height: 36)
                                    Image(systemName: "person.wave.2")
                                        .font(.system(size: 16))
                                        .foregroundStyle(OMColors.info)
                                }

                                VStack(alignment: .leading, spacing: 2) {
                                    Text("说话人识别")
                                        .font(OMFonts.subheadline.weight(.medium))
                                        .foregroundStyle(.white)
                                    Text(SpeakerRecognizer.shared.isModelReady
                                         ? "已就绪：\(SpeakerRecognizer.shared.enrolledSpeakers.joined(separator: "、"))"
                                         : "未训练模型（用 tools/train_speaker.swift 训练）")
                                        .font(OMFonts.caption2)
                                        .foregroundStyle(.white.opacity(0.5))
                                }
                                Spacer()
                            }
                        }
                    }

                    // About section
                    settingsSection(title: "关于") {
                        VStack(spacing: 16) {
                            HStack {
                                VStack(alignment: .leading, spacing: 4) {
                                    Text("OpenMemo")
                                        .font(OMFonts.title3.weight(.semibold))
                                        .foregroundStyle(.white)
                                    Text("Version 1.0.0")
                                        .font(OMFonts.caption)
                                        .foregroundStyle(.white.opacity(0.5))
                                }

                                Spacer()

                                ZStack {
                                    RoundedRectangle(cornerRadius: 16, style: .continuous)
                                        .fill(OMColors.primaryGradient)
                                        .frame(width: 60, height: 60)

                                    Image(systemName: "sparkles")
                                        .font(.system(size: 28))
                                        .foregroundStyle(.white)
                                }
                            }

                            if let model = backendModel, !model.isEmpty {
                                HStack {
                                    Text("后端模型")
                                        .font(OMFonts.subheadline)
                                        .foregroundStyle(.white.opacity(0.6))
                                    Spacer()
                                    Text(model)
                                        .font(OMFonts.subheadline.weight(.medium))
                                        .foregroundStyle(.white)
                                }
                            }

                            Divider()
                                .background(Color.white.opacity(0.1))

                            Button {
                                showingClearConfirmation = true
                            } label: {
                                HStack {
                                    Image(systemName: "trash")
                                    Text("清除所有数据")
                                }
                                .font(OMFonts.subheadline.weight(.medium))
                                .foregroundStyle(OMColors.error)
                                .frame(maxWidth: .infinity, alignment: .leading)
                            }
                        }
                    }

                    Spacer(minLength: 40)
                }
                .padding()
            }
        }
        .alert("确认清除", isPresented: $showingClearConfirmation) {
            Button("取消", role: .cancel) {}
            Button("清除", role: .destructive) {
                clearAllData()
            }
        } message: {
            Text("这将删除所有任务，此操作不可撤销。")
        }
        .task {
            check()
        }
    }

    // MARK: - 服务器操作

    /// 把输入框地址保存到 API 客户端并立即测试连接。
    private func applyServerURL() {
        let trimmed = serverURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        OpenMemoAPI.shared.baseURL = trimmed
        storedServerURL = trimmed          // 持久化，下次启动自动应用
        saved = true
        check()
    }

    /// 清除所有数据：遍历删除服务端全部任务。
    private func clearAllData() {
        let api = OpenMemoAPI.shared
        Task {
            do {
                let resp = try await api.listTasks()
                for task in resp.tasks {
                    _ = try? await api.deleteTask(task.taskId)
                }
                healthStatus = "已清除 \(resp.tasks.count) 个任务"
            } catch {
                healthStatus = "清除失败：\(error.localizedDescription)"
            }
        }
    }

    private func check() {
        checking = true
        healthStatus = nil
        // 用输入框当前地址测试（未保存时也应生效，便于先试后存）
        let testURL = serverURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !testURL.isEmpty else {
            checking = false
            return
        }
        let api = OpenMemoAPI.shared
        let original = api.baseURL
        api.baseURL = testURL
        Task {
            do {
                let h = try await api.health()
                await MainActor.run {
                    backendModel = h.model
                    isConnected = h.status == "running"
                    healthStatus = isConnected == true ? "已连接" : "状态: \(h.status)"
                    checking = false
                }
            } catch {
                await MainActor.run {
                    backendModel = nil
                    isConnected = false
                    healthStatus = "连接失败"
                    checking = false
                }
            }
            // 若用户没点保存，恢复原地址（已保存则保持新地址）
            if !saved {
                api.baseURL = original
            }
        }
    }

    private func settingsSection<Content: View>(title: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 16) {
            Text(title)
                .font(OMFonts.subheadline.weight(.semibold))
                .foregroundStyle(.white.opacity(0.5))
                .textCase(.uppercase)
                .padding(.horizontal, 4)

            VStack(spacing: 0) {
                content()
            }
            .padding()
            .glass(cornerRadius: 20)
        }
        .padding(.horizontal)
    }
}

#Preview {
    SettingsViewNew()
        .preferredColorScheme(.dark)
}
