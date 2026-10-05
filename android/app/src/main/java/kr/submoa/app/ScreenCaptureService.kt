package kr.submoa.app

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.graphics.Bitmap
import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.ImageReader
import android.graphics.Color
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.net.Uri
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.provider.Settings
import android.util.DisplayMetrics
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.view.WindowManager
import android.widget.TextView
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.text.TextRecognition
import com.google.mlkit.vision.text.korean.KoreanTextRecognizerOptions
import org.json.JSONArray

/**
 * 화면 캡처로 구독 화면을 읽는다 (MediaProjection).
 *
 * 한 번의 화면 캡처 동의로 여러 화면을 차례로 읽는다("주요 OTT 모두 읽기"). 각 대상(서비스 id + 주소)을
 * 순서대로 열고, 화면이 뜰 시간을 준 뒤 한 장씩 잡아 ML Kit로 글자를 뽑는다. 접근성 매크로가 아니라
 * 화면 녹화 앱이 쓰는 공식 API다. 잡은 글자는 어느 서비스였는지(id)와 함께 StoreStore에 쌓고,
 * 웹이 parseStoreScreenshot(targeted)으로 해석한다. 하나짜리 큐면 예전처럼 한 화면만 읽는다.
 */
class ScreenCaptureService : Service() {
    private var projection: MediaProjection? = null
    private var resultCode = 0
    private var data: Intent? = null
    private var reader: ImageReader? = null
    private var display: VirtualDisplay? = null
    private val main = Handler(Looper.getMainLooper())

    private data class Target(val id: String, val url: String)

    private var queue: List<Target> = emptyList()
    private var index = 0
    private var gotAny = false
    private var finished = false
    private var stepDone = false
    private var overlay: TextView? = null

