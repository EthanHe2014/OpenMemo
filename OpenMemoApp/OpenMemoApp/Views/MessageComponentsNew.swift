import SwiftUI

// MARK: - Message Bubble
struct MessageBubbleNew: View {
    let message: ChatMessage
    @State private var isPressed = false
    
    var body: some View {
        HStack(alignment: .bottom, spacing: 12) {
            if message.role == .assistant {
                AssistantAvatar()
            }
            
            if message.role == .user {
                Spacer(minLength: 60)
            }
            
            VStack(alignment: message.role == .user ? .trailing : .leading, spacing: 4) {
                // Message content
                Text(message.text)
                    .font(OMFonts.body)
                    .foregroundStyle(message.role == .user ? .white : .white.opacity(0.95))
                    .padding(.horizontal, 18)
                    .padding(.vertical, 14)
                    .background(
                        messageBackground
                    )
                    .contextMenu {
                        Button {
                            UIPasteboard.general.string = message.text
                        } label: {
                            Label("复制", systemImage: "doc.on.doc")
                        }
                    }
                
                // Timestamp
                if let time = messageTime(message) {
                    Text(time)
                        .font(OMFonts.caption2)
                        .foregroundStyle(.white.opacity(0.4))
                        .padding(.horizontal, 4)
                }
                
                // 说话人标签（气泡底部）
                if let speaker = message.speaker, !speaker.isEmpty {
                    HStack(spacing: 3) {
                        Image(systemName: "person.fill")
                            .font(.system(size: 8))
                        Text(speaker)
                            .font(OMFonts.caption2.weight(.medium))
                    }
                    .foregroundStyle(.white.opacity(0.45))
                    .padding(.horizontal, 4)
                }
            }
            
            if message.role == .assistant {
                Spacer(minLength: 60)
            }
        }
        .scaleEffect(isPressed ? 0.98 : 1)
        .animation(.easeInOut(duration: 0.1), value: isPressed)
        .onLongPressGesture(minimumDuration: 0.3, pressing: { pressing in
            isPressed = pressing
        }, perform: {})
    }
    
    private var messageBackground: some View {
        Group {
            if message.role == .user {
                // User: gradient bubble
                OMColors.primaryGradient
                    .clipShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
                    .shadow(color: Color(hex: "FF6B6B").opacity(0.3), radius: 12, x: 0, y: 6)
            } else {
                // Assistant: glass bubble
                RoundedRectangle(cornerRadius: 22, style: .continuous)
                    .fill(Color.white.opacity(0.08))
                    .background(.ultraThinMaterial)
                    .clipShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
                    .overlay(
                        RoundedRectangle(cornerRadius: 22, style: .continuous)
                            .stroke(Color.white.opacity(0.12), lineWidth: 1)
                    )
            }
        }
    }
    
    /// 消息时间：ChatMessage 无时间戳字段，暂不显示（保留占位以方便后续加）
    private func messageTime(_ message: ChatMessage) -> String? {
        nil
    }
}

// MARK: - Assistant Avatar
struct AssistantAvatar: View {
    @State private var isAnimating = false
    
    var body: some View {
        ZStack {
            // Glow
            Circle()
                .fill(OMColors.primaryGradient)
                .frame(width: 36, height: 36)
                .blur(radius: 8)
                .opacity(0.5)
            
            // Main circle
            Circle()
                .fill(OMColors.surfaceElevated)
                .frame(width: 36, height: 36)
                .overlay(
                    Circle()
                        .stroke(OMColors.primaryGradient, lineWidth: 1.5)
                )
            
            // Sparkle icon with subtle animation
            Image(systemName: "sparkles")
                .font(.system(size: 16, weight: .semibold))
                .foregroundStyle(OMColors.primaryGradient)
                .rotationEffect(.degrees(isAnimating ? 10 : -10))
                .animation(.easeInOut(duration: 3).repeatForever(autoreverses: true), value: isAnimating)
        }
        .onAppear { isAnimating = true }
    }
}

// MARK: - Typing Indicator
struct TypingIndicatorNew: View {
    @State private var isAnimating = false
    
    var body: some View {
        HStack(alignment: .bottom, spacing: 12) {
            AssistantAvatar()
            
            HStack(spacing: 4) {
                ForEach(0..<3) { i in
                    Dot(index: i, isAnimating: isAnimating)
                }
            }
            .padding(.horizontal, 18)
            .padding(.vertical, 18)
            .glass(cornerRadius: 22)
            
            Spacer(minLength: 60)
        }
        .onAppear { isAnimating = true }
    }
    
    struct Dot: View {
        let index: Int
        let isAnimating: Bool
        
