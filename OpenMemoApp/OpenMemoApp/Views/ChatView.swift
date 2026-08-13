import SwiftUI

struct ChatView: View {
    @Environment(ChatViewModel.self) private var chatVM
    @State private var voice = VoiceInputManager()
    @State private var speechAuthGranted = false

    private let suggestions = [
        "明天下午3点开项目会",
        "每天早上8点提醒我起床",
        "帮妈妈买牛奶",
        "每周二晚上7点提醒我去打球",
    ]

    var body: some View {
        NavigationStack {
            ZStack(alignment: .leading) {
                // 对话区
                VStack(spacing: 0) {
                    messageList
                    inputBar
                }
                .navigationTitle(chatVM.currentTitle)
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .topBarLeading) {
                        Button {
                            withAnimation(.easeInOut(duration: 0.25)) {
                                chatVM.sidebarOpen.toggle()
                            }
                        } label: {
                            Image(systemName: "sidebar.left")
                        }
                    }
                }
                .disabled(chatVM.sidebarOpen)

                // 侧边栏（浮层，DeepSeek 风格）
                if chatVM.sidebarOpen {
                    SidebarView()
                        .transition(.move(edge: .leading))
                }
            }
        }
        .task {
            await chatVM.startFresh()
            // 语音留言完成 → 填入输入框并发送
            voice.onMessageReady = { text in
                chatVM.inputText = text
                chatVM.send()
            }
        }
    }

    // MARK: - 消息列表

    private var messageList: some View {
        ScrollViewReader { scroll in
            ScrollView {
                LazyVStack(spacing: 14) {
                    if chatVM.messages.isEmpty {
                        welcomeCard
                            .padding(.top, 30)
                    } else {
                        ForEach(chatVM.messages) { msg in
                            ChatBubbleView(message: msg)
                                .id(msg.id)
                        }
                        // 输入中提示
                        if chatVM.isSending {
                            TypingBubbleView()
                                .id("typing")
                        }
                    }
                }
                .padding()
            }
            .onChange(of: chatVM.messages.count) { _, _ in
                if let last = chatVM.messages.last {
                    withAnimation { scroll.scrollTo(last.id) }
                }
            }
            .onChange(of: chatVM.isSending) { _, sending in
                if sending {
                    withAnimation { scroll.scrollTo("typing", anchor: .bottom) }
                }
            }
        }
        .scrollDismissesKeyboard(.interactively)
    }

    // MARK: - 欢迎卡片

    private var welcomeCard: some View {
        VStack(spacing: 18) {
            // Logo
            ZStack {
                RoundedRectangle(cornerRadius: 22, style: .continuous)
                    .fill(
                        LinearGradient(colors: [.orange, .pink], startPoint: .topLeading, endPoint: .bottomTrailing)
                    )
                    .frame(width: 76, height: 76)
                Image(systemName: "sparkles")
                    .font(.system(size: 34))
                    .foregroundStyle(.white)
            }
            .shadow(color: .orange.opacity(0.3), radius: 10, y: 4)

            VStack(spacing: 6) {
                Text("我是 OpenMemo")
                    .font(.title2.bold())
                Text("说一句话，我来帮你记任务、设提醒、安排日程")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 30)
            }

            // 能力标签
            HStack(spacing: 8) {
                chip(icon: "note.text", text: "记任务")
                chip(icon: "clock", text: "循环提醒")
                chip(icon: "airplane", text: "出行")
                chip(icon: "newspaper", text: "新闻")
            }

            // 示例
            VStack(alignment: .leading, spacing: 10) {
                Text("试试这样说")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .padding(.leading, 4)

                ForEach(suggestions, id: \.self) { s in
                    Button {
                        chatVM.inputText = s
                        chatVM.send()
                    } label: {
                        HStack {
                            Text(s)
                                .font(.subheadline)
                                .foregroundStyle(.primary)
                            Spacer()
                            Image(systemName: "arrow.up")
                                .font(.caption)
                                .foregroundStyle(.tertiary)
                        }
                        .padding(.horizontal, 14)
                        .padding(.vertical, 11)
                        .background(Color(.secondarySystemGroupedBackground))
                        .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.horizontal, 20)
        }
    }

    private func chip(icon: String, text: String) -> some View {
        Label(text, systemImage: icon)
            .font(.caption)
            .padding(.horizontal, 10)
            .padding(.vertical, 5)
            .background(Color(.secondarySystemGroupedBackground), in: Capsule())
            .foregroundStyle(.secondary)
    }

    // MARK: - 输入栏

    private var inputBar: some View {
        VStack(spacing: 4) {
            // 语音状态提示
            if voice.isListening {
                HStack(spacing: 6) {
                    Image(systemName: voice.isTranscribing ? "mic.fill" : "ear")
                        .foregroundStyle(voice.isTranscribing ? .red : .green)
                    Text(voice.isTranscribing
                         ? (voice.liveText.isEmpty ? "在听… 静音 2 秒自动发送" : "\(voice.liveText)")
                         : "在听…")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                    Spacer()
                    Button("取消") { voice.stop() }
                        .font(.caption)
                }
                .padding(.horizontal, 16)
                .transition(.opacity)
            }

            Divider()
            HStack(spacing: 8) {
                ZStack(alignment: .topLeading) {
                    MultilineTextField(
                        text: inputBinding,
                        onEnter: { chatVM.send() },       // 回车 = 发送
                        onCtrlEnter: { chatVM.inputText += "\n" }  // Ctrl+回车 = 换行
                    )
                    .frame(height: 40)
                    .padding(.horizontal, 12)
                    .background(Color(.systemGray6))
                    .clipShape(RoundedRectangle(cornerRadius: 20))

                    if chatVM.inputText.isEmpty {
                        Text("输入消息...")
                            .foregroundStyle(.placeholder)
                            .padding(.leading, 18)
                            .padding(.trailing, 12)
                            .padding(.vertical, 11)
                            .allowsHitTesting(false)
                    }
                }

                // 麦克风：语音留言（静音 2 秒自动发送；权限在点击时才申请，避免启动卡死）
                Button {
                    if voice.isTranscribing {
                        voice.stop()
                        return
                    }
                    Task {
                        if !speechAuthGranted {
                            speechAuthGranted = await VoiceInputManager.requestAuthorization()
                        }
                        guard speechAuthGranted else { return }
                        voice.stop()
                        voice.startVoiceInput()
                    }
                } label: {
                    Image(systemName: voice.isTranscribing ? "mic.fill" : "mic")
                        .font(.title2)
                }
                .foregroundStyle(voice.isTranscribing ? .red : .secondary)
                .disabled(!speechAuthGranted)

                Button {
                    chatVM.send()
                } label: {
                    if chatVM.isSending {
                        ProgressView()
                            .scaleEffect(0.8)
                    } else {
                        Image(systemName: "arrow.up.circle.fill")
                            .font(.title2)
                    }
                }
                .disabled(chatVM.inputText.trimmingCharacters(in: .whitespaces).isEmpty || chatVM.isSending)
            }
            .padding(.horizontal)
            .padding(.vertical, 8)
        }
        .background(.bar)
        .animation(.easeInOut(duration: 0.2), value: voice.isListening)
    }

    /// 输入框绑定：语音留言时实时显示转写文字，否则走普通输入
    private var inputBinding: Binding<String> {
        Binding(
            get: { voice.isTranscribing ? voice.liveText : chatVM.inputText },
            set: { newValue in
                if voice.isTranscribing {
                    voice.liveText = newValue
                } else {
                    chatVM.inputText = newValue
                }
            }
        )
    }
}

