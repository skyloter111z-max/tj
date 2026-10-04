package kr.submoa.app

import android.annotation.SuppressLint
import android.app.Activity
import android.content.ComponentName
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.webkit.JavascriptInterface
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.core.app.NotificationManagerCompat

/**
 * 화면은 웹 앱(Next.js)을 그대로 띄운다. 해석·판정 로직도 웹 쪽 TypeScript 하나뿐이다.
 * 네이티브는 알림을 모으는 일과, 그것을 웹에 건네는 `SubmoaBridge`만 맡는다.
 */
class MainActivity : Activity() {
    private lateinit var web: WebView
    private val allowedHost: String? = Uri.parse(BuildConfig.WEB_URL).host

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        web = WebView(this)
        setContentView(web)

        web.settings.javaScriptEnabled = true
        web.settings.domStorageEnabled = true // 온보딩 선택을 localStorage에 둔다
        web.addJavascriptInterface(Bridge(), "SubmoaBridge")

        // 브리지는 결제 알림을 내준다. 우리 웹 앱이 아닌 페이지는 이 WebView에서 열지 않는다.
        val assetLoader = WebAssets.loader(assets)
        web.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                if (request.url.host == allowedHost) return false
                startActivity(Intent(Intent.ACTION_VIEW, request.url))
                return true
            }

            override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse? =
                assetLoader.shouldInterceptRequest(request.url)
        }

        web.loadUrl(BuildConfig.WEB_URL)
    }

    override fun onResume() {
        super.onResume()
        // 설정 화면에서 알림 접근을 켜고 돌아온 순간을 웹이 알 수 있게 한다
        if (::web.isInitialized) {
            web.evaluateJavascript("window.dispatchEvent(new Event('submoa:resume'))", null)
        }
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        if (web.canGoBack()) web.goBack() else @Suppress("DEPRECATION") super.onBackPressed()
    }

    /** 웹에서 window.SubmoaBridge로 부른다. lib/card-alerts/bridge.ts와 짝이다 */
    inner class Bridge {
        @JavascriptInterface
        fun platform(): String = "android"

        @JavascriptInterface
        fun isAccessGranted(): Boolean =
            NotificationManagerCompat.getEnabledListenerPackages(this@MainActivity).contains(packageName)

        @JavascriptInterface
        fun openAccessSettings() = runOnUiThread {
            // Android 11+는 이 앱의 토글 화면으로 바로 간다. 그 이전은 목록 화면이다.
            val intent = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                Intent(Settings.ACTION_NOTIFICATION_LISTENER_DETAIL_SETTINGS).putExtra(
                    Settings.EXTRA_NOTIFICATION_LISTENER_COMPONENT_NAME,
                    ComponentName(this@MainActivity, AlertListenerService::class.java).flattenToString(),
                )
            } else {
                Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS)
            }
            runCatching { startActivity(intent) }
                .onFailure { startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS)) }
        }

        @JavascriptInterface
        fun getAlerts(): String = AlertStore.get(this@MainActivity).toJson()
    }
}
