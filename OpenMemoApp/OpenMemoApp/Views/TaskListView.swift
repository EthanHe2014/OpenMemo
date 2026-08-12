import SwiftUI

struct TaskListView: View {
    @Environment(TaskListViewModel.self) private var taskVM
    @State private var showAddSheet = false
    @State private var filterStatus: String? = nil

    var filteredTasks: [OpenMemoTask] {
        if let status = filterStatus {
            return taskVM.tasks.filter { $0.status == status }
        }
        return taskVM.tasks
    }

    var body: some View {
        NavigationStack {
            Group {
                if taskVM.isLoading && taskVM.tasks.isEmpty {
                    ProgressView("加载中...")
                } else if let error = taskVM.errorMessage {
                    VStack(spacing: 16) {
                        Image(systemName: "wifi.slash")
                            .font(.system(size: 48))
                            .foregroundStyle(.secondary)
                        Text("连接失败")
                            .font(.headline)
                        Text(error)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .multilineTextAlignment(.center)
                        Button("重试") { Task { await taskVM.load() } }
                            .buttonStyle(.bordered)
                    }
                    .padding()
                } else if taskVM.tasks.isEmpty {
                    ContentUnavailableView(
                        "暂无任务",
                        systemImage: "checklist",
                        description: Text("创建一个新任务开始吧")
                    )
                } else {
                    List {
                        ForEach(filteredTasks) { task in
                            NavigationLink(destination: TaskDetailView(task: task)) {
                                TaskRowView(task: task)
                            }
                            .swipeActions(edge: .trailing, allowsFullSwipe: true) {
                                Button(role: .destructive) {
                                    Task { await taskVM.delete(task) }
                                } label: {
                                    Label("删除", systemImage: "trash")
                                }
                                Button {
                                    Task { await taskVM.toggleComplete(task) }
                                } label: {
                                    Label(task.isCompleted ? "重开" : "完成", systemImage: task.isCompleted ? "arrow.uturn.backward" : "checkmark")
                                }
                                .tint(task.isCompleted ? .orange : .green)
                            }
                        }
                    }
                    .refreshable {
                        await taskVM.load()
                    }
                }
            }
            .navigationTitle("OpenMemo")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    HStack(spacing: 4) {
                        Menu {
                            Button("全部") { filterStatus = nil }
                            Button("待办") { filterStatus = "pending" }
                            Button("已完成") { filterStatus = "completed" }
                            Button("已取消") { filterStatus = "cancelled" }
                        } label: {
                            Image(systemName: "line.3.horizontal.decrease.circle")
                        }
                        Button {
                            showAddSheet = true
                        } label: {
                            Image(systemName: "plus")
                        }
                    }
                }
            }
            .sheet(isPresented: $showAddSheet) {
                AddTaskView()
            }
        }
        .task {
            await taskVM.load()
        }
    }
}

struct TaskRowView: View {
    let task: OpenMemoTask

    var body: some View {
        HStack(spacing: 12) {
            // 优先级标记
            Circle()
                .fill(priorityColor)
                .frame(width: 10, height: 10)

            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    Text(task.content)
                        .strikethrough(task.isCompleted)
                        .foregroundStyle(task.isCompleted ? .secondary : (task.isExecuted ? .secondary : .primary))
                        .lineLimit(1)
                    if task.isExecuted {
                        Text("已执行")
                            .font(.caption2)
                            .padding(.horizontal, 6)
                            .padding(.vertical, 1)
                            .background(.green.opacity(0.15), in: Capsule())
                            .foregroundStyle(.green)
                    }
                    if task.isCompleted {
                        Text("已完成")
                            .font(.caption2)
                            .padding(.horizontal, 6)
                            .padding(.vertical, 1)
                            .background(.blue.opacity(0.15), in: Capsule())
                            .foregroundStyle(.blue)
                    }
                }
                if let time = task.triggerTime {
                    Label(time, systemImage: "clock")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                if let notes = task.notes, !notes.isEmpty {
                    Text(notes)
                        .font(.caption)
                        .foregroundStyle(.tertiary)
                        .lineLimit(1)
                }
            }
        }
        .opacity(task.isCancelled ? 0.5 : 1)
    }

    private var priorityColor: Color {
        switch task.priority {
        case "high": return .red
        case "medium": return .orange
        case "low": return .green
        default: return .gray
        }
    }
}