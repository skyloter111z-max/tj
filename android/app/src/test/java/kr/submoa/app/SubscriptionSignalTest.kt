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
}
