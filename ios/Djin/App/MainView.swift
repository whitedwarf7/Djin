import SwiftUI

struct MainView: View {
    private enum Tab: Hashable {
        case chat
        case sessions
    }

    let user: UserProfile
    let onSignOut: () -> Void

    @StateObject private var model: ChatViewModel
    @State private var selectedTab: Tab = .chat

    init(user: UserProfile, client: APIClient, onSignOut: @escaping () -> Void) {
        self.user = user
        self.onSignOut = onSignOut
        _model = StateObject(wrappedValue: ChatViewModel(client: client))
    }

    var body: some View {
        TabView(selection: $selectedTab) {
            ChatView(model: model, user: user, onSignOut: onSignOut)
                .tabItem {
                    Label("Chat", systemImage: "message")
                }
                .tag(Tab.chat)

            SessionsView(
                model: model,
                onOpenChat: { selectedTab = .chat },
                onNewChat: {
                    model.startNewConversation()
                    selectedTab = .chat
                }
            )
            .tabItem {
                Label("Sessions", systemImage: "clock")
            }
            .tag(Tab.sessions)
        }
        .task {
            await model.loadInitialData()
        }
        .onChange(of: model.sessionExpired) { _, expired in
            if expired {
                onSignOut()
            }
        }
    }
}
