import SwiftUI

struct SettingsView: View {
    @State private var serverURL = OpenMemoAPI.shared.baseURL
    @State private var saved = false
    @State private var healthStatus: String? = nil
    @State private var checking = false
    @State private var backendModel: String? = nil

    var body: some View {
        NavigationStack {
            Form {
                Section("服务器连接") {
                    TextField("服务器地址", text: $serverURL)
                        .keyboardType(.URL)
                        .autocorrectionDisabled()
                        .textInputAutocapitalization(.never)
                        .onChange(of: serverURL) { _, _ in saved = false }

                    Button("保存服务器地址") {
                        OpenMemoAPI.shared.baseURL = serverURL
                            .trimmingCharacters(in: .whitespaces)
                            .replacingOccurrences(of: "/+$", with: "", options: .regularExpression)
                        saved = true
                    }
                    .disabled(serverURL.trimmingCharacters(in: .whitespaces).isEmpty)

                    if saved {
                        Label("已保存", systemImage: "checkmark.circle.fill")
                            .foregroundStyle(.green)
                            .font(.caption)
                    }
                }

                Section("连接测试") {
                    HStack {
                        Button("测试连接") {
                            check()
                        }
                        Spacer()
                        if checking {
                            ProgressView()
                        } else if let status = healthStatus {
                            Label(status, systemImage: status == "✅ 已连接" ? "checkmark.circle" : "xmark.circle")
                                .foregroundStyle(status == "✅ 已连接" ? .green : .red)
                                .font(.caption)
                        }
                    }
                }

                Section("关于") {
                    LabeledContent("名称", value: "OpenMemo iOS")
                    LabeledContent("版本", value: "1.0.0")
                    LabeledContent("后端", value: "FastAPI")
                    if let model = backendModel, !model.isEmpty {
                        LabeledContent("模型", value: model)
                    }
                    Text("任务提醒 · AI 对话 · 日程管理")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                Section("注意") {
                    Text("当前使用快速隧道地址，隧道重启后地址会变化，需在此更新服务器地址。V2 可使用固定域名解决。")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            .navigationTitle("设置")
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
                }
            } catch {
                await MainActor.run {
                    backendModel = nil
                    healthStatus = "❌ 失败: \(error.localizedDescription)"
                    checking = false
                }
            }
        }
    }
}