        var body: some View {
            Circle()
                .fill(Color.white.opacity(0.6))
                .frame(width: 7, height: 7)
                .scaleEffect(isAnimating ? 1.2 : 0.6)
                .opacity(isAnimating ? 1 : 0.4)
                .offset(y: isAnimating ? -4 : 0)
                .animation(
                    .easeInOut(duration: 0.5)
                    .repeatForever(autoreverses: true)
                    .delay(Double(index) * 0.15),
                    value: isAnimating
                )
        }
    }
}

// MARK: - Sidebar View New
struct SidebarViewNew: View {
    @Environment(ChatViewModel.self) private var chatVM
    let onClose: () -> Void
    @State private var isVisible = false
    @State private var renameTarget: ChatSession?
    @State private var renameText = ""
    
    var body: some View {
        ZStack(alignment: .leading) {
            // Backdrop: 轻遮罩（不盖死内容，点空白处关闭）
            Color.black
                .opacity(0.35)
                .ignoresSafeArea()
                .onTapGesture { close() }
            
            // Sidebar panel
            VStack(spacing: 0) {
                // Header
                HStack {
                    Text("对话历史")
                        .font(OMFonts.title2)
                        .foregroundStyle(.white)
                    
                    Spacer()
                    
                    Button {
                        Task {
                            await chatVM.startNewChat()
                            close()
                        }
                    } label: {
                        HStack(spacing: 6) {
                            Image(systemName: "plus")
                            Text("新对话")
                        }
                        .font(OMFonts.subheadline.weight(.medium))
                        .foregroundStyle(.white)
                        .padding(.horizontal, 12)
                        .padding(.vertical, 8)
                        .glass(cornerRadius: 12)
                        .hoverGlow()
                    }
                }
                .padding()
                
                Divider()
                    .background(Color.white.opacity(0.1))
                
                // Session list
                if chatVM.isLoading {
                    Spacer()
                    ProgressView()
                        .scaleEffect(1.2)
                        .tint(.white)
                    Spacer()
                } else if chatVM.sessions.isEmpty {
                    emptyState
                } else {
                    sessionList
                }
            }
            .frame(width: 320)
            .frame(maxHeight: .infinity)
            .background(
                // 暗色极光玻璃：与聊天/任务页同一套视觉语言，不再是灰盒子
                ZStack {
                    OMColors.background.opacity(0.96)
                    // 顶部紫色极光
                    Circle()
                        .fill(LinearGradient(colors: [Color(hex: "7C6FF0"), Color(hex: "C46BF0")],
                                             startPoint: .topLeading, endPoint: .bottomTrailing))
                        .frame(width: 460, height: 460)
                        .blur(radius: 130)
                        .offset(x: -60, y: -300)
                        .opacity(0.28)
                    // 底部蓝色微光
                    Circle()
                        .fill(Color(hex: "5B8DEF").opacity(0.16))
                        .frame(width: 320, height: 320)
                        .blur(radius: 110)
                        .offset(x: 130, y: 320)
                    // 极淡玻璃层，让内容在深底上更柔和
                    Color.white.opacity(0.03)
                }
            )
            .overlay(
                // 右缘高光（分隔主区域）
                Rectangle()
                    .fill(LinearGradient(colors: [.white.opacity(0.14), .white.opacity(0.03)],
                                         startPoint: .top, endPoint: .bottom))
                    .frame(width: 1)
                    .frame(maxWidth: .infinity, alignment: .trailing)
            )
            .clipShape(RoundedRectangle(cornerRadius: 0))
            .shadow(color: .black.opacity(0.5), radius: 26, x: 10, y: 0)
            .offset(x: isVisible ? 0 : -320)
            .animation(OMAnimations.spring, value: isVisible)
        }
        .onAppear { isVisible = true }
        .alert("重命名会话", isPresented: Binding(
            get: { renameTarget != nil },
            set: { if !$0 { renameTarget = nil } }
        )) {
            TextField("新名字", text: $renameText)
            Button("取消", role: .cancel) { renameTarget = nil }
            Button("确定") {
                if let target = renameTarget {
                    Task { await chatVM.renameSession(target, to: renameText) }
                }
                renameTarget = nil
            }
        } message: {
            Text("输入这个会话的新名字")
        }
        .onChange(of: renameTarget) { _, newValue in
            if let s = newValue { renameText = s.title }
        }
    }
    
    private var emptyState: some View {
        VStack(spacing: 16) {
            Spacer()
            
            ZStack {
                Circle()
                    .fill(Color.white.opacity(0.05))
                    .frame(width: 80, height: 80)
                
                Image(systemName: "text.bubble")
                    .font(.system(size: 32))
                    .foregroundStyle(.white.opacity(0.3))
            }
            
            Text("还没有历史对话")
                .font(OMFonts.subheadline)
                .foregroundStyle(.white.opacity(0.5))
            
            Spacer()
        }
    }
    
