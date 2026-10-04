import Foundation

/// 문자 하나가 카드 결제 알림인지 가른다. 안드로이드 `AlertFilter.kt`와 같은 규칙이다.
///
/// 단축어 자동화는 조건에 맞는 문자를 전부 넘겨준다. 여기를 통과하지 못한 문자는 저장하지 않고
/// 그 자리에서 버린다. 정밀한 해석은 웹 쪽 `lib/card-alerts/parse.ts`가 한다.
///
/// 세 조건을 모두 만족해야 한다:
///   1. 카드사 표기: "삼성카드", "삼성1088", "신한(1234)" — "우리", "하나"만으로는 일상 대화와 구분되지 않는다
///   2. 결제 동작: 승인·취소·전자상거래이용·자동결제
///   3. 금액: "12,000원"
public enum AlertFilter {
    private static let issuer = try! NSRegularExpression(
        pattern: "(삼성|신한|KB국민|국민|현대|롯데|하나|우리|BC|비씨|NH농협|농협|씨티|IBK)(카드|\\d{4}|\\(\\d{4}\\))"
    )
    private static let action = try! NSRegularExpression(pattern: "승인|취소|전자상거래이용|자동결제")
    private static let amount = try! NSRegularExpression(pattern: "[\\d,]+원")

    public static func isCardAlert(_ body: String) -> Bool {
        matches(issuer, body) && matches(action, body) && matches(amount, body)
    }

    private static func matches(_ re: NSRegularExpression, _ s: String) -> Bool {
        re.firstMatch(in: s, range: NSRange(s.startIndex..., in: s)) != nil
    }
}