// MARK: - 侧边栏

struct SidebarView: View {
    @Environment(ChatViewModel.self) private var chatVM

    var body: some View {
        ZStack(alignment: .leading) {
            // 其余屏幕变暗 -> 点击关闭
            Color.black.opacity(0.3)
                .ignoresSafeArea()
                .onTapGesture { close() }

            // 侧边栏面板
            VStack(spacing: 0) {
                HStack {
                    Text("对话")
                        .font(.headline)
                    Spacer()
                    Button {
                        chatVM.newSession(); close()
                    } label: {
                        Label("新对话", systemImage: "square.and.pencil")
                            .font(.subheadline)
                    }
                }
                .padding()

                Divider()

                if chatVM.isLoading {
                    Spacer()
                    ProgressView()
                    Spacer()
                } else if chatVM.sessions.isEmpty {
                    Spacer()
                    VStack(spacing: 8) {
                        Image(systemName: "text.bubble")
                            .font(.largeTitle)
                            .foregroundStyle(.secondary)
                        Text("还没有历史对话")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                } else {
                    sessionList
                }
            }
            .frame(width: 320)
            .frame(maxHeight: .infinity)
            .background(.regularMaterial)
        }
    }

    private func close() {
        withAnimation(.easeInOut(duration: 0.25)) {
            chatVM.sidebarOpen = false
        }
    }

    private var sessionList: some View {
        let all = chatVM.sessions
        let currentId = chatVM.currentSessionId
        return ScrollView {
            LazyVStack(spacing: 0) {
                ForEach(Array(all.enumerated()), id: \.element.sessionId) { _, session in
                    Button {
                        Task { await chatVM.selectSession(session) }
                    } label: {
                        HStack {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(session.displayTitle)
                                    .font(.subheadline)
                                    .foregroundStyle(.primary)
                                    .lineLimit(1)
                                if let last = session.lastAt {
                                    Text(shortTime(last))
                                        .font(.caption2)
                                        .foregroundStyle(.secondary)
                                }
                            }
                            Spacer()
                            if session.sessionId == currentId {
                                Image(systemName: "checkmark.circle.fill")
                                    .foregroundStyle(Color.accentColor)
                            }
                            Button {
                                Task { await chatVM.deleteSession(session) }
                            } label: {
                                Image(systemName: "trash")
                                    .font(.subheadline)
                                    .foregroundStyle(.red)
                            }
                            .buttonStyle(.borderless)
                        }
                        .padding(.horizontal, 16)
                        .padding(.vertical, 12)
                    }
                    .buttonStyle(.plain)
                    Divider()
                }
            }
        }
    }

