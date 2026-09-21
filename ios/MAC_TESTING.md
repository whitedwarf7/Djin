# Testing Djin for iPhone on a Mac

The Python Djin service remains the backend and must be running while the native SwiftUI app is used.

## One-time setup

1. Install Xcode from the Mac App Store and open it once to finish installing components.
2. Install Homebrew from <https://brew.sh> if it is not already installed.
3. Install XcodeGen:

   ```bash
   brew install xcodegen
   ```

4. Clone this repository, then prepare the Python service from the repository root:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   cp .env.example .env
   ```

5. Add the required Djin settings to `.env`. Never commit that file.
6. Start Djin and open <http://127.0.0.1:8765> in Safari to create the owner account if this is a new database:

   ```bash
   source .venv/bin/activate
   python -m djin.cli serve
   ```

## Test after every iOS change

1. Pull the latest commit on the Mac:

   ```bash
   git pull
   ```

2. In Terminal 1, start the backend from the repository root:

   ```bash
   source .venv/bin/activate
   python -m djin.cli serve
   ```

3. In Terminal 2, regenerate and open the Xcode project:

   ```bash
   cd ios
   xcodegen generate
   open Djin.xcodeproj
   ```

4. In Xcode, select the `Djin` project, then the `Djin` target. Under **Signing & Capabilities**, select your Apple development team. If Xcode reports that the bundle identifier is unavailable, change it to a unique value such as `com.yourname.djin`.
5. Choose an iPhone simulator in the top toolbar and press **Run** (the triangle button).
6. On the sign-in screen, keep the server address as `http://127.0.0.1:8765`, then use the owner username and password created in Safari.
7. Run unit tests with **Product > Test**.

Regenerate with `xcodegen generate` after every pull. Do not manually edit `Djin.xcodeproj`; it is generated from `project.yml`.

## Test on a physical iPhone

1. Put the Mac and iPhone on the same private Wi-Fi network.
2. Stop the backend if it is running, then expose it to the local network:

   ```bash
   source .venv/bin/activate
   DJIN_HOST=0.0.0.0 python -m djin.cli serve
   ```

3. In **System Settings > General > Sharing**, note the Mac local hostname. It usually looks like `your-mac.local`.
4. Connect the iPhone to the Mac, trust the computer, select the iPhone in Xcode, and press **Run**.
5. Accept the local-network prompt in the app.
6. Enter `http://your-mac.local:8765` as the server address, enable **Allow insecure development HTTP**, and sign in. The owner account must already have been created from Safari on the Mac.
7. If connection fails, allow incoming Python connections in the macOS firewall and verify the address from iPhone Safari first.

Do not expose this development HTTP server to the public internet. Use trusted HTTPS before using Djin across an untrusted network.

## What to test

- Sign in and sign out.
- Send one message and confirm the reply streams rather than appearing all at once.
- Trigger an external action, then test both **Reject** and **Approve**.
- Open the session from the Sessions tab and confirm tool status is preserved.
- Delete a session and confirm the confirmation dialog appears first.
- Repeat in light mode, dark mode, landscape, and a larger Dynamic Type size.

## What to report

- macOS, Xcode, simulator/device, and iOS versions
- whether `xcodegen generate`, Build, and Product > Test passed
- the exact first error from Xcode if one failed
- whether sign-in, one streamed reply, one approval, session reopen, and session delete worked
- screenshots of any layout issue in portrait, landscape, light mode, or dark mode