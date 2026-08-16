import SwiftUI

struct ChatViewNew: View {
    @Environment(ChatViewModel.self) private var chatVM
    // 统一 STT 层：自动检测平台（Apple→系统识别 / Android→系统识别 / 其它→本地）
    @State private var voice: any STTProvider = STTEngine.shared
    @State private var speechAuthGranted = false
    @State private var showSidebar = false
    
    private let suggestions = [
        "明天下午3点开项目会",
        "每天早上8点提醒我起床",
        "帮妈妈买牛奶",
        "每周二晚上7点提醒我去打球",
    ]
    
    var body: some View {
        ZStack {
            // Background — chat wallpaper (purple/pink aurora)
            OMBackground(.chat)
            
            VStack(spacing: 0) {
                // Custom navigation bar
                navBar
                
                // Messages
                messageList
                
                // Input area
                inputSection
            }
            
            // Sidebar overlay（与 Mac 一致：滑出侧栏）
            if showSidebar {
                SidebarViewNew(onClose: {
                    withAnimation(OMAnimations.spring) {
                        showSidebar = false
                    }
                })
                .transition(.move(edge: .leading))
            }
        }
        .task {
            await chatVM.startFresh()
            voice.onMessageReady = { text in
                chatVM.inputText = text
                chatVM.send()
            }
            // 唤醒词开关（设置页持久化）：默认开，关了就不监听（与 Mac 一致）
            let wakeEnabled = UserDefaults.standard.object(forKey: "wakeWordEnabled") as? Bool ?? true
            if wakeEnabled {
                if !speechAuthGranted {
                    speechAuthGranted = await VoiceInputManager.requestAuthorization()
                }
                if speechAuthGranted {
                    voice.setWakeMode(true)
                }
            } else {
                voice.setWakeMode(false)
            }
        }
    }
    
    // MARK: - Navigation Bar
    private var navBar: some View {
        HStack(spacing: 16) {
            Button {
                withAnimation(OMAnimations.spring) {
                    showSidebar.toggle()
                }
            } label: {
                Image(systemName: "line.3.horizontal")
                    .font(.system(size: 22, weight: .semibold))
                    .foregroundStyle(.white)
                    .frame(width: 44, height: 44)
                    .glass(cornerRadius: 14)
                    .hoverGlow()
            }
            
            Spacer()
            
            VStack(spacing: 2) {
                Text(chatVM.currentTitle)
                    .font(OMFonts.title3)
                    .foregroundStyle(.white)
                
                // 唤醒词开关（设置页可关）→ 状态随开关变化
                let wakeEnabled = UserDefaults.standard.object(forKey: "wakeWordEnabled") as? Bool ?? true
                if wakeEnabled {
                    HStack(spacing: 4) {
                        Circle()
                            .fill(OMColors.success)
                            .frame(width: 6, height: 6)
                        Text("小麦小麦 待命")
                            .font(OMFonts.caption2)
                            .foregroundStyle(OMColors.success)
                    }
                }
            }
            
            Spacer()
            
            Button {
                chatVM.newSession()
            } label: {
                Image(systemName: "plus")
                    .font(.system(size: 20, weight: .semibold))
                    .foregroundStyle(.white)
                    .frame(width: 44, height: 44)
                    .glass(cornerRadius: 14)
                    .hoverGlow()
            }
        }
        .padding(.horizontal)
        .padding(.vertical, 8)
    }
    
    // MARK: - Message List
    private var messageList: some View {
        ScrollViewReader { scroll in
            ScrollView {
                LazyVStack(spacing: 16) {
                    if chatVM.messages.isEmpty {
                        welcomeView
                            .padding(.top, 40)
                    } else {
                        ForEach(chatVM.messages) { msg in
                            MessageBubbleNew(message: msg)
                                .id(msg.id)
                                .transition(.asymmetric(
                                    insertion: .scale(scale: 0.9).combined(with: .opacity),
                                    removal: .opacity
                                ))
                        }
                        
                        if chatVM.isSending {
                            TypingIndicatorNew()
                                .id("typing")
                        }
                    }
                }
                .padding()
                // 底部留白：内容不被输入栏/Home 指示条遮挡（iPhone 关键）
                .padding(.bottom, 90)
            }
            .onChange(of: chatVM.messages.count) { _, _ in
                scrollToBottom(scroll: scroll)
            }
            .onChange(of: chatVM.isSending) { _, sending in
                if sending {
                    withAnimation { scroll.scrollTo("typing", anchor: .bottom) }
                }
            }
        }
        .scrollDismissesKeyboard(.interactively)
    }
    