    private var sessionList: some View {
        ScrollView {
            LazyVStack(spacing: 8) {
                ForEach(chatVM.sessions) { session in
                    SessionRow(
                        session: session,
                        isSelected: session.sessionId == chatVM.currentSessionId,
                        isLocked: chatVM.isLockedSession(session.sessionId),
                        showDelete: chatVM.canDeleteSession(session.sessionId),
                        showRename: chatVM.canRenameSession(session.sessionId)
                    ) {
                        Task {
                            await chatVM.selectSession(session)
                            close()
                        }
                    } onRename: {
                        renameTarget = session
                    } onDelete: {
                        Task { await chatVM.deleteSession(session) }
                    }
                }
            }
            .padding()
        }
    }
    
    private func close() {
        withAnimation(OMAnimations.spring) {
            isVisible = false
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
            onClose()
        }
    }
}

// MARK: - Session Row
struct SessionRow: View {
    let session: ChatSession
    let isSelected: Bool
    var isLocked: Bool = false
    var showDelete: Bool = true
    var showRename: Bool = true
    let onSelect: () -> Void
    let onRename: () -> Void
    let onDelete: () -> Void
    
    @State private var showingDelete = false
    
    var body: some View {
        Button(action: onSelect) {
            HStack(spacing: 12) {
                // Icon
                ZStack {
                    Circle()
                        .fill(isSelected ? AnyShapeStyle(OMColors.primaryGradient) : AnyShapeStyle(Color.white.opacity(0.1)))
                        .frame(width: 40, height: 40)
                    
                    Image(systemName: isLocked ? "lock.fill" : "bubble.left.fill")
                        .font(.system(size: 16))
                        .foregroundStyle(isSelected ? .white : .white.opacity(0.7))
                }
                
                // Content
                VStack(alignment: .leading, spacing: 4) {
                    Text(session.displayTitle)
                        .font(OMFonts.subheadline.weight(isSelected ? .semibold : .medium))
                        .foregroundStyle(.white)
                        .lineLimit(1)
                    
                    if let last = session.lastAt {
                        Text(formatTime(last))
                            .font(OMFonts.caption2)
                            .foregroundStyle(.white.opacity(0.5))
                    }
                }
                
                Spacer()
                
                // 重命名 + 删除按钮（都只有会话主人可见）
                HStack(spacing: 4) {
                    if showRename {
                        Button {
                            onRename()
                        } label: {
                            Image(systemName: "pencil")
                                .font(.system(size: 12, weight: .medium))
                                .foregroundStyle(.white.opacity(0.7))
                                .frame(width: 26, height: 26)
                                .background(Color.white.opacity(0.08))
                                .clipShape(Circle())
                                .hoverGlow()
                        }
                        .buttonStyle(.plain)
                    }
                    
                    if showDelete {
                        Button {
                            onDelete()
                        } label: {
                            Image(systemName: "trash")
                                .font(.system(size: 12, weight: .medium))
                                .foregroundStyle(.white.opacity(0.7))
                                .frame(width: 26, height: 26)
                                .background(Color.white.opacity(0.08))
                                .clipShape(Circle())
                                .hoverGlow(color: OMColors.danger)   // 悬停红色发光
                        }
                        .buttonStyle(.plain)
                    }
                }
                
                // Selection indicator
                if isSelected {
                    Image(systemName: "checkmark.circle.fill")
                        .foregroundStyle(OMColors.success)
                }
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 10)
            .background(
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .fill(OMColors.primaryGradient)
                    .opacity(isSelected ? 0.45 : 0)
            )
            .overlay(
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .stroke(isSelected ? Color.white.opacity(0.28) : Color.white.opacity(0.06), lineWidth: 1)
            )
            .hoverGlow()
        }
        .buttonStyle(.plain)
        .contextMenu {
            Button(role: .destructive, action: onDelete) {
                Label("删除", systemImage: "trash")
            }
        }
        .swipeActions(edge: .trailing) {
            Button(role: .destructive, action: onDelete) {
                Image(systemName: "trash")
            }
        }
    }
    
    private func formatTime(_ timestamp: String) -> String {
        let cleaned = timestamp.replacingOccurrences(of: "T", with: " ").prefix(16)
        let parts = cleaned.split(separator: " ")
        guard parts.count >= 2 else { return String(cleaned) }
        let dateParts = parts[0].split(separator: "-")
        guard dateParts.count >= 3 else { return String(cleaned) }
        return "\(dateParts[1])-\(dateParts[2]) \(parts[1])"
    }
}

#Preview {
    ZStack {
        OMColors.background.ignoresSafeArea()
        
        VStack(spacing: 20) {
            MessageBubbleNew(message: ChatMessage(
                role: .assistant,
                text: "你好！我是 OpenMemo，可以帮你记录任务、设置提醒。有什么我可以帮你的吗？"
            ))
            
            MessageBubbleNew(message: ChatMessage(
                role: .user,
                text: "明天下午3点提醒我开会"
            ))
            
            TypingIndicatorNew()
        }
        .padding()
    }
}
