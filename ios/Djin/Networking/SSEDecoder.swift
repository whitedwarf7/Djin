import Foundation

struct SSEDecoder {
    private let decoder = JSONDecoder()

    func decode(line: String) throws -> StreamEvent? {
        let trimmed = line.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed.hasPrefix("data:") else {
            return nil
        }

        let payload = trimmed.dropFirst(5).trimmingCharacters(in: .whitespaces)
        guard !payload.isEmpty, let data = payload.data(using: .utf8) else {
            return nil
        }
        return try decoder.decode(StreamEvent.self, from: data)
    }
}