    private func scrollToBottom(scroll: ScrollViewProxy) {
        if let last = chatVM.messages.last {
            withAnimation(OMAnimations.smooth) {
                scroll.scrollTo(last.id, anchor: .bottom)
            }
        }
    }
    
    // MARK: - Welcome View
    private var welcomeView: some View {
        VStack(spacing: 28) {
            // Animated logo
            ZStack {
                // Outer glow rings
                ForEach(0..<3) { i in
                    Circle()
                        .stroke(OMColors.primaryGradient, lineWidth: 1)
                        .frame(width: 100 + CGFloat(i) * 30, height: 100 + CGFloat(i) * 30)
                        .opacity(0.3 - Double(i) * 0.1)
                        .scaleEffect(1 + Double(i) * 0.1)
                }
                
                // Main logo
                RoundedRectangle(cornerRadius: 28, style: .continuous)
                    .fill(OMColors.primaryGradient)
                    .frame(width: 90, height: 90)
                    .overlay(
                        Image(systemName: "sparkles")
                            .font(.system(size: 40))
                            .foregroundStyle(.white)
                    )
                    .shadow(color: Color(hex: "FF6B6B").opacity(0.4), radius: 30, x: 0, y: 10)
            }
            
            VStack(spacing: 8) {
                Text("OpenMemo")
                    .font(OMFonts.title)
                    .foregroundStyle(.white)
                
                Text("说一句话，AI 帮你安排一切")
                    .font(OMFonts.subheadline)
                    .foregroundStyle(.white.opacity(0.6))
            }
            
            // Capability pills
            FlowLayout(spacing: 8) {
                CapabilityPill(icon: "note.text", text: "记任务")
                CapabilityPill(icon: "clock.badge.checkmark", text: "智能提醒")
                CapabilityPill(icon: "airplane", text: "出行规划")
                CapabilityPill(icon: "newspaper", text: "实时资讯")
                CapabilityPill(icon: "bell.badge", text: "循环提醒")
            }
            .padding(.horizontal, 20)
            
            // Suggestion cards
            VStack(alignment: .leading, spacing: 12) {
                Text("试试这样说")
                    .font(OMFonts.caption)
                    .foregroundStyle(.white.opacity(0.5))
                    .padding(.leading, 4)
                
                ForEach(suggestions, id: \.self) { suggestion in
                    SuggestionCard(text: suggestion) {
                        chatVM.inputText = suggestion
                        chatVM.send()
                    }
                }
            }
            .padding(.horizontal, 20)
        }
    }
    
    // MARK: - Input Section
    private var inputSection: some View {
        VStack(spacing: 8) {
            // Voice status — in flow, only while actually recording → can never overlap the input
            if voice.isTranscribing {
                VoiceStatusBar(voice: voice)
                    .transition(.opacity.combined(with: .move(edge: .bottom)))
            }
            
            inputBar
        }
        .frame(maxWidth: .infinity)
        .background {
            // 同一块材质背景直接延伸进底部安全区（Home 条下无缝，无灰色残条）
            OMColors.surface
                .overlay(.ultraThinMaterial)
                .ignoresSafeArea(edges: .bottom)
        }
    }
    
