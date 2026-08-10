import SwiftUI
import UIKit

/// 支持「回车=发送，Ctrl+回车=换行」的多行输入框。
/// SwiftUI 的 TextField(axis: .vertical) 会把 Return 吞掉（插入换行），
/// onSubmit / onKeyPress 都收不到——所以用 UITextView 的 keyCommands 可靠拦截。
struct MultilineTextField: UIViewRepresentable {
    @Binding var text: String
    var placeholder: String = ""
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
        tv.textContainerInset = UIEdgeInsets(top: 8, left: 4, bottom: 8, right: 4)
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
        // placeholder 显示
        if text.isEmpty {
            uiView.text = placeholder
            uiView.textColor = .placeholderText
        } else if uiView.text == placeholder {
            uiView.text = ""
            uiView.textColor = .label
        }
    }

    class Coordinator: NSObject, UITextViewDelegate {
        var parent: MultilineTextField

        init(_ parent: MultilineTextField) {
            self.parent = parent
        }

        func textViewDidChange(_ textView: UITextView) {
            let t = textView.text ?? ""
            if t == parent.placeholder { return }
            parent.text = t
        }

        func textViewDidBeginEditing(_ textView: UITextView) {
            if textView.text == parent.placeholder {
                textView.text = ""
                textView.textColor = .label
            }
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
