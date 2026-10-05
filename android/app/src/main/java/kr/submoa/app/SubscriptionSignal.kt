package kr.submoa.app

/**
 * 지금 화면이 "구독 상태" 화면인지 — 서비스 앱 안에서 사용자가 이용권·구독 화면에 도착했는지 — 를
 * OCR 글자로 가늠한다. 맞으면 캡처 서비스가 그 화면을 읽고 다음 서비스로 넘어간다.
 *
 * 요금제를 고르는 화면(가격이 여럿 + "결제하기")에서 잘못 넘어가지 않도록, "다음 결제·결제 예정·이용 기간"
 * 처럼 **이미 구독 중일 때만** 나오는 말과 금액이 함께 있어야 한다.
 */
object SubscriptionSignal {
    private val STATUS = Regex(
        "다음\\s*결제|결제\\s*예정|정기\\s*결제일|자동\\s*결제일|이용\\s*기간|해지\\s*예약|next\\s*(billing|payment)|renews?\\b",
        RegexOption.IGNORE_CASE,
    )
    private val PRICE = Regex("₩\\s?\\d{1,3}(,\\d{3})+|\\d{1,3}(,\\d{3})+\\s*원|\\d{3,}\\s*원|\\$\\s?\\d")

    fun looksLikeSubscription(text: String): Boolean =
        STATUS.containsMatchIn(text) && PRICE.containsMatchIn(text)
}
