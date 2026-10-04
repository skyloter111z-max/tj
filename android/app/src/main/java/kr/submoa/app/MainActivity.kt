package kr.submoa.app

import android.Manifest
import android.annotation.SuppressLint
import android.app.Activity
import android.content.ComponentName
import android.content.Intent
import android.content.pm.PackageManager
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

    /** 알림 권한을 묻는 동안 모의 알림 요청을 들고 있는다 */
    private var pendingSimulate = false

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
        dispatchResume()
    }

    private fun dispatchResume() {
        if (::web.isInitialized) {
            web.evaluateJavascript("window.dispatchEvent(new Event('submoa:resume'))", null)
        }
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == REQUEST_NOTIFY && pendingSimulate) {
            pendingSimulate = false
            if (grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED) postSimulated()
        }
    }

    private fun postSimulated() {
        if (!SimulatedAlert.post(this)) return
        // 리스너가 받아 저장할 시간을 준 뒤 화면을 새로 읽게 한다
        web.postDelayed({ dispatchResume() }, 1000)
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

        /** 디버그 빌드에서만 웹에 모의 결제 버튼이 뜬다 */
        @JavascriptInterface
        fun canSimulate(): Boolean = BuildConfig.DEBUG

        @JavascriptInterface
        fun simulatePaymentAlert() = runOnUiThread {
            if (!BuildConfig.DEBUG) return@runOnUiThread
            val needsPermission = Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
                checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
            if (needsPermission) {
                pendingSimulate = true
                requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), REQUEST_NOTIFY)
            } else {
                postSimulated()
            }
        }

        @JavascriptInterface
        fun clearSimulated() {
            if (!BuildConfig.DEBUG) return
            AlertStore.get(this@MainActivity).removeIf { it.contains(SimulatedAlert.MERCHANT) }
            runOnUiThread { dispatchResume() }
        }
    }

    private companion object {
        const val REQUEST_NOTIFY = 1
    }
}
