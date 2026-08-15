import SwiftUI

struct TaskListViewNew: View {
    @Environment(TaskListViewModel.self) private var taskVM
    @State private var selectedFilter: TaskFilter = .all
    @State private var showingAddTask = false
    
    enum TaskFilter: String, CaseIterable {
        case all = "全部"
        case pending = "待办"
        case today = "今日"
        case completed = "已完成"
    }
    
    var body: some View {
        ZStack {
            // Background — tasks wallpaper (indigo/blue aurora)
            OMBackground(.tasks)
            
            VStack(spacing: 0) {
                // Header
                header
                
                // Stats cards
                statsSection
                    .padding(.horizontal)
                    .padding(.top, 8)
                
                // Filter pills
                filterSection
                    .padding(.horizontal)
                    .padding(.vertical, 12)
                
                // Task list
                taskList
            }
        }
        .sheet(isPresented: $showingAddTask) {
            AddTaskView()
        }
        .task {
            await taskVM.load()
        }
    }
    
    // MARK: - Header
    private var header: some View {
        HStack {
            Text("任务")
                .font(OMFonts.largeTitle)
                .foregroundStyle(.white)
            
            Spacer()
            
            Button {
                showingAddTask = true
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
        .padding(.top, 8)
    }
    
    // MARK: - Stats Section
    private var statsSection: some View {
        let stats = calculateStats()
        
        return ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 12) {
                StatCard(
                    value: stats.pending,
                    label: "待办",
                    icon: "clock",
                    color: OMColors.warning,
                    gradient: [Color(hex: "F59E0B"), Color(hex: "D97706")]
                )
                
                StatCard(
                    value: stats.today,
                    label: "今日",
                    icon: "calendar.badge.clock",
                    color: OMColors.error,
                    gradient: [Color(hex: "EF4444"), Color(hex: "DC2626")]
                )
                
                StatCard(
                    value: stats.completed,
                    label: "已完成",
                    icon: "checkmark.circle.fill",
                    color: OMColors.success,
                    gradient: [Color(hex: "10B981"), Color(hex: "059669")]
                )
                
                StatCard(
                    value: stats.total,
                    label: "总计",
                    icon: "list.bullet.rectangle.fill",
                    color: .white,
                    gradient: [Color(hex: "6366F1"), Color(hex: "4F46E5")]
                )
            }
            .padding(.horizontal, 4)
        }
    }
    
