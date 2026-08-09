import SwiftUI

struct AddTaskView: View {
    @Environment(TaskListViewModel.self) private var taskVM
    @Environment(\.dismiss) private var dismiss

    @State private var content = ""
    @State private var triggerTime = ""
    @State private var priority = "medium"
    @State private var notes = ""
    @State private var hasTime = false
    @State private var isSaving = false
    @State private var showError = false
    @State private var errorText = ""

    var body: some View {
        NavigationStack {
            Form {
                Section("任务内容") {
                    TextField("要做什么？", text: $content, axis: .vertical)
                        .lineLimit(1...3)
                }

                Section("提醒时间") {
                    Toggle("设置提醒时间", isOn: $hasTime)
                    if hasTime {
                        TextField("如 2026-08-06 14:00", text: $triggerTime)
                            .keyboardType(.numbersAndPunctuation)
                    }
                }

                Section("优先级") {
                    Picker("优先级", selection: $priority) {
                        Text("高 🔴").tag("high")
                        Text("中").tag("medium")
                        Text("低 🟢").tag("low")
                    }
                    .pickerStyle(.segmented)
                }

                Section("备注（可选）") {
                    TextField("备注", text: $notes, axis: .vertical)
                        .lineLimit(1...3)
                }

                if showError {
                    Section {
                        Text(errorText)
                            .font(.caption)
                            .foregroundStyle(.red)
                    }
                }
            }
            .navigationTitle("添加任务")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("保存") {
                        guard !content.trimmingCharacters(in: .whitespaces).isEmpty else {
                            errorText = "任务内容不能为空"
                            showError = true
                            return
                        }
                        let trimmedTime = triggerTime.trimmingCharacters(in: .whitespaces)
                        isSaving = true
                        Task {
                            await taskVM.add(
                                content: content,
                                triggerTime: (hasTime && !trimmedTime.isEmpty) ? trimmedTime : nil,
                                priority: priority,
                                notes: notes.isEmpty ? nil : notes
                            )
                            await MainActor.run { isSaving = false; dismiss() }
                        }
                    }
                    .disabled(isSaving)
                }
            }
        }
    }
}