import SwiftUI

struct AuthView: View {
    private enum Field: Hashable {
        case server
        case username
        case password
    }

    @ObservedObject var session: SessionStore

    @State private var username = ""
    @State private var password = ""
    @State private var showsPassword = false
    @State private var allowsInsecureHTTP = false
    @FocusState private var focusedField: Field?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                brand
                form
            }
            .frame(maxWidth: 520)
            .padding(.horizontal, 24)
            .padding(.vertical, 40)
            .frame(maxWidth: .infinity)
        }
        .scrollDismissesKeyboard(.interactively)
        .background(DjinTheme.background.ignoresSafeArea())
        .foregroundStyle(DjinTheme.primaryText)
    }

    private var brand: some View {
        VStack(alignment: .leading, spacing: 16) {
            Image("BrandMark")
                .resizable()
                .scaledToFit()
                .frame(width: 64, height: 64)
                .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: 6) {
                Text("Djin")
                    .font(.largeTitle.bold())
                Text("Sign in to your personal assistant")
                    .font(.title3)
                    .foregroundStyle(DjinTheme.secondaryText)
            }
        }
    }

    private var form: some View {
        VStack(alignment: .leading, spacing: 18) {
            fieldLabel("Server address")
            TextField("http://127.0.0.1:8765", text: $session.serverAddress)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .keyboardType(.URL)
                .textContentType(.URL)
                .focused($focusedField, equals: .server)
                .submitLabel(.next)
                .onSubmit { focusedField = .username }
                .djinField(focused: focusedField == .server)

            if ServerAddress.usesDevelopmentHTTP(session.serverAddress) {
                connectionNotice(
                    "HTTP is for development on a trusted local network only.",
                    systemImage: "exclamationmark.shield.fill"
                )
            }

#if !targetEnvironment(simulator)
            if ServerAddress.usesLoopback(session.serverAddress) {
                connectionNotice(
                    "This points to the iPhone. Start Djin on the Mac with DJIN_HOST=0.0.0.0 and enter its .local address.",
                    systemImage: "network.slash"
                )
            }

            if ServerAddress.usesDevelopmentHTTP(session.serverAddress) {
                Toggle("Allow insecure development HTTP", isOn: $allowsInsecureHTTP)
                    .font(.callout.weight(.semibold))
                    .tint(DjinTheme.accent)
            }
#endif

            fieldLabel("Username")
            TextField("Owner username", text: $username)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .textContentType(.username)
                .focused($focusedField, equals: .username)
                .submitLabel(.next)
                .onSubmit { focusedField = .password }
                .djinField(focused: focusedField == .username)

            fieldLabel("Password")
            passwordField

            if let errorMessage = session.errorMessage {
                Label(errorMessage, systemImage: "exclamationmark.circle.fill")
                    .font(.callout)
                    .foregroundStyle(DjinTheme.danger)
                    .accessibilityLabel("Sign-in error: \(errorMessage)")
            }

            Button {
                focusedField = nil
                Task {
                    await session.signIn(username: username, password: password)
                }
            } label: {
                if session.isWorking {
                    ProgressView()
                        .tint(DjinTheme.accentInk)
                        .accessibilityLabel("Signing in")
                } else {
                    Text("Sign in")
                }
            }
            .buttonStyle(PrimaryButtonStyle())
            .disabled(session.isWorking || !canAttemptSignIn)
            .opacity(session.isWorking || !canAttemptSignIn ? 0.55 : 1)
        }
    }

    private var passwordField: some View {
        HStack(spacing: 8) {
            Group {
                if showsPassword {
                    TextField("Password", text: $password)
                } else {
                    SecureField("Password", text: $password)
                }
            }
            .textContentType(.password)
            .focused($focusedField, equals: .password)
            .submitLabel(.go)
            .onSubmit { submit() }

            Button {
                showsPassword.toggle()
            } label: {
                Image(systemName: showsPassword ? "eye.slash" : "eye")
                    .frame(width: 44, height: 44)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .foregroundStyle(DjinTheme.secondaryText)
            .accessibilityLabel(showsPassword ? "Hide password" : "Show password")
        }
        .djinField(focused: focusedField == .password)
    }

    private func fieldLabel(_ value: String) -> some View {
        Text(value)
            .font(.subheadline.weight(.semibold))
            .padding(.bottom, -10)
    }

    private func connectionNotice(_ value: String, systemImage: String) -> some View {
        Label(value, systemImage: systemImage)
            .font(.footnote)
            .foregroundStyle(DjinTheme.secondaryText)
            .accessibilityElement(children: .combine)
    }

    private func submit() {
        guard !session.isWorking, canAttemptSignIn else {
            return
        }
        focusedField = nil
        Task {
            await session.signIn(username: username, password: password)
        }
    }

    private var canAttemptSignIn: Bool {
#if targetEnvironment(simulator)
        true
#else
        !ServerAddress.usesDevelopmentHTTP(session.serverAddress) || allowsInsecureHTTP
#endif
    }
}

#Preview {
    AuthView(session: SessionStore())
}