    // MARK: - Filter Section
    private var filterSection: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(TaskFilter.allCases, id: \.self) { filter in
                    FilterPill(
                        title: filter.rawValue,
                        isSelected: selectedFilter == filter,
                        count: countForFilter(filter)
                    ) {
                        withAnimation(OMAnimations.smooth) {
                            selectedFilter = filter
                        }
                    }
                }
            }
            .padding(.vertical, 6)   // room for the glow to breathe inside the scroll view
        }
        .scrollClipDisabled(true)   // don't clip the hover glow at the top
    }
    
    // MARK: - Task List
    private var taskList: some View {
        Group {
            if taskVM.isLoading && taskVM.tasks.isEmpty {
                loadingState
            } else if let error = taskVM.errorMessage {
                errorState(error)
            } else if filteredTasks.isEmpty {
                emptyState
            } else {
                taskScrollView
            }
        }
    }
    
    private var loadingState: some View {
        VStack(spacing: 20) {
            Spacer()
            ProgressView()
                .scaleEffect(1.5)
                .tint(.white)
            Text("加载中...")
                .font(OMFonts.subheadline)
                .foregroundStyle(.white.opacity(0.6))
            Spacer()
        }
    }
    
    private func errorState(_ error: String) -> some View {
        VStack(spacing: 16) {
            Spacer()
            
            ZStack {
                Circle()
                    .fill(OMColors.error.opacity(0.2))
                    .frame(width: 80, height: 80)
                
                Image(systemName: "wifi.slash")
                    .font(.system(size: 32))
                    .foregroundStyle(OMColors.error)
            }
            
            Text("连接失败")
                .font(OMFonts.title2)
                .foregroundStyle(.white)
            
            Text(error)
                .font(OMFonts.subheadline)
                .foregroundStyle(.white.opacity(0.6))
                .multilineTextAlignment(.center)
                .padding(.horizontal, 40)
            
            Button {
                Task { await taskVM.load() }
            } label: {
                Text("重试")
                    .font(OMFonts.subheadline.weight(.semibold))
                    .foregroundStyle(.white)
                    .padding(.horizontal, 24)
                    .padding(.vertical, 12)
                    .glass(cornerRadius: 12)
            }
            
            Spacer()
        }
    }
    
    private var emptyState: some View {
        VStack(spacing: 20) {
            Spacer()
            
            ZStack {
                Circle()
                    .fill(Color.white.opacity(0.05))
                    .frame(width: 100, height: 100)
                
                Image(systemName: "checkmark.circle")
                    .font(.system(size: 44))
                    .foregroundStyle(.white.opacity(0.3))
            }
            
            Text(selectedFilter == .all ? "暂无任务" : "没有符合条件的任务")
                .font(OMFonts.title3)
                .foregroundStyle(.white)
            
            Text("直接跟 OpenMemo 说，它就会帮你记下来")
                .font(OMFonts.subheadline)
                .foregroundStyle(.white.opacity(0.5))
            
            Spacer()
        }
    }
    
    private var taskScrollView: some View {
        ScrollView {
            LazyVStack(spacing: 12) {
                ForEach(groupedTasks.keys.sorted(), id: \.self) { section in
                    if let tasks = groupedTasks[section], !tasks.isEmpty {
                        TaskSection(
                            title: section,
                            tasks: tasks,
                            onToggle: { task in
                                Task { await taskVM.toggleComplete(task) }
                            },
                            onDelete: { task in
                                Task { await taskVM.delete(task) }
                            }
                        )
                    }
                }
            }
            .padding()
        }
        .refreshable {
            await taskVM.load()
        }
    }
    
    // MARK: - Helpers
    private var filteredTasks: [OpenMemoTask] {
        switch selectedFilter {
        case .all:
            return taskVM.tasks
        case .pending:
            return taskVM.tasks.filter { $0.isPending }
        case .today:
            return taskVM.tasks.filter { task in
                guard let t = task.triggerTime,
                      let d = TaskListHelpers.parseTime(t) else { return false }
                return Calendar.current.isDateInToday(d) && task.isPending
            }
        case .completed:
            return taskVM.tasks.filter { $0.isCompleted }
        }
    }
    
    private var groupedTasks: [String: [OpenMemoTask]] {
        Dictionary(grouping: filteredTasks) { task in
            if task.isCompleted { return "已完成" }
            if task.isCancelled { return "已取消" }
            if let time = task.triggerTime,
               let date = TaskListHelpers.parseTime(time) {
                if Calendar.current.isDateInToday(date) { return "今天" }
                if Calendar.current.isDateInTomorrow(date) { return "明天" }
                return "未来"
            }
            return "待安排"
        }
    }
    
    private func countForFilter(_ filter: TaskFilter) -> Int {
        switch filter {
        case .all: return taskVM.tasks.count
        case .pending: return taskVM.tasks.filter { $0.isPending }.count
        case .today:
            return taskVM.tasks.filter { task in
                guard let t = task.triggerTime,
                      let d = TaskListHelpers.parseTime(t) else { return false }
                return Calendar.current.isDateInToday(d) && task.isPending
            }.count
        case .completed: return taskVM.tasks.filter { $0.isCompleted }.count
        }
    }
    
    private func calculateStats() -> (pending: Int, today: Int, completed: Int, total: Int) {
        let pending = taskVM.tasks.filter { $0.isPending }.count
        let today = taskVM.tasks.filter { task in
            guard let t = task.triggerTime,
                  let d = TaskListHelpers.parseTime(t) else { return false }
            return Calendar.current.isDateInToday(d) && task.isPending
        }.count
        let completed = taskVM.tasks.filter { $0.isCompleted }.count
        return (pending, today, completed, taskVM.tasks.count)
    }
}

// MARK: - Stat Card
struct StatCard: View {
    let value: Int
    let label: String
    let icon: String
    let color: Color
    let gradient: [Color]
    
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Spacer()
                ZStack {
                    Circle()
                        .fill(LinearGradient(colors: gradient, startPoint: .topLeading, endPoint: .bottomTrailing))
                        .frame(width: 36, height: 36)
                        .opacity(0.3)
                    
                    Image(systemName: icon)
                        .font(.system(size: 16, weight: .semibold))
                        .foregroundStyle(color)
                }
            }
            
            VStack(alignment: .leading, spacing: 4) {
                Text("\(value)")
                    .font(.system(size: 28, weight: .bold, design: .rounded))
                    .foregroundStyle(.white)
                
                Text(label)
                    .font(OMFonts.caption.weight(.medium))
                    .foregroundStyle(.white.opacity(0.6))
            }
        }
        .padding()
        .frame(width: 110, height: 120)
        .glass(cornerRadius: 20)
    }
}

