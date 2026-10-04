import XCTest
@testable import SubmoaCore

/// 삼성카드 알림 실제 형식(값은 바꿈). 문자는 앞에 [Web발신]이 붙는다.
final class AlertFilterTests: XCTestCase {
    func testPassesCardAlerts() {
        XCTAssertTrue(AlertFilter.isCardAlert("[Web발신]\n삼성1088승인 홍*동\n88,000원 일시불\n10/03 21:24 바다식당"))
        XCTAssertTrue(AlertFilter.isCardAlert("삼성카드 홍*동님 전자상거래이용\n05/06 01:26 테스트상점 42,400원"))
        XCTAssertTrue(AlertFilter.isCardAlert("[삼성카드]1088\n자동결제 04/12접수\nKT통신료(123456)\n55,000원"))
        XCTAssertTrue(AlertFilter.isCardAlert("[삼성카드]1088취소\n01/19 테스트상점\n-77,900원"))
    }

    func testDropsEverydayMessages() {
        XCTAssertFalse(AlertFilter.isCardAlert("우리 승인 났대 3,000원만 보내줘"))
        XCTAssertFalse(AlertFilter.isCardAlert("[Web발신] 인증번호 [123456]을 입력해 주세요"))
        XCTAssertFalse(AlertFilter.isCardAlert("[삼성카드] 결제일 안내\n홍*동 회원님, 결제일은 14일입니다."))
    }
}
