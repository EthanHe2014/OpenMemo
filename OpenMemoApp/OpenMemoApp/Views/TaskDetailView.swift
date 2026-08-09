import SwiftUI

struct TaskDetailView: View {
    @Environment(TaskListViewModel.self) private var taskVM
    let task: OpenMemoTask

    @State private var content: String
    @State private var priority: String
    @State private var notes: String
    @State private var triggerTime: String
    @State private var isEditing = false
    @State private var saved = false

    init(task: OpenMemoTask) {
        self.task = task
        _content = State(initialValue: task.content)
        _priority = State(initialValue: task.priority)
        _notes = State(initialValue: task.notes ?? "")
        _triggerTime = State(initialValue: task.triggerTime ?? "")
    }

    var body: some View {
        Form {
            Section("任务内容") {
                if isEditing {
                    TextField("内容", text: $content)
                } else {
                    Text(task.content)
                }
            }

            Section("状态") {
                HStack {
                    Text("状态")
                    Spacer()
                    Text(task.isCompleted ? "✅ 已完成" : task.isCancelled ? "❌ 已取消" : "⏳ 待办")
                        .foregroundStyle(.secondary)
                }
            }

            Section("时间") {
                if isEditing {
                    TextField("时间 (YYYY-MM-DD HH:MM)", text: $triggerTime)
                        .keyboardType(.numbersAndPunctuation)
                } else if let t = task.triggerTime {
                    Text(t)
                } else {
                    Text("未设置时间")
                        .foregroundStyle(.secondary)
                }
            }

            Section("优先级") {
                if isEditing {
                    Picker("优先级", selection: $priority) {
                        Text("高 🔴").tag("high")
                        Text("中").tag("medium")
                        Text("低").tag("low")
                    }
                    .pickerStyle(.segmented)
                } else {
                    HStack {
                        Text(task.priority)
                        Spacer()
                        switch task.priority {
                        case "high": Text("高 🔴")
                        case "medium": Text("中")
                        case "low": Text("低 🟢")
                        default: EmptyView()
                        }
                    }
                }
            }

            Section("备注") {
                if isEditing {
                    TextEditor(text: $notes)
                        .frame(minHeight: 80)
                } else if let n = task.notes, !n.isEmpty {
                    Text(n)
                } else {
                    Text("无备注")
                        .foregroundStyle(.secondary)
                }
            }

            if !isEditing {
                Section {
                    Button(task.isCompleted ? "重新打开" : "标记完成") {
                        Task { await taskVM.toggleComplete(task) }
                    }
                    .foregroundStyle(task.isCompleted ? .orange : .green)

                    Button("删除任务", role: .destructive) {
                        Task { await taskVM.delete(task) }
                    }
                }
            }
        }
        .navigationTitle("任务详情")
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                if isEditing {
                    Button("保存") {
                        Task {
                            _ = try? await OpenMemoAPI.shared.updateTask(
                                task.taskId, content: content,
                                triggerTime: triggerTime.isEmpty ? nil : triggerTime,
                                priority: priority,
                                notes: notes.isEmpty ? nil : notes
                            )
                            saved = true
                            isEditing = false
                            await taskVM.load()
                        }
                    }
                } else {
                    Button("编辑") { isEditing = true }
                }
            }
        }
        .onDisappear {
            if saved {
                Task { await taskVM.load() }
            }
        }
    }
}