    private val stepRunnable = Runnable { captureCurrent() }
    private val stepTimeout = Runnable { onStep(null) }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START -> {
                resultCode = intent.getIntExtra(EXTRA_CODE, 0)
                data = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                    intent.getParcelableExtra(EXTRA_DATA, Intent::class.java)
                } else {
                    @Suppress("DEPRECATION") intent.getParcelableExtra(EXTRA_DATA)
                }
                queue = parseQueue(intent.getStringExtra(EXTRA_QUEUE))
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                    startForeground(NOTIF_ID, buildNotification(), ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION)
                } else {
                    startForeground(NOTIF_ID, buildNotification())
                }
                // 오버레이(떠 있는 작은 안내창)가 있어야 안드로이드가 앱의 자동 화면 전환을 허용한다.
                showOverlay()
                // 첫 화면은 액티비티가 이미 열었다. 뜰 시간을 준 뒤 순서대로 읽어 나간다.
                if (queue.isEmpty()) finishToApp(false) else scheduleStep()
            }
            // 알림의 "지금 읽기": 기다리지 않고 지금 한 장 잡는다
            ACTION_CAPTURE -> { main.removeCallbacks(stepRunnable); main.removeCallbacks(stepTimeout); captureCurrent() }
            ACTION_STOP -> stop()
        }
        return START_NOT_STICKY
    }

    private fun parseQueue(json: String?): List<Target> {
        if (json.isNullOrBlank()) return emptyList()
        val arr = runCatching { JSONArray(json) }.getOrNull() ?: return emptyList()
        val out = ArrayList<Target>(arr.length())
        for (i in 0 until arr.length()) {
            val o = arr.optJSONObject(i) ?: continue
            val url = o.optString("url")
            if (url.isNotBlank()) out.add(Target(o.optString("id"), url))
        }
        return out
    }

    private fun scheduleStep() {
        main.removeCallbacks(stepRunnable)
        main.postDelayed(stepRunnable, AUTO_CAPTURE_DELAY_MS)
    }

    /** 지금 화면을 한 장 잡는다. 프레임이 오거나(또는 못 오면 시간초과) onStep으로 모인다. */
    private fun captureCurrent() {
        stepDone = false
        updateOverlay()
        main.postDelayed(stepTimeout, STEP_TIMEOUT_MS)
        val mpm = getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        val d = data ?: return onStep(null)
        val proj = projection ?: runCatching {
            mpm.getMediaProjection(resultCode, d).also {
                projection = it
                it.registerCallback(object : MediaProjection.Callback() {}, main)
            }
        }.getOrNull() ?: return onStep(null)

        val metrics = screenMetrics()
        reader = ImageReader.newInstance(metrics.width, metrics.height, PixelFormat.RGBA_8888, 2)
        display = runCatching {
            proj.createVirtualDisplay(
                "submoa-capture",
                metrics.width,
                metrics.height,
                metrics.density,
                DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
                reader!!.surface,
                null,
                main,
            )
        }.getOrNull() ?: return onStep(null)

        reader!!.setOnImageAvailableListener({ r ->
            val image = r.acquireLatestImage() ?: return@setOnImageAvailableListener
            val bitmap = runCatching { toBitmap(image, metrics.width) }.getOrNull()
            image.close()
            r.setOnImageAvailableListener(null, null)
            onStep(bitmap)
        }, main)
    }

    /** 이번 화면 한 장이 끝났다(프레임/실패/시간초과 중 한 번만). 글자를 뽑고 다음으로 넘어간다. */
    private fun onStep(bitmap: Bitmap?) {
        if (stepDone) return
        stepDone = true
        main.removeCallbacks(stepTimeout)
        releaseCapture()
        if (bitmap == null) return advance(false)
        recognize(bitmap) { got -> advance(got) }
    }

    private fun recognize(bitmap: Bitmap, done: (Boolean) -> Unit) {
        val id = queue.getOrNull(index)?.id ?: ""
        TextRecognition.getClient(KoreanTextRecognizerOptions.Builder().build())
            .process(InputImage.fromBitmap(bitmap, 0))
            .addOnSuccessListener { result ->
                val text = result.text
                if (text.isNotBlank()) StoreStore.appendPendingOcr(this, id, text)
                done(text.isNotBlank())
            }
            .addOnFailureListener { done(false) }
    }

    /** 다음 대상으로. 더 없으면 앱으로 돌아간다. */
    private fun advance(got: Boolean) {
        if (got) gotAny = true
        index++
        val next = queue.getOrNull(index)
        if (next != null) {
            openTarget(next)
            scheduleStep()
        } else {
            finishToApp(gotAny)
        }
    }

    /** 다음 서비스 화면을 연다. 플레이 구독 주소는 플레이 스토어 앱으로, 나머지는 기본 처리로. */
    private fun openTarget(t: Target) {
        val url = Uri.parse(t.url)
        if (url.host?.contains("play.google.com") == true) {
            val toPlay = Intent(Intent.ACTION_VIEW, url)
                .setPackage("com.android.vending")
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            if (toPlay.resolveActivity(packageManager) != null) {
                runCatching { startActivity(toPlay) }.onSuccess { return }
            }
        }
        runCatching { startActivity(Intent(Intent.ACTION_VIEW, url).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
    }

    private fun releaseCapture() {
        runCatching { display?.release() }
        display = null
        runCatching { reader?.close() }
        reader = null
    }

    /**
     * 떠 있는 작은 안내창. 사용자에게 진행 상황을 보여 주고, 동시에 "보이는 창"이 되어
     * 안드로이드가 앱의 자동 화면 전환을 허용하게 한다(SYSTEM_ALERT_WINDOW 예외).
     */
    private fun showOverlay() {
        if (overlay != null || !Settings.canDrawOverlays(this)) return
        val pad = (12 * resources.displayMetrics.density).toInt()
        val view = TextView(this).apply {
            setBackgroundColor(Color.parseColor("#E60EA5E9"))
            setTextColor(Color.WHITE)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 13f)
            setPadding(pad, pad / 2, pad, pad / 2)
            text = "구독 화면을 읽는 중…"
        }
        val lp = WindowManager.LayoutParams(
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,
            android.graphics.PixelFormat.TRANSLUCENT,
        ).apply { gravity = Gravity.TOP or Gravity.CENTER_HORIZONTAL; y = (48 * resources.displayMetrics.density).toInt() }
        runCatching { (getSystemService(WINDOW_SERVICE) as WindowManager).addView(view, lp) }
            .onSuccess { overlay = view }
    }

    private fun updateOverlay() {
        val total = queue.size
        val n = (index + 1).coerceAtMost(total)
        overlay?.text = if (total > 1) "구독 화면을 읽는 중… ($n/$total)" else "구독 화면을 읽는 중…"
    }

    private fun removeOverlay() {
        val view = overlay ?: return
        overlay = null
        runCatching { (getSystemService(WINDOW_SERVICE) as WindowManager).removeView(view) }
    }

    private fun toBitmap(image: android.media.Image, width: Int): Bitmap {
        val plane = image.planes[0]
        val pixelStride = plane.pixelStride
        val rowStride = plane.rowStride
        val rowPadding = rowStride - pixelStride * width
        val bmp = Bitmap.createBitmap(width + rowPadding / pixelStride, image.height, Bitmap.Config.ARGB_8888)
        bmp.copyPixelsFromBuffer(plane.buffer)
        return if (rowPadding == 0) bmp else Bitmap.createBitmap(bmp, 0, 0, width, image.height)
    }

    /**
     * 결과를 가지고 앱 홈으로 돌아간다. 홈이 OCR 글자를 꺼내 해석한다.
     * 자동 전환은 기기에 따라 막힐 수 있어, 눌러서 돌아올 수 있는 결과 알림도 함께 띄운다.
     */
    private fun finishToApp(gotText: Boolean) {
        if (finished) return
        finished = true
        main.removeCallbacks(stepRunnable)
        main.removeCallbacks(stepTimeout)
        // 홈이 돌아왔을 때 결과를 정확히 안내하도록 상태를 남긴다
        StoreStore.saveCaptureStatus(this, if (gotText) "read" else "empty")
        postResultNotification(gotText)
        runCatching { startActivity(openAppIntent()) }
        stop()
    }

    private fun openAppIntent(): Intent =
        Intent(this, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_REORDER_TO_FRONT)

    /** FGS 알림(읽는 중)은 지워지지만, 결과 알림은 남아 사용자가 눌러서 결과로 들어올 수 있다 */
    private fun postResultNotification(gotText: Boolean) {
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(
            NotificationChannel(RESULT_CHANNEL_ID, "구독 읽기 결과", NotificationManager.IMPORTANCE_HIGH),
        )
        val open = PendingIntent.getActivity(this, 0, openAppIntent(), PendingIntent.FLAG_IMMUTABLE)
        val title = if (gotText) "구독 화면을 읽었어요" else "화면을 읽지 못했어요"
        val body = if (gotText) "눌러서 구독모아에서 확인하기" else "다시 시도하려면 눌러서 구독모아 열기"
        manager.notify(
            RESULT_NOTIF_ID,
            Notification.Builder(this, RESULT_CHANNEL_ID)
                .setSmallIcon(android.R.drawable.ic_menu_camera)
                .setContentTitle(title)
                .setContentText(body)
                .setContentIntent(open)
                .setAutoCancel(true)
                .build(),
        )
    }

    private fun stop() {
        main.removeCallbacks(stepRunnable)
        main.removeCallbacks(stepTimeout)
        removeOverlay()
        releaseCapture()
        projection?.stop()
        projection = null
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    private data class Metrics(val width: Int, val height: Int, val density: Int)

    private fun screenMetrics(): Metrics {
        val wm = getSystemService(Context.WINDOW_SERVICE) as WindowManager
        val dm = DisplayMetrics()
        @Suppress("DEPRECATION") wm.defaultDisplay.getRealMetrics(dm)
        return Metrics(dm.widthPixels, dm.heightPixels, dm.densityDpi)
    }

    private fun action(name: String): PendingIntent {
        val intent = Intent(this, ScreenCaptureService::class.java).setAction(name)
        return PendingIntent.getService(this, name.hashCode(), intent, PendingIntent.FLAG_IMMUTABLE)
    }

    private fun buildNotification(): Notification {
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(
            NotificationChannel(CHANNEL_ID, "구독 화면 읽기", NotificationManager.IMPORTANCE_HIGH),
        )
        val open = PendingIntent.getActivity(this, 1, openAppIntent(), PendingIntent.FLAG_IMMUTABLE)
        return Notification.Builder(this, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_menu_camera)
            .setContentTitle("구독 화면을 읽는 중…")
            .setContentText("잠시 후 자동으로 읽어요. 스크롤이 필요하면 눌러서 다시 읽기")
            .setContentIntent(open)
            .addAction(Notification.Action.Builder(null, "지금 읽기", action(ACTION_CAPTURE)).build())
            .addAction(Notification.Action.Builder(null, "취소", action(ACTION_STOP)).build())
            .setOngoing(true)
            .build()
    }

    companion object {
        private const val CHANNEL_ID = "screen-capture"
        private const val RESULT_CHANNEL_ID = "screen-capture-result"
        private const val NOTIF_ID = 42
        private const val RESULT_NOTIF_ID = 43
        const val ACTION_START = "kr.submoa.app.CAPTURE_START"
        const val ACTION_CAPTURE = "kr.submoa.app.CAPTURE_NOW"
        const val ACTION_STOP = "kr.submoa.app.CAPTURE_STOP"
        const val EXTRA_CODE = "code"
        const val EXTRA_DATA = "data"
        const val EXTRA_QUEUE = "queue"
        private const val AUTO_CAPTURE_DELAY_MS = 4000L
        private const val STEP_TIMEOUT_MS = 6000L

        fun start(context: Context, resultCode: Int, data: Intent, queueJson: String) {
            val intent = Intent(context, ScreenCaptureService::class.java)
                .setAction(ACTION_START)
                .putExtra(EXTRA_CODE, resultCode)
                .putExtra(EXTRA_DATA, data)
                .putExtra(EXTRA_QUEUE, queueJson)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) context.startForegroundService(intent)
            else context.startService(intent)
        }
    }
}
