import SwiftUI
import UIKit

enum DjinTheme {
    static let background = adaptive(light: 0xF5F7F9, dark: 0x0D0F13)
    static let surface = adaptive(light: 0xFFFFFF, dark: 0x171A20)
    static let raisedSurface = adaptive(light: 0xE9EDF2, dark: 0x20242C)
    static let primaryText = adaptive(light: 0x17191E, dark: 0xF5F2EA)
    static let secondaryText = adaptive(light: 0x545B66, dark: 0xB8BAC1)
    static let divider = adaptive(light: 0xD3D8DE, dark: 0x323741)
    static let accent = Color(red: 224 / 255, green: 169 / 255, blue: 63 / 255)
    static let accentInk = Color(red: 20 / 255, green: 16 / 255, blue: 23 / 255)
    static let danger = adaptive(light: 0xB42335, dark: 0xFF7B88)
    static let success = adaptive(light: 0x1E7440, dark: 0x70D190)

    static func risk(_ value: String) -> Color {
        switch value {
        case "external", "destructive":
            return danger
        case "write":
            return accent
        default:
            return secondaryText
        }
    }

    private static func adaptive(light: UInt32, dark: UInt32) -> Color {
        Color(uiColor: UIColor { traits in
            UIColor(rgb: traits.userInterfaceStyle == .dark ? dark : light)
        })
    }
}

private extension UIColor {
    convenience init(rgb: UInt32) {
        self.init(
            red: CGFloat((rgb >> 16) & 0xFF) / 255,
            green: CGFloat((rgb >> 8) & 0xFF) / 255,
            blue: CGFloat(rgb & 0xFF) / 255,
            alpha: 1
        )
    }
}

struct PrimaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.headline)
            .foregroundStyle(DjinTheme.accentInk)
            .frame(maxWidth: .infinity, minHeight: 50)
            .padding(.horizontal, 16)
            .background(DjinTheme.accent, in: RoundedRectangle(cornerRadius: 8))
            .opacity(configuration.isPressed ? 0.72 : 1)
    }
}

struct DjinFieldModifier: ViewModifier {
    let isFocused: Bool

    func body(content: Content) -> some View {
        content
            .padding(.horizontal, 14)
            .frame(minHeight: 52)
            .background(DjinTheme.surface, in: RoundedRectangle(cornerRadius: 8))
            .overlay {
                RoundedRectangle(cornerRadius: 8)
                    .stroke(isFocused ? DjinTheme.accent : DjinTheme.divider, lineWidth: 1)
            }
    }
}

extension View {
    func djinField(focused: Bool) -> some View {
        modifier(DjinFieldModifier(isFocused: focused))
    }
}
