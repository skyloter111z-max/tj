import XCTest
@testable import SubmoaCore

final class WebAssetsTests: XCTestCase {
    func testExtensionlessPathsResolveToHTML() {
        XCTAssertEqual(WebAssets.candidates("/onboarding"), ["onboarding.html", "onboarding/index.html"])
        XCTAssertEqual(WebAssets.candidates("/party/p-netflix-1"), ["party/p-netflix-1.html", "party/p-netflix-1/index.html"])
    }

    func testRootAndDirectoriesResolveToIndex() {
        XCTAssertEqual(WebAssets.candidates("/"), ["index.html"])
        XCTAssertEqual(WebAssets.candidates("/party/"), ["party/index.html"])
    }

    func testStaticFilesPassThrough() {
        XCTAssertEqual(WebAssets.candidates("/_next/static/chunks/main.js"), ["_next/static/chunks/main.js"])
        XCTAssertEqual(WebAssets.mimeType("_next/static/chunks/main.js"), "text/javascript")
        XCTAssertEqual(WebAssets.mimeType("onboarding.txt"), "text/plain")
    }
}
