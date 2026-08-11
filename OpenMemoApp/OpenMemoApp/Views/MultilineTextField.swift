import SwiftUI
import UIKit

/// 支持「回车=发送，Ctrl+回车=换行」的多行输入框。
/// SwiftUI 的 TextField(axis: .vertical) 会把 Return 吞掉（插入换行），
/// onSubmit / onKeyPress 都收不到——所以用 UITextView 的 keyCommands 可靠拦截。
/// 注意：placeholder 由外部 overlay 显示（绝不能写进 text，否则会被当消息发出去）。
struct MultilineTextField: UIViewRepresentable {
    @Binding var text: String
    var onEnter: () -> Void
    var onCtrlEnter: () -> Void

    func makeCoordinator() -> Coordinator {
        Coordinator(self)
    }

    func makeUIView(context: Context) -> KeyHandlingTextView {
        let tv = KeyHandlingTextView()
        tv.font = .preferredFont(forTextStyle: .body)
        tv.backgroundColor = .clear
        tv.isScrollEnabled = true
        tv.textContainerInset = UIEdgeInsets(top: 6, left: 0, bottom: 6, right: 0)
        tv.delegate = context.coordinator
        tv.returnKeyType = .send
        tv.onEnter = { onEnter() }
        tv.onCtrlEnter = { onCtrlEnter() }
        return tv
    }

    func updateUIView(_ uiView: KeyHandlingTextView, context: Context) {
        if uiView.text != text {
            uiView.text = text
        }
        uiView.onEnter = { onEnter() }
        uiView.onCtrlEnter = { onCtrlEnter() }
        // 空内容时隐藏光标，避免和 placeholder 重叠
        uiView.tintColor = text.isEmpty ? .clear : nil
    }

    class Coordinator: NSObject, UITextViewDelegate {
        var parent: MultilineTextField

        init(_ parent: MultilineTextField) {
            self.parent = parent
        }

        func textViewDidChange(_ textView: UITextView) {
            parent.text = textView.text ?? ""
        }
    }
}

/// 用 keyCommands 拦截硬件键盘回车：无修饰键=发送，Ctrl+回车=换行
final class KeyHandlingTextView: UITextView {
    var onEnter: (() -> Void)?
    var onCtrlEnter: (() -> Void)?

    override var keyCommands: [UIKeyCommand]? {
        [
            UIKeyCommand(input: "\r", modifierFlags: [], action: #selector(enterPressed)),
            UIKeyCommand(input: "\r", modifierFlags: .control, action: #selector(ctrlEnterPressed)),
        ]
    }

    @objc private func enterPressed() {
        onEnter?()
    }

    @objc private func ctrlEnterPressed() {
        onCtrlEnter?()
    }
}
