import AppIntents
import Foundation
import SubmoaCore

/// 단축어 "메시지" 자동화가 문자를 받을 때마다 부르는 동작.
///
/// 아이폰은 다른 앱의 알림(카톡·카드사 앱)을 읽을 수 없다. 문자는 단축어 자동화가 넘겨줄 수 있어서,
/// 카드 알림을 문자로 받는 사람은 안드로이드처럼 자동으로 쌓인다.
/// 카드 결제 문자가 아니면 AlertFilter가 그 자리에서 버린다.
struct SaveCardAlertIntent: AppIntent {
    static var title: LocalizedStringResource = "결제 알림 저장"
    static var description = IntentDescription("카드 결제 문자를 구독모아에 넘깁니다. 결제 알림이 아닌 문자는 바로 버립니다.")
    static var openAppWhenRun: Bool = false

    @Parameter(title: "문자 내용")
    var message: String

    func perform() async throws -> some IntentResult {
        let now = Int64(Date().timeIntervalSince1970 * 1000)
        AlertStore.shared.addIfCardAlert(message, postedAt: now)
        return .result()
    }
}

/// 앱을 깔기만 하면 단축어 앱의 동작 목록에 "구독모아 › 결제 알림 저장"이 뜬다
struct SubmoaShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(
            intent: SaveCardAlertIntent(),
            phrases: ["\(.applicationName)에 결제 알림 저장"],
            shortTitle: "결제 알림 저장",
            systemImageName: "creditcard"
        )
    }
}
