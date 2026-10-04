import XCTest
@testable import SubmoaCore

final class AlertStoreTests: XCTestCase {
    private func tempStore() -> (AlertStore, URL) {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
            .appendingPathComponent("card-alerts.jsonl")
        return (AlertStore(url: url), url)
    }

    private let approval = "삼성1088승인 홍*동\n88,000원 일시불\n10/03 21:24 바다식당"

    func testKeepsOnlyCardAlerts() {
        let (store, _) = tempStore()
        XCTAssertTrue(store.addIfCardAlert(approval, postedAt: 1))
        XCTAssertFalse(store.addIfCardAlert("오늘 저녁 뭐 먹어?", postedAt: 2))
        XCTAssertEqual(store.all().map(\.body), [approval])
    }

    func testIgnoresTheSameMessageTwice() {
        let (store, _) = tempStore()
        store.addIfCardAlert(approval, postedAt: 1)
        store.addIfCardAlert(approval, postedAt: 1)
        XCTAssertEqual(store.all().count, 1)
    }

    /// 단축어(App Intent)가 쓴 것을 화면이 새 인스턴스로 읽는다
    func testAnotherInstanceSeesSavedAlerts() {
        let (store, url) = tempStore()
        store.addIfCardAlert(approval, postedAt: 1_696_300_000_000)
        let reader = AlertStore(url: url)
        XCTAssertEqual(reader.all(), [AlertStore.Alert(body: approval, postedAt: 1_696_300_000_000)])
        XCTAssertTrue(reader.json().contains("\"postedAt\":1696300000000"))
    }

    func testEmptyStoreIsEmptyJSONArray() {
        let (store, _) = tempStore()
        XCTAssertEqual(store.json(), "[]")
    }
}
