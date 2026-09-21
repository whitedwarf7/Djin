import SwiftUI

struct RootView: View {
    @ObservedObject var session: SessionStore

    var body: some View {
        Group {
            switch session.state {
            case .restoring:
                LaunchView()
            case .signedOut:
                AuthView(session: session)
            case .signedIn(let user):
                signedInView(user: user)
            }
        }
        .task {
            await session.restore()
        }
    }

    @ViewBuilder
    private func signedInView(user: UserProfile) -> some View {
        if let client = session.apiClient {
            MainView(user: user, client: client) {
                Task { await session.signOut() }
            }
        } else {
            LaunchView()
                .task { await session.signOut() }
        }
    }
}

private struct LaunchView: View {
    var body: some View {
        VStack(spacing: 20) {
            Image("BrandMark")
                .resizable()
                .scaledToFit()
                .frame(width: 72, height: 72)
                .accessibilityHidden(true)
            ProgressView()
                .tint(DjinTheme.accent)
                .accessibilityLabel("Restoring session")
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(DjinTheme.background)
    }
}

#Preview {
    RootView(session: SessionStore())
}
