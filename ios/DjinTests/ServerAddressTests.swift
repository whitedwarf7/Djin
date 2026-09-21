import XCTest
@testable import Djin

final class ServerAddressTests: XCTestCase {
    func testAddsHTTPWhenSchemeIsMissing() throws {
        let url = try ServerAddress.normalize("my-mac.local:8765")

        XCTAssertEqual(url.absoluteString, "http://my-mac.local:8765")
    }

    func testAcceptsHTTPS() throws {
        let url = try ServerAddress.normalize("https://djin.example.com/")

        XCTAssertEqual(url.absoluteString, "https://djin.example.com")
    }

    func testRejectsCredentialsAndPaths() {
        XCTAssertThrowsError(try ServerAddress.normalize("http://user:pass@localhost:8765"))
        XCTAssertThrowsError(try ServerAddress.normalize("http://localhost:8765/djin"))
    }
}
