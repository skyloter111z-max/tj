package kr.submoa.app

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.Person
import java.util.Calendar
import java.util.Locale

/**
 * 실제 결제 없이 알림 읽기를 시험한다 (디버그 빌드 전용).
 *
 * 삼성카드 카톡 알림톡과 같은 본문을, 카톡처럼 MessagingStyle 알림으로 띄운다. 그러면
 * 시스템 → AlertListenerService → AlertFilter → AlertStore → 웹 화면까지 실제 경로를 그대로 탄다.
 * 카톡 앱이 알림을 만드는 방식 자체는 시험하지 못한다 — 그건 카톡으로 이 본문을 받아 봐야 안다.
 */
object SimulatedAlert {
    const val CHANNEL_ID = "simulated-payment"

    /** 모의 알림을 지울 때 이 가맹점명으로 찾는다 */
    const val MERCHANT = "모의결제"

    private val AMOUNTS = intArrayOf(4500, 9900, 13500, 17000)

    /** 삼성카드 승인 알림톡 형식 (lib/card-alerts/parse.ts의 CARD_TX) */
    fun body(at: Calendar, amount: Int): String {
        val date = String.format(Locale.US, "%02d/%02d", at.get(Calendar.MONTH) + 1, at.get(Calendar.DAY_OF_MONTH))
        val time = String.format(Locale.US, "%02d:%02d", at.get(Calendar.HOUR_OF_DAY), at.get(Calendar.MINUTE))
        val won = String.format(Locale.US, "%,d", amount)
        return "삼성1088승인 홍*동\n${won}원 일시불\n$date $time $MERCHANT"
    }

    /** 알림을 띄웠으면 true. Android 13+에서 알림 권한이 없으면 false */
    fun post(context: Context): Boolean {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            return false
        }
        val manager = context.getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(
            NotificationChannel(CHANNEL_ID, "모의 결제 알림 (테스트)", NotificationManager.IMPORTANCE_DEFAULT),
        )

        val now = System.currentTimeMillis()
        val text = body(Calendar.getInstance(), AMOUNTS.random())
        val sender = Person.Builder().setName("삼성카드").build()
        val me = Person.Builder().setName("나").build()
        val notification = NotificationCompat.Builder(context, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.stat_notify_chat)
            .setContentTitle("삼성카드")
            .setContentText(text)
            .setStyle(NotificationCompat.MessagingStyle(me).addMessage(text, now, sender))
            .setAutoCancel(true)
            .build()
        manager.notify(now.toInt(), notification)
        return true
    }
}
