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
import android.graphics.Bitmap
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.text.TextRecognition
import com.google.mlkit.vision.text.korean.KoreanTextRecognizerOptions
import org.json.JSONArray

/**
 * 화면은 웹 앱(Next.js)을 그대로 띄운다. 해석·판정 로직도 웹 쪽 TypeScript 하나뿐이다.
 * 네이티브는 알림을 모으는 일과, 그것을 웹에 건네는 `SubmoaBridge`만 맡는다.
 */
class MainActivity : Activity() {
    private lateinit var web: WebView
    private val allowedHost: String? = Uri.parse(BuildConfig.WEB_URL).host

    /** 알림 권한을 묻는 동안 모의 알림 요청을 들고 있는다 */
    private var pendingSimulate = false

    /** 캡처 동의를 받는 동안, 동의하면 차례로 열어 읽을 화면들의 JSON([{id,url}])을 들고 있는다 */
    private var pendingCaptureQueue = "[]"

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
        warmUpOcr()
    }

    /**
     * 한국어 OCR 모델을 미리 받아 둔다. Play 서비스가 처음 쓸 때 내려받는데, 그때까지 첫 캡처가
     * "글자를 못 읽음"으로 실패할 수 있어서, 앱을 켤 때 작은 더미 이미지로 미리 깨워 둔다.
     */
    private fun warmUpOcr() {
        runCatching {
            val bmp = Bitmap.createBitmap(1, 1, Bitmap.Config.ARGB_8888)
            TextRecognition.getClient(KoreanTextRecognizerOptions.Builder().build())
                .process(InputImage.fromBitmap(bmp, 0))
        }
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
            ScreenCaptureService.start(this, resultCode, data, pendingCaptureQueue)
            // 첫 화면은 (포그라운드 권한이 있는) 액티비티가 연다. 나머지는 서비스가 순서대로 연다.
            val first = runCatching { JSONArray(pendingCaptureQueue).optJSONObject(0) }.getOrNull()
            if (first != null) CaptureApps.open(this, first.optString("id"), first.optString("url"), newTask = false)
        }
        // '다른 앱 위에 표시' 설정에서 돌아왔다 — 허용됐든 아니든 캡처는 진행한다
        if (requestCode == REQUEST_OVERLAY) proceedToConsent()
    }

    /**
     * 큐에서 이 폰에 앱이 없는 서비스를 뺀다(브라우저로 열면 로그인 화면뿐이라 읽을 게 없다).
     * 남은 큐와, 빠진 서비스 이름들을 돌려준다.
     */
    private fun dropMissingApps(queueJson: String): Pair<JSONArray, List<String>> {
        val arr = runCatching { JSONArray(queueJson) }.getOrDefault(JSONArray())
        val kept = JSONArray()
        val skipped = mutableListOf<String>()
        for (i in 0 until arr.length()) {
            val o = arr.optJSONObject(i) ?: continue
            val id = o.optString("id")
            val url = o.optString("url")
            if (url.isBlank()) continue
            if (CaptureApps.modeFor(this, id, url) == CaptureApps.Mode.SKIP) skipped += o.optString("name").ifBlank { id }
            else kept.put(o)
        }
        return kept to skipped
    }

    /**
     * 떠 있는 안내창이 필요한가: 화면이 여럿이면(자동 전환), 또는 서비스 앱 안에서 읽어야 하면
     * ('읽기'·'건너뛰기' 버튼). 구글플레이 한 장만 읽을 때는 필요 없다.
     */
    private fun needsOverlay(queue: JSONArray): Boolean {
        if (queue.length() > 1) return true
        val o = queue.optJSONObject(0) ?: return false
        return CaptureApps.modeFor(this, o.optString("id"), o.optString("url")) == CaptureApps.Mode.GUIDED
    }

    /**
     * 화면 캡처 자동 읽기 시작. 큐([{id,url,name}])의 화면들을 한 번의 동의로 차례로 읽는다.
     *
     * 안내창이 필요하면 '다른 앱 위에 표시'(오버레이) 권한을 먼저 받는다 — 이 권한이 있어야 앱이 다음
     * 화면으로 자동 전환할 수 있다(안드로이드 백그라운드 실행 제한을 이 권한이 풀어 준다).
     */
    private fun beginCapture(queueJson: String) = runOnUiThread {
        val (queue, skipped) = dropMissingApps(queueJson)
        if (skipped.isNotEmpty()) {
            Toast.makeText(this, "${skipped.joinToString("·")}: 이 폰에 앱이 없어 건너뛰어요", Toast.LENGTH_LONG).show()
        }
        if (queue.length() == 0) {
            Toast.makeText(this, "읽을 수 있는 서비스 앱이 이 폰에 없어요", Toast.LENGTH_LONG).show()
            return@runOnUiThread
        }
        pendingCaptureQueue = queue.toString()
        if (needsOverlay(queue) && !Settings.canDrawOverlays(this)) {
            Toast.makeText(this, "구독 화면을 자동으로 넘기며 읽으려면 '다른 앱 위에 표시'를 켜 주세요", Toast.LENGTH_LONG).show()
            val intent = Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:$packageName"))
            runCatching { startActivityForResult(intent, REQUEST_OVERLAY) }
                .onFailure { proceedToConsent() }
            return@runOnUiThread
        }
        proceedToConsent()
    }

    /** 알림 권한을 받아 둔 뒤(캡처 뒤 '눌러서 확인' 알림이 보이도록) 화면 캡처 동의를 띄운다 */
    private fun proceedToConsent() {
        val needsNotify = Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        if (needsNotify) requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), REQUEST_NOTIFY_CAPTURE)
        else launchCaptureConsent()
    }

    /** 화면 캡처 동의 창을 띄운다. 동의하면 onActivityResult에서 서비스가 뜨고 대상 페이지가 열린다 */
    private fun launchCaptureConsent() {
        val mpm = getSystemService(MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        runCatching { startActivityForResult(mpm.createScreenCaptureIntent(), REQUEST_CAPTURE) }
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == REQUEST_NOTIFY && pendingSimulate) {
            pendingSimulate = false
            if (grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED) postSimulated()
        }
        // 알림 권한 결과와 무관하게 캡처는 진행한다 (허용되면 "눌러서 확인" 알림이 보인다)
        if (requestCode == REQUEST_NOTIFY_CAPTURE) launchCaptureConsent()
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

        /**
         * 구글플레이 구독 화면을 자동으로 읽기 시작한다. (화면 하나짜리 큐)
         */
        @JavascriptInterface
        fun startStoreCapture() = beginCapture("""[{"id":"","url":"$PLAY_SUBS_URL","name":"구글플레이 정기결제"}]""")

        /**
         * 여러 화면([{id,url}]의 JSON)을 한 번의 동의로 차례로 열어 읽는다.
         * OTT 하나만 읽을 때도 원소 하나짜리 배열로 부른다.
         */
        @JavascriptInterface
        fun startCaptureSequence(queueJson: String) = beginCapture(queueJson)

        @JavascriptInterface
        fun takePendingOcrText(): String = StoreStore.takePendingOcr(this@MainActivity)

        /** 마지막 캡처 결과("read"/"empty"/""). 홈이 결과 안내를 정확히 하도록 꺼내 쓴다 */
        @JavascriptInterface
        fun takeCaptureStatus(): String = StoreStore.takeCaptureStatus(this@MainActivity)

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
        private const val REQUEST_NOTIFY_CAPTURE = 3
        private const val REQUEST_OVERLAY = 4
        private const val PLAY_SUBS_URL = "https://play.google.com/store/account/subscriptions"
    }
}
