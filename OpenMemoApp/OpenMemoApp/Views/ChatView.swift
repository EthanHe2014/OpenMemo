import SwiftUI
import Speech

struct ChatView: View {
    @Environment(ChatViewModel.self) private var chatVM
    @State private var voice = VoiceInputManager()
    @State private var speechAuthGranted = false

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
            // 进入时（含应用启动）：新建聊天 + 加载侧边栏。
            await chatVM.startFresh()
            speechAuthGranted = await VoiceInputManager.requestAuthorization()
            // 语音留言完成 → 填入输入框并发送
            voice.onMessageReady = { text in
                chatVM.inputText = text
                chatVM.send()
            }
            voice.onWakeWord = {
                // 唤醒成功：清空输入框准备留言
                chatVM.inputText = ""
            }
        }
    }

    private var messageList: some View {
        ScrollViewReader { scroll in
            ScrollView {
                LazyVStack(spacing: 12) {
                    if chatVM.messages.isEmpty {
                        VStack(spacing: 16) {
                            Image(systemName: "bubble.left.and.bubble.right")
                                .font(.system(size: 48))
                                .foregroundStyle(.secondary)
                            Text("和 OpenMemo 对话")
                                .font(.headline)
                            Text("每人每次登录都会开启全新的对话，旧对话在左侧栏里可以回看或删除。")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                                .multilineTextAlignment(.center)
                                .padding(.horizontal, 40)
                        }
                        .padding(.top, 60)
                    } else {
                        ForEach(chatVM.messages) { msg in
                            ChatBubbleView(message: msg)
                                .id(msg.id)
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
        }
    }

    private var inputBar: some View {
        VStack(spacing: 4) {
            // 语音状态提示
            if voice.isListening {
                HStack(spacing: 6) {
                    Image(systemName: voice.isTranscribing ? "mic.fill" : "ear")
                        .foregroundStyle(voice.isTranscribing ? .red : .green)
                    Text(voice.isTranscribing
                         ? (voice.liveText.isEmpty ? "在听… 静音 2 秒自动发送" : "\(voice.liveText)")
                         : "常听中… 说 \"memo memo\" 开始留言")
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
                TextField("输入消息...", text: inputBinding, axis: .vertical)
                    .textFieldStyle(.plain)
                    .lineLimit(1...4)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 8)
                    .background(Color(.systemGray6))
                    .clipShape(RoundedRectangle(cornerRadius: 20))
                    .submitLabel(.send)   // 软键盘回车键显示为“发送”
                    .onSubmit { chatVM.send() }  // 软键盘“发送”键
                    .onKeyPress(.return, phases: .down) { press in  // 硬件键盘：回车=发送，Ctrl+回车=换行
                        if press.modifiers.contains(.control) {
                            chatVM.inputText += "\n"
                        } else {
                            chatVM.send()
                        }
                        return .handled
                    }

                // 唤醒词常听开关（前台）
                Button {
                    if voice.isListening && !voice.isTranscribing {
                        voice.stop()
                    } else {
                        voice.stop()
                        voice.startWakeListening()
                    }
                } label: {
                    Image(systemName: voice.isListening && !voice.isTranscribing ? "ear.fill" : "ear")
                        .font(.title2)
                }
                .foregroundStyle((voice.isListening && !voice.isTranscribing) ? .green : .secondary)
                .disabled(!speechAuthGranted)

                // 麦克风：语音留言
                Button {
                    if voice.isTranscribing {
                        voice.stop()
                    } else {
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

// MARK: - 气泡

struct ChatBubbleView: View {
    let message: ChatMessage

    var body: some View {
        HStack {
            if message.role == .user { Spacer(minLength: 60) }
            Text(message.text)
                .padding(.horizontal, 14)
                .padding(.vertical, 10)
                .background(message.role == .user ? Color.accentColor : Color(.systemGray5))
                .foregroundStyle(message.role == .user ? .white : .primary)
                .clipShape(RoundedRectangle(cornerRadius: 18))
                .textSelection(.enabled)
            if message.role == .assistant {
                Spacer(minLength: 60)
            }
        }
    }
}