// MARK: - Filter Pill
struct FilterPill: View {
    let title: String
    let isSelected: Bool
    let count: Int
    let action: () -> Void
    
    var body: some View {
        Button(action: action) {
            HStack(spacing: 6) {
                Text(title)
                    .font(OMFonts.subheadline.weight(isSelected ? .semibold : .medium))
                
                if count > 0 {
                    Text("\(count)")
                        .font(OMFonts.caption2.weight(.bold))
                        .padding(.horizontal, 6)
                        .padding(.vertical, 2)
                        .background(isSelected ? Color.white : Color.white.opacity(0.2))
                        .foregroundStyle(isSelected ? OMColors.background : .white)
                        .clipShape(Capsule())
                }
            }
            .foregroundStyle(isSelected ? OMColors.background : .white)
            .padding(.horizontal, 16)
            .padding(.vertical, 10)
            .background(
                isSelected ? AnyShapeStyle(OMColors.primaryGradient) : AnyShapeStyle(Color.white.opacity(0.08))
            )
            .clipShape(Capsule())
            .overlay(
                Capsule()
                    .stroke(isSelected ? Color.clear : Color.white.opacity(0.15), lineWidth: 1)
            )
            .hoverGlow(cornerRadius: 24)
        }
        .buttonStyle(.plain)
    }
}

// MARK: - Task Section
struct TaskSection: View {
    let title: String
    let tasks: [OpenMemoTask]
    let onToggle: (OpenMemoTask) -> Void
    let onDelete: (OpenMemoTask) -> Void
    
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text(title)
                    .font(OMFonts.subheadline.weight(.semibold))
                    .foregroundStyle(.white.opacity(0.7))
                
                Text("\(tasks.count)")
                    .font(OMFonts.caption.weight(.medium))
                    .foregroundStyle(.white.opacity(0.5))
                    .padding(.horizontal, 8)
                    .padding(.vertical, 2)
                    .background(Color.white.opacity(0.1))
                    .clipShape(Capsule())
                
                Spacer()
            }
            .padding(.horizontal, 4)
            
            ForEach(tasks) { task in
                TaskCard(task: task, onToggle: { onToggle(task) }, onDelete: { onDelete(task) })
                    .contextMenu {
                        Button(role: .destructive) {
                            onDelete(task)
                        } label: {
                            Label("删除", systemImage: "trash")
                        }
                    }
                    .swipeActions(edge: .trailing) {
                        Button(role: .destructive) {
                            onDelete(task)
                        } label: {
                            Image(systemName: "trash")
                        }
                    }
            }
        }
    }
}

// MARK: - Task Card
struct TaskCard: View {
    let task: OpenMemoTask
    let onToggle: () -> Void
    let onDelete: () -> Void
    
    var body: some View {
        HStack(spacing: 14) {
            // ── 可点击切换区：状态 + 内容 + 勾选（点这里 = 完成/未完成）──
            HStack(spacing: 14) {
                // Status indicator
                statusIndicator
                
                // Content
                VStack(alignment: .leading, spacing: 6) {
                    Text(task.content)
                        .font(OMFonts.body.weight(task.isPending ? .medium : .regular))
                        .foregroundStyle(task.isCompleted ? .white.opacity(0.5) : .white)
                        .strikethrough(task.isCompleted)
                        .lineLimit(2)
                    
                    HStack(spacing: 10) {
                        if let time = task.triggerTime {
                            timeLabel(time)
                        }
                        
                        if let rec = task.isRecurring, !rec.isEmpty {
                            recurringLabel(rec)
                        }
                    }
                }
                
                Spacer(minLength: 8)
                
                // Check button
                checkButton
            }
            .contentShape(Rectangle())
            .onTapGesture { toggleOnce() }
            
            // ── 独立删除按钮：点击只删除，绝不触发切换 ──
            deleteButton
        }
        .padding()
        .glass(cornerRadius: 18)
        .overlay(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .stroke(borderColor, lineWidth: 1)
        )
        .hoverGlow()
    }
    
    /// Catalyst 上 .onTapGesture 在含 Button 的层级里会偶发双触发，
    /// 导致任务“完成→飞到底部→又切回来”。用时间窗口去抖，只认第一次。
    @State private var lastToggleAt = Date.distantPast
    
