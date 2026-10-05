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
import android.media.projection.MediaProjectionManager
import android.provider.Settings
import android.webkit.JavascriptInterface
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Toast
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

    /** 카톡에서 내보내기를 공유받았다 — 홈을 다시 열면 홈이 원본을 꺼내 처리한다 */
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        if (intent.getBooleanExtra(EXTRA_IMPORTED, false) && ::web.isInitialized) {
            web.loadUrl(BuildConfig.WEB_URL)
        }
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

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == REQUEST_CAPTURE && resultCode == RESULT_OK && data != null) {
            ScreenCaptureService.start(this, resultCode, data)
            openPlaySubscriptions()
        }
    }

    /**
     * 구글플레이 구독 화면으로 보낸다. 그냥 https 링크는 크롬에서 빈(흰) 웹페이지로 열릴 때가 있어,
     * 플레이 스토어 앱(com.android.vending)으로 직접 보낸다. 플레이 앱이 없으면 기본 처리로 넘긴다.
     */
    private fun openPlaySubscriptions() {
        val url = Uri.parse("https://play.google.com/store/account/subscriptions")
        val toPlay = Intent(Intent.ACTION_VIEW, url).setPackage("com.android.vending")
        if (toPlay.resolveActivity(packageManager) != null) {
            runCatching { startActivity(toPlay) }.onSuccess { return }
        }
        runCatching { startActivity(Intent(Intent.ACTION_VIEW, url)) }
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

        /** 공유받은 카톡 내보내기 원본. 꺼내는 순간 기기에서 지운다 */
        @JavascriptInterface
        fun takePendingExport(): String = ImportStore.takePending(this@MainActivity)

        /** 웹이 원본에서 골라낸 카드 결제 알림만 저장한다 */
        @JavascriptInterface
        fun saveImportedAlerts(json: String) = ImportStore.addImported(this@MainActivity, json)

        @JavascriptInterface
        fun getImportedAlerts(): String = ImportStore.importedJson(this@MainActivity)

        @JavascriptInterface
        fun clearImported() {
            ImportStore.clearImported(this@MainActivity)
            runOnUiThread { dispatchResume() }
        }

        /** 화면 캡처 자동 읽기 시작: 캡처 동의를 받고, 동의하면 서비스가 뜨고 스토어 페이지가 열린다 */
        @JavascriptInterface
        fun startStoreCapture() = runOnUiThread {
            val mpm = getSystemService(MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
            runCatching { startActivityForResult(mpm.createScreenCaptureIntent(), REQUEST_CAPTURE) }
        }

        @JavascriptInterface
        fun takePendingOcrText(): String = StoreStore.takePendingOcr(this@MainActivity)

        @JavascriptInterface
        fun saveStoreSubs(json: String) = StoreStore.saveStoreSubs(this@MainActivity, json)

        @JavascriptInterface
        fun getStoreSubs(): String = StoreStore.storeSubsJson(this@MainActivity)

        @JavascriptInterface
        fun clearStoreSubs() {
            StoreStore.clearStoreSubs(this@MainActivity)
            runOnUiThread { dispatchResume() }
        }

        @JavascriptInterface
        fun openKakaoTalk() = runOnUiThread {
            val launch = packageManager.getLaunchIntentForPackage("com.kakao.talk")
            if (launch != null) startActivity(launch)
            else Toast.makeText(this@MainActivity, "카카오톡이 설치되어 있지 않아요", Toast.LENGTH_SHORT).show()
        }

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

    companion object {
        const val EXTRA_IMPORTED = "kr.submoa.app.IMPORTED"
        private const val REQUEST_NOTIFY = 1
        private const val REQUEST_CAPTURE = 2
    }
}
