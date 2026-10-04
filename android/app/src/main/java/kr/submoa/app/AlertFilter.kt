package kr.submoa.app

/**
 * 알림 하나가 카드 결제 알림인지 가른다.
 *
 * 카톡 알림에는 친구와 나눈 대화도 섞여 온다. 여기를 통과하지 못한 알림은 저장하지
 * 않고 그 자리에서 버린다. 정밀한 해석(금액·가맹점·날짜)은 웹 쪽
 * `lib/card-alerts/parse.ts`가 한다 — 여기서는 "카드사가 보낸 결제 알림처럼 생겼는가"만 본다.
 *
 * 세 조건을 모두 만족해야 한다:
 *   1. 카드사 표기: "삼성카드", "삼성1088", "신한(1234)" 처럼 카드사 이름 뒤에 "카드"나 카드 번호
 *      — "우리", "하나" 같은 이름만으로는 일상 대화와 구분되지 않는다
 *   2. 결제 동작: 승인·취소·전자상거래이용·자동결제
 *   3. 금액: "12,000원"
 */
object AlertFilter {
    private val ISSUER = Regex(
        "(삼성|신한|KB국민|국민|현대|롯데|하나|우리|BC|비씨|NH농협|농협|씨티|IBK)" +
            "(카드|\\d{4}|\\(\\d{4}\\))",
    )
    private val ACTION = Regex("승인|취소|전자상거래이용|자동결제")
    private val AMOUNT = Regex("[\\d,]+원")

    /** 알림 제목(보낸 사람)과 본문을 함께 본다. 카톡 알림톡은 제목이 카드사 채널 이름이다 */
    fun isCardAlert(title: String?, body: String): Boolean {
        val text = if (title.isNullOrBlank()) body else "$title\n$body"
        return ISSUER.containsMatchIn(text) &&
            ACTION.containsMatchIn(body) &&
            AMOUNT.containsMatchIn(body)
    }
}
