package kr.submoa.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.Calendar

class SimulatedAlertTest {
    private val at = Calendar.getInstance().apply { set(2026, Calendar.OCTOBER, 4, 9, 5) }

    /** 웹 parse.test.ts의 "앱의 모의 알림"과 같은 문자열이어야 한다 */
    @Test
    fun `삼성카드 승인 알림톡 형식으로 만든다`() {
        assertEquals("삼성1088승인 홍*동\n13,500원 일시불\n10/04 09:05 모의결제", SimulatedAlert.body(at, 13500))
    }

    @Test
    fun `알림 걸러내기를 통과한다`() {
        assertTrue(AlertFilter.isCardAlert("삼성카드", SimulatedAlert.body(at, 4500)))
    }
}