    private var inputBar: some View {
        HStack(spacing: 10) {
            // Voice button
            VoiceButton(
                isRecording: voice.isTranscribing,
                isWakeMode: voice.isWakeArmed
            ) {
                Task { @MainActor in
                    Task { try? await OpenMemoAPI.shared.stopSpeak() }
                    if voice.isTranscribing {
                        voice.stop()
                        return
                    }
                    if !speechAuthGranted {
                        speechAuthGranted = await VoiceInputManager.requestAuthorization()
                    }
                    guard speechAuthGranted else { return }
                    voice.stop()
                    voice.startVoiceInput()
                }
            }
            
            // Text input
            ZStack(alignment: .leading) {
                if effectiveInputText.isEmpty {
                    Text("输入消息或说「小麦小麦」...")
                        .font(OMFonts.subheadline)
                        .foregroundStyle(.white.opacity(0.35))
                        .padding(.leading, 6)
                }
                
                MultilineTextField(
                    text: inputBinding,
                    onEnter: { chatVM.send() },
                    onCtrlEnter: { chatVM.inputText += "\n" }
                )
                .font(OMFonts.subheadline)
                .foregroundStyle(.white)
                .frame(height: 40)
            }
            .padding(.horizontal, 14)
            .glass(cornerRadius: 20)
            
            // Send button
            SendButton(isLoading: chatVM.isSending, isEnabled: !effectiveInputText.trimmingCharacters(in: .whitespaces).isEmpty) {
                chatVM.send()
            }
        }
        .padding(.horizontal)
        .padding(.vertical, 8)
    }
    
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
    
    private var effectiveInputText: String {
        voice.isTranscribing ? voice.liveText : chatVM.inputText
    }
}

// MARK: - Supporting Views

struct CapabilityPill: View {
    let icon: String
    let text: String
    
    var body: some View {
        HStack(spacing: 6) {
            Image(systemName: icon)
                .font(.caption)
            Text(text)
                .font(OMFonts.caption.weight(.medium))
        }
        .foregroundStyle(.white.opacity(0.8))
        .padding(.horizontal, 12)
        .padding(.vertical, 6)
        .background(Color.white.opacity(0.1))
        .clipShape(Capsule())
        .overlay(
            Capsule()
                .stroke(Color.white.opacity(0.15), lineWidth: 1)
        )
    }
}

struct SuggestionCard: View {
    let text: String
    let action: () -> Void
    
    var body: some View {
        Button(action: action) {
            HStack {
                Text(text)
                    .font(OMFonts.subheadline)
                    .foregroundStyle(.white)
                Spacer()
                Image(systemName: "arrow.up.right")
                    .font(.caption)
                    .foregroundStyle(.white.opacity(0.5))
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 14)
            .glass(cornerRadius: 16)
            .hoverGlow()
        }
        .buttonStyle(.plain)
        .pressEffect()
    }
}

struct VoiceButton: View {
    let isRecording: Bool
    let isWakeMode: Bool
    let action: () -> Void
    
    @State private var isPressed = false
    
    var body: some View {
        Button(action: action) {
            ZStack {
                // Glow effect when recording
                if isRecording {
                    Circle()
                        .fill(OMColors.error.opacity(0.3))
                        .frame(width: 42, height: 42)
                        .scaleEffect(1.4)
                        .animation(.easeInOut(duration: 1).repeatForever(autoreverses: true), value: isRecording)
                }
                
                Circle()
                    .fill(isRecording ? OMColors.error : OMColors.surfaceElevated)
                    .frame(width: 38, height: 38)
                    .overlay(
                        Circle()
                            .stroke(isRecording ? OMColors.error : Color.white.opacity(0.2), lineWidth: 1.5)
                    )
                
                Image(systemName: isRecording ? "mic.fill" : "mic")
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundStyle(isRecording ? .white : .white.opacity(0.8))
            }
            .scaleEffect(isPressed ? 0.9 : 1)
            .hoverGlow()
        }
        .buttonStyle(.plain)
        .simultaneousGesture(
            DragGesture(minimumDistance: 0)
                .onChanged { _ in isPressed = true }
                .onEnded { _ in isPressed = false }
        )
    }
}

struct SendButton: View {
    let isLoading: Bool
    let isEnabled: Bool
    let action: () -> Void
    
