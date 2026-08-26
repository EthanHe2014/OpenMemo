import SwiftUI

struct MainContainerView: View {
    @State private var selectedTab: Tab = .chat
    
    enum Tab: String, CaseIterable {
        case chat = "对话"
        case tasks = "任务"
        case settings = "设置"
    }
    
    var body: some View {
        TabView(selection: $selectedTab) {
            ChatViewNew()
                .tag(Tab.chat)
            
            TaskListViewNew()
                .tag(Tab.tasks)
            
            SettingsViewNew()
                .tag(Tab.settings)
        }
        .tabViewStyle(.page(indexDisplayMode: .never))
        .ignoresSafeArea()
    }
}

#Preview {
    MainContainerView()
        .preferredColorScheme(.dark)
}
