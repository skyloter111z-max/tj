import Foundation

/// 카드 결제 알림을 앱 컨테이너 안 파일에만 쌓는다. 서버로 보내지 않는다.
///
/// 단축어가 부르는 App Intent와 화면은 서로 다른 시점·프로세스에서 이 파일을 연다.
/// 그래서 메모리에 들고 있지 않고 매번 파일을 읽는다(최대 수천 줄이라 충분히 가볍다).
public final class AlertStore: @unchecked Sendable {
    public struct Alert: Codable, Equatable, Sendable {
        public let body: String
        /// epoch 밀리초 — 안드로이드 AlertStore와 같은 단위다
        public let postedAt: Int64
    }

    public static let maxAlerts = 5000

    private let url: URL
    private let lock = NSLock()

    public init(url: URL) {
        self.url = url
    }

    /// 카드 결제 알림이면 저장하고 true. 아니면 버리고 false.
    @discardableResult
    public func addIfCardAlert(_ text: String, postedAt: Int64) -> Bool {
        let body = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !body.isEmpty, AlertFilter.isCardAlert(body) else { return false }
        add(Alert(body: body, postedAt: postedAt))
        return true
    }

    func add(_ alert: Alert) {
        lock.lock()
        defer { lock.unlock() }
        var alerts = read()
        // 같은 문자로 단축어가 두 번 돌 수 있다
        if alerts.contains(alert) { return }
        alerts.append(alert)
        if alerts.count > Self.maxAlerts { alerts = Array(alerts.suffix(Self.maxAlerts / 2)) }
        write(alerts)
    }

    public func all() -> [Alert] {
        lock.lock()
        defer { lock.unlock() }
        return read()
    }

    /// 웹에 넘길 JSON: [{"body": "...", "postedAt": 1696300000000}, ...]
    public func json() -> String {
        let data = (try? JSONEncoder().encode(all())) ?? Data("[]".utf8)
        return String(decoding: data, as: UTF8.self)
    }

    private func read() -> [Alert] {
        guard let text = try? String(contentsOf: url, encoding: .utf8) else { return [] }
        let decoder = JSONDecoder()
        return text.split(separator: "\n").compactMap { line in
            try? decoder.decode(Alert.self, from: Data(line.utf8))
        }
    }

    private func write(_ alerts: [Alert]) {
        let encoder = JSONEncoder()
        let lines = alerts.compactMap { try? encoder.encode($0) }.map { String(decoding: $0, as: UTF8.self) }
        try? FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try? (lines.joined(separator: "\n") + "\n").write(to: url, atomically: true, encoding: .utf8)
    }
}
