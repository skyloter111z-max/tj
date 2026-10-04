package kr.submoa.app

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** 삼성카드 카카오톡 알림방 실제 형식(값은 바꿈)과, 걸러야 할 일상 대화 */
class AlertFilterTest {
    @Test
    fun `일반 승인을 통과시킨다`() {
        assertTrue(AlertFilter.isCardAlert("삼성카드", "삼성1088승인 홍*동\n88,000원 일시불\n10/03 21:24 바다식당"))
    }

    @Test
    fun `전자상거래 승인을 통과시킨다`() {
        assertTrue(AlertFilter.isCardAlert("삼성카드", "삼성카드 홍*동님 전자상거래이용\n05/06 01:26 테스트상점 42,400원"))
    }

    @Test
    fun `자동납부와 취소를 통과시킨다`() {
        assertTrue(AlertFilter.isCardAlert("삼성카드", "[삼성카드]1088\n자동결제 04/12접수\nKT통신료(123456)\n55,000원"))
        assertTrue(AlertFilter.isCardAlert("삼성카드", "[삼성카드]1088취소\n01/19 테스트상점\n-77,900원"))
    }

    @Test
    fun `알림 미리보기처럼 제목 없이 한 줄로 와도 통과시킨다`() {
        assertTrue(AlertFilter.isCardAlert(null, "삼성1088승인 홍*동 88,000원 일시불 10/03 21:24 바다식당"))
    }

    @Test
    fun `카드사 이름이 들어간 일상 대화는 버린다`() {
        assertFalse(AlertFilter.isCardAlert("엄마", "우리 승인 났대 3,000원만 보내줘"))
        assertFalse(AlertFilter.isCardAlert("친구", "하나 취소했어 만원 돌려받음"))
    }

    @Test
    fun `카드사 안내·광고는 버린다`() {
        assertFalse(AlertFilter.isCardAlert("삼성카드", "[삼성카드] 결제일 안내\n홍*동 회원님, 결제일은 14일입니다."))
    }
}
