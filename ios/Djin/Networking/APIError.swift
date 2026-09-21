import Foundation

enum APIError: LocalizedError, Equatable {
    case invalidServerAddress
    case invalidResponse
    case unauthorized(String)
    case server(status: Int, message: String)

    var errorDescription: String? {
        switch self {
        case .invalidServerAddress:
            return "Enter a valid HTTP or HTTPS Djin server address."
        case .invalidResponse:
            return "The Djin server returned an unreadable response."
        case .unauthorized(let message):
            return message
        case .server(_, let message):
            return message
        }
    }
}

enum ServerAddress {
    static func normalize(_ value: String) throws -> URL {
        var candidate = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !candidate.isEmpty else {
            throw APIError.invalidServerAddress
        }
        if !candidate.contains("://") {
            candidate = "http://\(candidate)"
        }

        guard var components = URLComponents(string: candidate),
              let scheme = components.scheme?.lowercased(),
              scheme == "http" || scheme == "https",
              components.host != nil,
              components.user == nil,
              components.password == nil,
              components.query == nil,
              components.fragment == nil,
              components.path.isEmpty || components.path == "/"
        else {
            throw APIError.invalidServerAddress
        }

        components.scheme = scheme
        components.path = ""
        guard let url = components.url else {
            throw APIError.invalidServerAddress
        }
        return url
    }

    static func usesDevelopmentHTTP(_ value: String) -> Bool {
        (try? normalize(value).scheme?.lowercased()) == "http"
    }

    static func usesLoopback(_ value: String) -> Bool {
        guard let host = try? normalize(value).host?.lowercased() else {
            return false
        }
        return host == "localhost" || host == "127.0.0.1" || host == "::1"
    }
}
