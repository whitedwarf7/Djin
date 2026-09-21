import Foundation
import Combine

@MainActor
final class SessionStore: ObservableObject {
    enum State: Equatable {
        case restoring
        case signedOut
        case signedIn(UserProfile)
    }

    @Published private(set) var state: State = .restoring
    @Published var serverAddress: String
    @Published private(set) var isWorking = false
    @Published var errorMessage: String?

    private static let tokenAccount = "djin-access-token"
    private static let serverAddressKey = "djin-server-address"
    private static let defaultServerAddress = "http://127.0.0.1:8765"

    private let keychain = KeychainStore()
    private let defaults: UserDefaults
    private var token: String?

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        serverAddress = defaults.string(forKey: Self.serverAddressKey)
            ?? Self.defaultServerAddress
    }

    var apiClient: APIClient? {
        guard let token,
              let baseURL = try? ServerAddress.normalize(serverAddress)
        else {
            return nil
        }
        return APIClient(baseURL: baseURL, token: token)
    }

    func restore() async {
        guard state == .restoring else {
            return
        }

        do {
            guard let storedToken = try keychain.read(account: Self.tokenAccount) else {
                state = .signedOut
                return
            }
            let baseURL = try ServerAddress.normalize(serverAddress)
            let user = try await APIClient(baseURL: baseURL, token: storedToken).currentUser()
            token = storedToken
            state = .signedIn(user)
        } catch APIError.unauthorized(_) {
            try? keychain.delete(account: Self.tokenAccount)
            token = nil
            state = .signedOut
            errorMessage = "Your saved session expired. Sign in again."
        } catch {
            state = .signedOut
            errorMessage = error.localizedDescription
        }
    }

    func signIn(username: String, password: String) async {
        let normalizedUsername = username.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !normalizedUsername.isEmpty, !password.isEmpty else {
            errorMessage = "Enter your username and password."
            return
        }

        isWorking = true
        errorMessage = nil
        defer { isWorking = false }

        do {
            let baseURL = try ServerAddress.normalize(serverAddress)
            let response = try await APIClient(baseURL: baseURL).login(
                username: normalizedUsername,
                password: password
            )
            try keychain.save(response.accessToken, account: Self.tokenAccount)
            defaults.set(baseURL.absoluteString, forKey: Self.serverAddressKey)
            serverAddress = baseURL.absoluteString
            token = response.accessToken
            state = .signedIn(response.user)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func signOut() async {
        let client = apiClient
        token = nil
        state = .signedOut
        errorMessage = nil
        try? keychain.delete(account: Self.tokenAccount)
        try? await client?.logout()
    }
}
