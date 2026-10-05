package kr.submoa.app

import android.content.Context
import android.content.Intent
import android.net.Uri

/**
 * 구독 화면을 어디서 열지 정한다.
 *
 * OTT·AI 사이트는 브라우저에서 열면 로그인 화면만 뜬다(브라우저엔 로그인이 안 돼 있다). 사용자가
 * 로그인해 쓰는 곳은 각 서비스의 **앱**이므로, 앱이 깔려 있으면 앱으로 연다. 앱 안에서 구독(이용권)
 * 화면까지는 사용자가 한두 번 눌러 이동하고, 그 화면이 보이면 캡처 서비스가 알아서 읽는다(GUIDED).
 *
 *   AUTO    여는 즉시 그 화면이 구독 목록이다(구글플레이 정기결제, 앱스토어 등) → 몇 초 뒤 자동으로 읽는다
 *   GUIDED  서비스 앱을 연다 → 사용자가 구독 화면으로 이동하면 감지해 읽는다(또는 "읽기" 버튼)
 *   SKIP    그 서비스 앱이 이 폰에 없다 → 건너뛴다(브라우저는 로그인 벽이라 읽을 게 없다)
 */
object CaptureApps {
    enum class Mode { AUTO, GUIDED, SKIP }

    private data class App(val pkg: String, val hint: String)

    /** 서비스 id → 앱 패키지와, 앱 안에서 구독 화면으로 가는 길 안내 */
    private val APPS = mapOf(
        "netflix" to App("com.netflix.mediaclient", "프로필 → 계정에서 멤버십 화면을 열어 주세요"),
        "disneyplus" to App("com.disney.disneyplus", "내 정보 → 계정 → 구독 화면을 열어 주세요"),
        "tving" to App("net.cj.cjhv.gs.tving", "마이 → 이용권 화면을 열어 주세요"),
        "wavve" to App("kr.co.captv.pooqV2", "마이 → 이용권 화면을 열어 주세요"),
        "coupangplay" to App("com.coupang.mobile", "마이쿠팡 → 와우 멤버십 화면을 열어 주세요"),
        "chatgpt" to App("com.openai.chatgpt", "설정 → 구독(플랜) 화면을 열어 주세요"),
        "claude" to App("com.anthropic.claude", "설정 → 구독·결제 화면을 열어 주세요"),
        "gemini" to App("com.google.android.apps.subscriptions.red", "Google One 멤버십 화면을 열어 주세요"),
        "perplexity" to App("ai.perplexity.app.android", "설정 → 구독 화면을 열어 주세요"),
    )

    private fun isPlay(url: String) = Uri.parse(url).host?.contains("play.google.com") == true

    private fun installed(context: Context, pkg: String) =
        context.packageManager.getLaunchIntentForPackage(pkg) != null

    fun modeFor(context: Context, id: String, url: String): Mode {
        if (isPlay(url)) return Mode.AUTO
        val app = APPS[id] ?: return Mode.AUTO // 스토어 전체(앱스토어) 등: 그대로 연다
        return if (installed(context, app.pkg)) Mode.GUIDED else Mode.SKIP
    }

    fun hintFor(id: String): String = APPS[id]?.hint ?: "구독(멤버십) 화면을 열어 주세요"

    /**
     * 대상 화면을 연다. 서비스에서 열 때는 newTask=true.
     *  - 플레이 구독 주소는 플레이 스토어 앱으로(크롬에선 빈 페이지가 뜬다)
     *  - 서비스 앱이 있으면: 그 주소를 앱이 받으면 앱 안의 그 화면으로, 아니면 앱 첫 화면으로
     */
    fun open(context: Context, id: String, url: String, newTask: Boolean): Mode {
        val mode = modeFor(context, id, url)
        val uri = Uri.parse(url)
        val flags = if (newTask) Intent.FLAG_ACTIVITY_NEW_TASK else 0
        val pm = context.packageManager
        when (mode) {
            Mode.SKIP -> Unit
            Mode.GUIDED -> {
                val pkg = APPS.getValue(id).pkg
                val inApp = Intent(Intent.ACTION_VIEW, uri).setPackage(pkg).addFlags(flags)
                val opened = inApp.resolveActivity(pm) != null && runCatching { context.startActivity(inApp) }.isSuccess
                if (!opened) {
                    pm.getLaunchIntentForPackage(pkg)
                        ?.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                        ?.let { runCatching { context.startActivity(it) } }
                }
            }
            Mode.AUTO -> {
                if (isPlay(url)) {
                    val toPlay = Intent(Intent.ACTION_VIEW, uri).setPackage("com.android.vending").addFlags(flags)
                    if (toPlay.resolveActivity(pm) != null && runCatching { context.startActivity(toPlay) }.isSuccess) {
                        return mode
                    }
                }
                runCatching { context.startActivity(Intent(Intent.ACTION_VIEW, uri).addFlags(flags)) }
            }
        }
        return mode
    }
}
