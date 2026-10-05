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
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.util.DisplayMetrics
import android.view.WindowManager
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.text.TextRecognition
import com.google.mlkit.vision.text.korean.KoreanTextRecognizerOptions

/**
 * 화면 캡처로 스토어 구독 화면을 읽는다 (MediaProjection).
 *
 * 사용자가 화면 캡처를 1회 동의하면, 스토어 구독 화면이 보일 때 알림의 "화면 읽기"를 눌러
 * 그 순간 화면을 한 장 잡아 ML Kit로 글자를 뽑는다. 접근성 매크로가 아니라 화면 녹화 앱이 쓰는
 * 공식 API다. 잡은 글자는 StoreStore에 넣고, 웹이 parseStoreScreenshot으로 해석한다.
 */
class ScreenCaptureService : Service() {
    private var projection: MediaProjection? = null
    private var resultCode = 0
    private var data: Intent? = null
    private var captured = false
    private var finished = false
    private var reader: ImageReader? = null
    private var display: VirtualDisplay? = null
    private val main = Handler(Looper.getMainLooper())
    private val giveUp = Runnable { finishToApp(false) }

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
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                    startForeground(NOTIF_ID, buildNotification(), ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION)
                } else {
                    startForeground(NOTIF_ID, buildNotification())
                }
                // 스토어 화면이 뜰 시간을 준 뒤 알아서 한 장 읽는다. 버튼을 찾을 필요가 없다.
                main.postDelayed({ capture() }, AUTO_CAPTURE_DELAY_MS)
            }
            ACTION_CAPTURE -> { main.removeCallbacks(giveUp); releaseCapture(); captured = false; capture() }
            ACTION_STOP -> stop()
        }
        return START_NOT_STICKY
    }

    private fun capture() {
        if (captured) return
        captured = true
        // 프레임이나 OCR이 끝내 오지 않아도 사용자가 흰 화면에 갇히지 않게, 일정 시간 뒤 앱으로 돌려보낸다.
        main.postDelayed(giveUp, CAPTURE_TIMEOUT_MS)
        val mpm = getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        val d = data ?: return finishToApp(false)
        val proj = projection ?: runCatching {
            mpm.getMediaProjection(resultCode, d).also {
                projection = it
                it.registerCallback(object : MediaProjection.Callback() {}, main)
            }
        }.getOrNull() ?: return finishToApp(false)

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
        }.getOrNull() ?: return finishToApp(false)

        reader!!.setOnImageAvailableListener({ r ->
            val image = r.acquireLatestImage() ?: return@setOnImageAvailableListener
            val bitmap = runCatching { toBitmap(image, metrics.width) }.getOrNull()
            image.close()
            r.setOnImageAvailableListener(null, null)
            releaseCapture()
            if (bitmap == null) return@setOnImageAvailableListener finishToApp(false)
            recognize(bitmap)
        }, main)
    }

    private fun releaseCapture() {
        runCatching { display?.release() }
        display = null
        runCatching { reader?.close() }
        reader = null
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

    private fun recognize(bitmap: Bitmap) {
        TextRecognition.getClient(KoreanTextRecognizerOptions.Builder().build())
            .process(InputImage.fromBitmap(bitmap, 0))
            .addOnSuccessListener { result ->
                val text = result.text
                if (text.isNotBlank()) StoreStore.savePendingOcr(this, text)
                finishToApp(text.isNotBlank())
            }
            .addOnFailureListener { finishToApp(false) }
    }

    /**
     * 결과를 가지고 앱 홈으로 돌아간다. 홈이 OCR 글자를 꺼내 해석한다.
     * 자동 전환은 기기에 따라 막힐 수 있어, 눌러서 돌아올 수 있는 결과 알림도 함께 띄운다.
     */
    private fun finishToApp(gotText: Boolean) {
        if (finished) return
        finished = true
        main.removeCallbacks(giveUp)
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
        main.removeCallbacks(giveUp)
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
        private const val AUTO_CAPTURE_DELAY_MS = 3500L
        private const val CAPTURE_TIMEOUT_MS = 6000L

        fun start(context: Context, resultCode: Int, data: Intent) {
            val intent = Intent(context, ScreenCaptureService::class.java)
                .setAction(ACTION_START)
                .putExtra(EXTRA_CODE, resultCode)
                .putExtra(EXTRA_DATA, data)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) context.startForegroundService(intent)
            else context.startService(intent)
        }
    }
}
