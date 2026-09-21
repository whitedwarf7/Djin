import SwiftUI

@main
struct DjinApp: App {
    @StateObject private var session = SessionStore()

    var body: some Scene {
        WindowGroup {
            RootView(session: session)
                .tint(DjinTheme.accent)
        }
    }
}
