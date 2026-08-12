import SwiftUI

struct SettingsView: View {
    @State private var serverURL = OpenMemoAPI.shared.baseURL
    @State private var saved = false
    @State private var healthStatus: String? = nil
    @State private var checking = false
    @State private var backendModel: String? = nil
    @State private var lastChecked = false

    var body: some View {
        NavigationStack {
            Form {
                // 头部：Logo + 名称
                Section {
                    HStack(spacing: 14) {
                        ZStack {
                            RoundedRectangle(cornerRadius: 14, style: .continuous)
                                .fill(
                                    LinearGradient(colors: [.orange, .pink], startPoint: .topLeading, endPoint: .bottomTrailing)
                                )
                                .frame(width: 52, height: 52)
                            Image(systemName: "sparkles")
                                .font(.system(size: 24))
                                .foregroundStyle(.white)
                        }
                        VStack(alignment: .leading, spacing: 2) {
                            Text("OpenMemo")
                                .font(.headline)
                            Text("AI 语音助手 · 任务提醒")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        Spacer()
                        if let status = healthStatus {
                            Label(status.hasPrefix("✅") ? "已连接" : "未连接",
                                  systemImage: status.hasPrefix("✅") ? "circle.fill" : "circle")
                                .font(.caption)
                                .foregroundStyle(status.hasPrefix("✅") ? .green : .red)
                        }
                    }
                    .padding(.vertical, 4)
                }
                .listRowBackground(Color.clear)

                // 服务器连接
                Section("服务器连接") {
                    TextField("服务器地址", text: $serverURL)
                        .keyboardType(.URL)
                        .autocorrectionDisabled()
                        .textInputAutocapitalization(.never)
                        .onChange(of: serverURL) { _, _ in saved = false }

                    HStack {
                        Button {
                            check()
                        } label: {
                            if checking {
                                ProgressView()
                                    .scaleEffect(0.8)
                            } else {
                                Label("测试连接", systemImage: "bolt.horizontal.circle")
                            }
                        }
                        .disabled(checking)

                        Spacer()

                        if saved {
                            Label("已保存", systemImage: "checkmark.circle.fill")
                                .foregroundStyle(.green)
                                .font(.caption)
                        } else if let status = healthStatus, lastChecked {
                            Text(status)
                                .font(.caption)
                                .foregroundStyle(status.hasPrefix("✅") ? .green : (status.hasPrefix("⚠️") ? .orange : .red))
                        }
                    }
                }

                // 关于
                Section("关于") {
                    LabeledContent("名称", value: "OpenMemo")
                    LabeledContent("版本", value: "1.0.0")
                    LabeledContent("后端", value: "FastAPI")
                    if let model = backendModel, !model.isEmpty {
                        LabeledContent("模型", value: model)
                    }
                }

                // 使用提示
                Section("使用提示") {
                    Label("直接说 \"明天下午3点开会\"，帮你记任务", systemImage: "1.circle")
                        .font(.caption)
                    Label("说 \"每天早上8点提醒我\"，建立循环提醒", systemImage: "2.circle")
                        .font(.caption)
                    Label("说 \"牛奶买好了\"，完成任务", systemImage: "3.circle")
                        .font(.caption)
                    Label("回车发送 · Ctrl+回车换行", systemImage: "4.circle")
                        .font(.caption)
                }

                Section("注意") {
                    Text("当前使用快速隧道地址，隧道重启后地址会变化，需在此更新服务器地址。V2 可使用固定域名解决。")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            .navigationTitle("设置")
        }
        .task {
            // 进入设置页自动测一次连接
            check()
        }
    }

    private func check() {
        checking = true
        healthStatus = nil
        Task {
            do {
                let h = try await OpenMemoAPI.shared.health()
                let isOK = h.status == "running"
                await MainActor.run {
                    backendModel = h.model
                    healthStatus = isOK ? "✅ 已连接" : "⚠️ 状态: \(h.status)"
                    checking = false
                    lastChecked = true
                }
            } catch {
                await MainActor.run {
                    backendModel = nil
                    healthStatus = "❌ 连接失败"
                    checking = false
                    lastChecked = true
                }
            }
        }
    }
}
