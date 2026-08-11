import SwiftUI

struct ChatView: View {
    @Environment(ChatViewModel.self) private var chatVM

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
        VStack(spacing: 0) {
            Divider()
            HStack(spacing: 8) {
                ZStack(alignment: .topLeading) {
                    MultilineTextField(
                        text: Bindable(chatVM).inputText,
                        onEnter: { chatVM.send() },       // 回车 = 发送
                        onCtrlEnter: { chatVM.inputText += "\n" }  // Ctrl+回车 = 换行
                    )
                    .frame(height: 40)
                    .padding(.horizontal, 12)
                    .background(Color(.systemGray6))
                    .clipShape(RoundedRectangle(cornerRadius: 20))

                    // placeholder 用 overlay 显示，绝不写进输入框内容；
                    // 左移 18pt 让光标露在 placeholder 前面（光标在文本起点）
                    if chatVM.inputText.isEmpty {
                        Text("输入消息...")
                            .foregroundStyle(.placeholder)
                            .padding(.leading, 18)
                            .padding(.trailing, 12)
                            .padding(.vertical, 11)
                            .allowsHitTesting(false)
                    }
                }

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
