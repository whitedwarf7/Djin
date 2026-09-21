import Foundation

struct APIClient {
    let baseURL: URL
    let token: String?

    private let session: URLSession
    private let encoder = JSONEncoder()
    private let decoder = JSONDecoder()

    init(baseURL: URL, token: String? = nil, session: URLSession = .shared) {
        self.baseURL = baseURL
        self.token = token
        self.session = session
    }

    func login(username: String, password: String) async throws -> AuthResponse {
        try await post(
            path: "/api/auth/login",
            body: LoginRequest(username: username, password: password)
        )
    }

    func currentUser() async throws -> UserProfile {
        try await get(path: "/api/auth/me")
    }

    func status() async throws -> ServerStatus {
        try await get(path: "/api/status")
    }

    func conversations(limit: Int = 40) async throws -> [ConversationSummary] {
        try await get(
            path: "/api/conversations",
            queryItems: [URLQueryItem(name: "limit", value: String(limit))]
        )
    }

    func conversation(id: String) async throws -> ConversationDetail {
        try await get(path: "/api/conversations/\(id)")
    }

    func deleteConversation(id: String) async throws {
        let _: DeleteResponse = try await request(
            path: "/api/conversations/\(id)",
            method: "DELETE"
        )
    }

    func logout() async throws {
        let request = try makeRequest(path: "/api/auth/logout", method: "POST")
        let (data, response) = try await session.data(for: request)
        try validate(response: response, data: data)
    }

    func streamChat(_ request: ChatRequest) throws -> AsyncThrowingStream<StreamEvent, Error> {
        try stream(path: "/api/chat/stream", body: request)
    }

    func streamDecision(
        actionID: String,
        request: DecisionRequest
    ) throws -> AsyncThrowingStream<StreamEvent, Error> {
        try stream(path: "/api/actions/\(actionID)/decision/stream", body: request)
    }

    private func get<Response: Decodable>(
        path: String,
        queryItems: [URLQueryItem] = []
    ) async throws -> Response {
        try await request(path: path, method: "GET", queryItems: queryItems)
    }

    private func post<Body: Encodable, Response: Decodable>(
        path: String,
        body: Body
    ) async throws -> Response {
        try await request(path: path, method: "POST", body: encoder.encode(body))
    }

    private func request<Response: Decodable>(
        path: String,
        method: String,
        queryItems: [URLQueryItem] = [],
        body: Data? = nil
    ) async throws -> Response {
        let request = try makeRequest(
            path: path,
            method: method,
            queryItems: queryItems,
            body: body
        )
        let (data, response) = try await session.data(for: request)
        try validate(response: response, data: data)
        do {
            return try decoder.decode(Response.self, from: data)
        } catch {
            throw APIError.invalidResponse
        }
    }

    private func stream<Body: Encodable>(
        path: String,
        body: Body
    ) throws -> AsyncThrowingStream<StreamEvent, Error> {
        var request = try makeRequest(
            path: path,
            method: "POST",
            body: encoder.encode(body),
            timeout: 300
        )
        request.setValue("text/event-stream", forHTTPHeaderField: "Accept")
        let session = session

        return AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    let (bytes, response) = try await session.bytes(for: request)
                    guard let httpResponse = response as? HTTPURLResponse else {
                        throw APIError.invalidResponse
                    }
                    guard (200..<300).contains(httpResponse.statusCode) else {
                        var errorData = Data()
                        for try await byte in bytes {
                            errorData.append(byte)
                        }
                        throw Self.responseError(status: httpResponse.statusCode, data: errorData)
                    }

                    let streamDecoder = SSEDecoder()
                    for try await line in bytes.lines {
                        try Task.checkCancellation()
                        if let event = try streamDecoder.decode(line: line) {
                            continuation.yield(event)
                        }
                    }
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { _ in
                task.cancel()
            }
        }
    }

    private func makeRequest(
        path: String,
        method: String,
        queryItems: [URLQueryItem] = [],
        body: Data? = nil,
        timeout: TimeInterval = 30
    ) throws -> URLRequest {
        guard var components = URLComponents(url: baseURL, resolvingAgainstBaseURL: false) else {
            throw APIError.invalidServerAddress
        }
        components.path = path
        components.queryItems = queryItems.isEmpty ? nil : queryItems
        guard let url = components.url else {
            throw APIError.invalidServerAddress
        }

        var request = URLRequest(url: url, timeoutInterval: timeout)
        request.httpMethod = method
        request.httpBody = body
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if body != nil {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        if let token, !token.isEmpty {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        return request
    }

    private func validate(response: URLResponse, data: Data) throws {
        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }
        guard (200..<300).contains(httpResponse.statusCode) else {
            throw Self.responseError(status: httpResponse.statusCode, data: data)
        }
    }

    private static func responseError(status: Int, data: Data) -> APIError {
        let message: String
        if let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let detail = object["detail"] as? String {
            message = detail
        } else {
            message = "The Djin server returned HTTP \(status)."
        }

        if status == 401 {
            return .unauthorized(message)
        }
        return .server(status: status, message: message)
    }
}