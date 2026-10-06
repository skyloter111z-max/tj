package kr.submoa.app

/**
 * 지금 화면이 "구독 상태" 화면인지 — 서비스 앱 안에서 사용자가 이용권·구독 화면에 도착했는지 — 를
 * OCR 글자로 가늠한다. 맞으면 캡처 서비스가 그 화면을 읽고 다음 서비스로 넘어간다.
 *
 * 두 종류를 받는다.
 *  1. "다음 결제·결제 예정·이용 기간" + 금액 — 이용권 화면, 구글플레이 정기결제
 *  2. 금액은 없지만 **가입 중일 때만** 나오는 표시 — 넷플릭스 계정의 "멤버십 시작: 2025년 6월",
 *     쿠팡플레이 프로필의 "WOW! 와우회원" 한 줄 (실제 화면 2026-10 확인)
 * 요금제를 고르는 화면(가격이 여럿 + "결제하기")이나 "와우회원 전용" 같은 안내 문구에서는 넘어가지 않는다.
 */
object SubscriptionSignal {
    private val STATUS = Regex(
        "다음\\s*결제|결제\\s*예정|정기\\s*결제일|자동\\s*결제일|이용\\s*기간|해지\\s*예약|next\\s*(billing|payment)|renews?\\b",
        RegexOption.IGNORE_CASE,
    )
    private val PRICE = Regex("₩\\s?\\d{1,3}(,\\d{3})+|\\d{1,3}(,\\d{3})+\\s*원|\\d{3,}\\s*원|\\$\\s?\\d")

    /** 가입 중일 때만 보이는 표시 */
    private val MEMBER_SINCE = Regex("멤버십\\s*시작")
    private val WOW_MEMBER_LINE = Regex("^\\W*(wow\\W*)?와우\\s*회원\\s*$", RegexOption.IGNORE_CASE)

    fun looksLikeSubscription(text: String): Boolean =
        (STATUS.containsMatchIn(text) && PRICE.containsMatchIn(text)) ||
            MEMBER_SINCE.containsMatchIn(text) ||
            text.lines().any { WOW_MEMBER_LINE.matches(it.trim()) }
}