    var body: some View {
        Button(action: action) {
            ZStack {
                Circle()
                    .fill(isEnabled ? AnyShapeStyle(OMColors.primaryGradient) : AnyShapeStyle(Color.white.opacity(0.1)))
                    .frame(width: 38, height: 38)
                
                if isLoading {
                    ProgressView()
                        .scaleEffect(0.7)
                        .tint(.white)
                } else {
                    Image(systemName: "arrow.up")
                        .font(.system(size: 16, weight: .bold))
                        .foregroundStyle(.white)
                }
            }
            .hoverGlow()
        }
        .disabled(!isEnabled || isLoading)
        .buttonStyle(.plain)
    }
}

struct VoiceStatusBar: View {
    let voice: any STTProvider
    
    var body: some View {
        HStack(spacing: 10) {
            // Animated waveform
            HStack(spacing: 3) {
                ForEach(0..<5) { i in
                    RoundedRectangle(cornerRadius: 1.5)
                        .fill(voice.isTranscribing ? OMColors.error : OMColors.success)
                        .frame(width: 3, height: voice.isTranscribing ? 16 : 10)
                        .animation(.easeInOut(duration: 0.3).repeatForever(autoreverses: true).delay(Double(i) * 0.05), value: voice.isTranscribing)
                }
            }
            
            Text(voice.isTranscribing ? (voice.liveText.isEmpty ? "正在聆听..." : voice.liveText) : "等待「小麦小麦」...")
                .font(OMFonts.caption.weight(.medium))
                .foregroundStyle(.white)
                .lineLimit(1)
            
            Spacer()
            
            if voice.isTranscribing {
                Button("取消") { voice.stop() }
                    .font(OMFonts.caption.weight(.semibold))
                    .foregroundStyle(OMColors.error)
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 8)
        .frame(maxWidth: .infinity)
        .background(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .fill(OMColors.surfaceElevated)
                .overlay(
                    RoundedRectangle(cornerRadius: 16, style: .continuous)
                        .stroke(Color.white.opacity(0.12), lineWidth: 1)
                )
        )
        .padding(.horizontal, 12)
        .shadow(color: .black.opacity(0.4), radius: 12, x: 0, y: 6)
    }
}

// MARK: - Press Effect Modifier
struct PressEffect: ViewModifier {
    @State private var isPressed = false
    
    func body(content: Content) -> some View {
        content
            .scaleEffect(isPressed ? 0.97 : 1)
            .opacity(isPressed ? 0.8 : 1)
            .animation(.easeInOut(duration: 0.15), value: isPressed)
            .simultaneousGesture(
                DragGesture(minimumDistance: 0)
                    .onChanged { _ in isPressed = true }
                    .onEnded { _ in isPressed = false }
            )
    }
}

extension View {
    func pressEffect() -> some View {
        modifier(PressEffect())
    }
}

// MARK: - Flow Layout
struct FlowLayout: Layout {
    var spacing: CGFloat = 8
    
    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let result = FlowResult(in: proposal.width ?? 0, subviews: subviews, spacing: spacing)
        return result.size
    }
    
    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let result = FlowResult(in: bounds.width, subviews: subviews, spacing: spacing)
        for (index, subview) in subviews.enumerated() {
            subview.place(at: CGPoint(x: bounds.minX + result.positions[index].x, y: bounds.minY + result.positions[index].y), proposal: .unspecified)
        }
    }
    
    struct FlowResult {
        var size: CGSize = .zero
        var positions: [CGPoint] = []
        
        init(in maxWidth: CGFloat, subviews: Subviews, spacing: CGFloat) {
            var x: CGFloat = 0
            var y: CGFloat = 0
            var rowHeight: CGFloat = 0
            
            for subview in subviews {
                let size = subview.sizeThatFits(.unspecified)
                if x + size.width > maxWidth && x > 0 {
                    x = 0
                    y += rowHeight + spacing
                    rowHeight = 0
                }
                positions.append(CGPoint(x: x, y: y))
                rowHeight = max(rowHeight, size.height)
                x += size.width + spacing
            }
            
            self.size = CGSize(width: maxWidth, height: y + rowHeight)
        }
    }
}

#Preview {
    ChatViewNew()
        .environment(ChatViewModel())
        .preferredColorScheme(.dark)
}