    private func toggleOnce() {
        let now = Date()
        guard now.timeIntervalSince(lastToggleAt) > 0.35 else { return }
        lastToggleAt = now
        onToggle()
    }
    
    private var statusIndicator: some View {
        ZStack {
            if task.isCompleted {
                Circle()
                    .fill(OMColors.success.opacity(0.2))
                    .frame(width: 36, height: 36)
                
                Image(systemName: "checkmark")
                    .font(.system(size: 14, weight: .bold))
                    .foregroundStyle(OMColors.success)
            } else if task.isCancelled {
                Circle()
                    .fill(Color.white.opacity(0.1))
                    .frame(width: 36, height: 36)
                
                Image(systemName: "slash")
                    .font(.system(size: 14))
                    .foregroundStyle(.white.opacity(0.4))
            } else {
                Circle()
                    .stroke(OMColors.priority(task.priority).opacity(0.5), lineWidth: 2)
                    .frame(width: 36, height: 36)
                
                Circle()
                    .fill(OMColors.priority(task.priority))
                    .frame(width: 10, height: 10)
                    .glow(color: OMColors.priority(task.priority), isActive: isUrgent)
            }
        }
    }
    
    private func timeLabel(_ time: String) -> some View {
        let relative = TaskListHelpers.relativeTime(time)
        let color = timeColor(time)
        
        return Label(relative, systemImage: "clock")
            .font(OMFonts.caption.weight(.medium))
            .foregroundStyle(color)
    }
    
    private func recurringLabel(_ rec: String) -> some View {
        Label(recurringText(rec), systemImage: "repeat")
            .font(OMFonts.caption.weight(.medium))
            .foregroundStyle(OMColors.warning)
    }
    
    private var checkButton: some View {
        ZStack {
            Circle()
                .fill(task.isCompleted ? OMColors.success : Color.white.opacity(0.1))
                .frame(width: 32, height: 32)
            
            Image(systemName: task.isCompleted ? "checkmark" : "circle")
                .font(.system(size: 14, weight: .semibold))
                .foregroundStyle(task.isCompleted ? .white : .white.opacity(0.5))
        }
    }
    
    private var deleteButton: some View {
        HoverableDeleteButton(onDelete: onDelete)
    }
    
    private var borderColor: Color {
        if task.isCompleted { return Color.white.opacity(0.05) }
        if isUrgent { return OMColors.error.opacity(0.3) }
        return Color.white.opacity(0.1)
    }
    
    private var isUrgent: Bool {
        guard task.isPending, let time = task.triggerTime,
              let date = TaskListHelpers.parseTime(time) else { return false }
        return date < Date() || Calendar.current.isDateInToday(date)
    }
    
    private func timeColor(_ time: String) -> Color {
        guard task.isPending, let d = TaskListHelpers.parseTime(time) else {
            return .white.opacity(0.4)
        }
        if d < Date() { return OMColors.error }
        if Calendar.current.isDateInToday(d) { return OMColors.warning }
        return .white.opacity(0.6)
    }
    
    private func recurringText(_ rec: String) -> String {
        switch rec.lowercased() {
        case "每天", "daily": return "每天"
        case "工作日", "weekday": return "工作日"
        default: return rec
        }
    }
}

#Preview {
    TaskListViewNew()
        .environment(TaskListViewModel())
        .preferredColorScheme(.dark)
}

/// 垃圾桶按钮：悬停时图标变红 + 红色辉光 + 微放大
struct HoverableDeleteButton: View {
    let onDelete: () -> Void
    var help: String = "删除任务"
    @State private var isHovered = false
    
    var body: some View {
        Button(action: onDelete) {
            ZStack {
                Circle()
                    .fill(isHovered ? OMColors.error.opacity(0.22) : Color.white.opacity(0.08))
                    .frame(width: 30, height: 30)
                
                Image(systemName: "trash")
                    .font(.system(size: 13, weight: .medium))
                    .foregroundStyle(isHovered ? OMColors.error : .white.opacity(0.55))
            }
            .scaleEffect(isHovered ? 1.1 : 1)
            .shadow(color: isHovered ? OMColors.error.opacity(0.6) : .clear, radius: isHovered ? 10 : 0)
            .animation(.easeInOut(duration: 0.15), value: isHovered)
        }
        .buttonStyle(.plain)
        .onHover { hovering in
            isHovered = hovering
        }
        .help(help)
    }
}
