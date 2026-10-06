package kr.submoa.app

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** 서비스 앱 안에서 "구독 상태 화면"에 도착했는지 가늠하는 신호 */
class SubscriptionSignalTest {
    @Test
    fun `티빙 이용권 화면은 구독 상태로 본다`() {
        assertTrue(SubscriptionSignal.looksLikeSubscription("이용권\n광고형 스탠다드\n월 5,500원\n다음 결제일 2026.11.03"))
    }

    @Test
    fun `구글플레이 정기결제 화면도 구독 상태로 본다`() {
        assertTrue(SubscriptionSignal.looksLikeSubscription("YouTube Premium\n다음 결제: 2026. 11. 1.에 ₩14,900 결제 예정"))
    }

    @Test
    fun `요금제 고르는 화면은 넘어가지 않는다`() {
        // 가격은 여럿이지만 '다음 결제·이용 기간' 같은 구독 중 표시가 없다
        assertFalse(SubscriptionSignal.looksLikeSubscription("이용권 구매\n광고형 스탠다드 5,500원\n스탠다드 13,900원\n결제하기"))
    }

    @Test
    fun `앱 첫 화면이나 로그인 화면은 넘어가지 않는다`() {
        assertFalse(SubscriptionSignal.looksLikeSubscription("오늘의 추천\n인기 드라마\n이어보기"))
        assertFalse(SubscriptionSignal.looksLikeSubscription("로그인\n이메일\n비밀번호"))
    }

    // 실제 화면(2026-10, 사용자 캡처)에서 개인정보 줄은 뺐다
    @Test
    fun `넷플릭스 계정 화면은 금액이 없어도 구독 상태로 본다`() {
        val netflix = "계정\n멤버십 정보\n멤버십 시작: 2025년 6월\n광고형 스탠다드 멤버십\n네이버 멤버십 서비스 추가 옵션을 통해 청구\n결제 내역 확인"
        assertTrue(SubscriptionSignal.looksLikeSubscription(netflix))
    }

    @Test
    fun `쿠팡플레이 프로필의 와우회원 표시는 구독 상태로 본다`() {
        val coupang = "홍길동 >\nWOW! 와우회원\npremium 구독하고 광고 없이 시청하세요 >\n쿠플클럽\n2,330점 >"
        assertTrue(SubscriptionSignal.looksLikeSubscription(coupang))
    }

    @Test
    fun `와우회원 전용이나 가입 권유 문구로는 넘어가지 않는다`() {
        assertFalse(SubscriptionSignal.looksLikeSubscription("오늘의 추천\nWOW! 와우회원 전용\n인기 영화"))
        assertFalse(SubscriptionSignal.looksLikeSubscription("와우회원이 되어 보세요\n지금 가입하기"))
    }
}