    private func shortTime(_ s: String) -> String {
        let cleaned = s.replacingOccurrences(of: "T", with: " ").prefix(16)
        let parts = cleaned.split(separator: " ")
        guard parts.count >= 2 else { return s }
        let dateParts = parts[0].split(separator: "-")
        guard dateParts.count >= 3 else { return String(cleaned) }
        return "\(dateParts[1])-\(dateParts[2]) \(parts[1])"
    }
}

// MARK: - 消息气泡

struct ChatBubbleView: View {
    let message: ChatMessage

    var body: some View {
        HStack(alignment: .bottom, spacing: 8) {
            if message.role == .assistant {
                assistantAvatar
            }

            if message.role == .user {
                Spacer(minLength: 60)
            }

            Text(message.text)
                .padding(.horizontal, 14)
                .padding(.vertical, 10)
                .background(message.role == .user ? Color.accentColor : Color(.systemGray5))
                .foregroundStyle(message.role == .user ? .white : .primary)
                .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
                .textSelection(.enabled)

            if message.role == .assistant {
                Spacer(minLength: 60)
            }
        }
    }

    private var assistantAvatar: some View {
        ZStack {
            Circle()
                .fill(LinearGradient(colors: [.orange, .pink], startPoint: .topLeading, endPoint: .bottomTrailing))
                .frame(width: 30, height: 30)
            Image(systemName: "sparkles")
                .font(.system(size: 13))
                .foregroundStyle(.white)
        }
    }
}

// MARK: - 输入中气泡

struct TypingBubbleView: View {
    @State private var animating = false

    var body: some View {
        HStack(alignment: .bottom, spacing: 8) {
            ZStack {
                Circle()
                    .fill(LinearGradient(colors: [.orange, .pink], startPoint: .topLeading, endPoint: .bottomTrailing))
                    .frame(width: 30, height: 30)
                Image(systemName: "sparkles")
                    .font(.system(size: 13))
                    .foregroundStyle(.white)
            }

            HStack(spacing: 5) {
                ForEach(0..<3, id: \.self) { i in
                    Circle()
                        .fill(.secondary.opacity(0.6))
                        .frame(width: 7, height: 7)
                        .scaleEffect(animating ? 1 : 0.5)
                        .opacity(animating ? 1 : 0.4)
                        .animation(
                            .easeInOut(duration: 0.6)
                                .repeatForever(autoreverses: true)
                                .delay(Double(i) * 0.15),
                            value: animating
                        )
                }
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 12)
            .background(Color(.systemGray5))
            .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))

            Spacer(minLength: 60)
        }
        .onAppear { animating = true }
    }
}
