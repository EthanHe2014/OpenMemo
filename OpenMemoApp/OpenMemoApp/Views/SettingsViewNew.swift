import SwiftUI

// MARK: - Settings View New
struct SettingsViewNew: View {
    @AppStorage("serverURL") private var serverURL = "http://localhost:18890"
    @AppStorage("wakeWordEnabled") private var wakeWordEnabled = true
    @State private var showingClearConfirmation = false
    
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
                        }
                    }
                    
                    // Voice section
                    settingsSection(title: "语音") {
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
                    }
                    
                    // About section
                    settingsSection(title: "关于") {
                        VStack(spacing: 16) {
                            HStack {
                                VStack(alignment: .leading, spacing: 4) {
                                    Text("OpenMemo")
                                        .font(OMFonts.title3.weight(.semibold))
                                        .foregroundStyle(.white)
                                    Text("Version 0.7")
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
                // Clear data logic
            }
        } message: {
            Text("这将删除所有本地数据，此操作不可撤销。")
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
