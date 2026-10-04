package kr.submoa.app

import android.app.Notification
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import androidx.core.app.NotificationCompat

/**
 * 폰에 뜨는 알림 중 카드 결제 알림만 저장한다.
 *
 * 카톡 알림톡, 문자, 카드사 앱 푸시, 토스 카드 알림이 모두 이 경로로 들어온다.
 * 패키지로 거르지 않고 내용으로 거른다 — 카드사 앱 패키지명을 일일이 알 필요가 없다.
 * 카드 결제 알림이 아닌 것은 읽은 자리에서 버린다(AlertFilter).
 */
class AlertListenerService : NotificationListenerService() {

    override fun onListenerConnected() {
        // 허용 직후, 알림창에 아직 남아 있는 결제 알림도 주워 담는다
        runCatching { activeNotifications }.getOrNull()?.forEach(::capture)
    }

    override fun onNotificationPosted(sbn: StatusBarNotification) = capture(sbn)

    private fun capture(sbn: StatusBarNotification) {
        if (sbn.packageName == packageName) return
        val notification = sbn.notification
        if (notification.flags and Notification.FLAG_GROUP_SUMMARY != 0) return

        val extras = notification.extras
        val title = extras.getCharSequence(Notification.EXTRA_TITLE)?.toString()
        val store = AlertStore.get(this)

        for ((text, time) in messagesOf(sbn)) {
            val body = text.trim()
            if (body.isEmpty() || !AlertFilter.isCardAlert(title, body)) continue
            store.add(body, if (time > 0) time else sbn.postTime)
        }
    }

    /**
     * 알림에서 (본문, 수신 시각) 목록을 꺼낸다.
     *
     * 카톡은 MessagingStyle이라 한 알림에 안 읽은 메시지가 여러 개, 각자 시각과 함께 들어 있다.
     * 그 밖의 앱은 펼친 본문(BIG_TEXT)이 있으면 그것을, 없으면 한 줄 본문을 쓴다.
     */
    private fun messagesOf(sbn: StatusBarNotification): List<Pair<String, Long>> {
        val notification = sbn.notification
        val style = NotificationCompat.MessagingStyle.extractMessagingStyleFromNotification(notification)
        if (style != null && style.messages.isNotEmpty()) {
            return style.messages.mapNotNull { m -> m.text?.toString()?.let { it to m.timestamp } }
        }
        val extras = notification.extras
        val text = extras.getCharSequence(Notification.EXTRA_BIG_TEXT)
            ?: extras.getCharSequence(Notification.EXTRA_TEXT)
            ?: return emptyList()
        return listOf(text.toString() to sbn.postTime)
    }
}
