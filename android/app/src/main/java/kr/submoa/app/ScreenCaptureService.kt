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
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.SystemClock
import android.provider.Settings
import android.util.DisplayMetrics
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.view.WindowManager
import android.widget.LinearLayout
import android.widget.TextView
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.text.TextRecognition
import com.google.mlkit.vision.text.korean.KoreanTextRecognizerOptions
import org.json.JSONArray

/**
 * 화면 캡처로 구독 화면을 읽는다 (MediaProjection).
 *
 * 한 번의 화면 캡처 동의로 여러 서비스를 차례로 읽는다. 대상마다 방식이 다르다(CaptureApps):
 *   AUTO    구글플레이 정기결제처럼 열면 바로 구독 목록인 화면 → 몇 초 뒤 자동으로 한 장 읽는다
 *   GUIDED  서비스 앱(로그인돼 있는 곳)을 연다 → 사용자가 이용권·구독 화면으로 이동하면, 화면을 몇 초마다
 *           살펴보다 "다음 결제/결제 예정 + 금액"이 보이는 순간 읽고 넘어간다. "읽기"로 바로 읽을 수도 있다.
 *
 * 떠 있는 작은 안내창(오버레이)이 진행 상황과 버튼을 보여 주고, 동시에 "보이는 창"이 되어 안드로이드가
 * 앱의 자동 화면 전환을 허용하게 한다. 캡처하는 순간에는 화면을 가리지 않도록 잠깐 숨긴다.
 * 읽은 글자는 어느 서비스였는지(id)와 함께 StoreStore에 쌓고, 웹이 해석한다.
 */
class ScreenCaptureService : Service() {
    private var projection: MediaProjection? = null
    private var resultCode = 0
    private var data: Intent? = null
    private var reader: ImageReader? = null
    private var display: VirtualDisplay? = null
    private val main = Handler(Looper.getMainLooper())

    private data class Target(val id: String, val url: String, val name: String)

    /** 캡처 한 장의 결과 */
    private sealed class Shot {
        data class Text(val text: String) : Shot()
        /** 글자를 못 읽었다(빈 화면·인식 실패) */
        object Empty : Shot()
        /** 화면이 새까맣다 — 그 앱이 화면 캡처를 막아 두었다(FLAG_SECURE) */
        object Blocked : Shot()
    }

    private var queue: List<Target> = emptyList()
    private var index = 0
    private var mode = CaptureApps.Mode.AUTO
    /** 단계가 바뀔 때마다 올린다 — 늦게 도착한 이전 단계의 캡처 결과를 버리기 위해서 */
    private var gen = 0
    private var busy = false
    private var gotAny = false
    private var finished = false
    private var guidedDeadline = 0L
    private var captureTimeout: Runnable? = null

    /**
     * 화면 미러는 세션 내내 하나만 쓴다. 안드로이드 14부터 한 번의 캡처 동의로는 가상 화면을
     * 한 번만 만들 수 있어서, 매번 새로 만들면 두 번째 캡처부터 실패한다. 대신 미러를 켜 두고
     * 가장 최근 장면(heldImage)을 들고 있다가, 읽을 때 그 장면을 쓴다.
     */
    private var heldImage: android.media.Image? = null
    private var frameWaiter: (() -> Unit)? = null
    private var mirrorMetrics: Metrics? = null

    /** 마지막으로 받아들인 화면 — 앱 전환이 막혀 같은 화면을 다음 서비스로 잘못 읽는 걸 막는다 */
    private var lastAcceptedText: String? = null
    private var blackStreak = 0

    private var panel: LinearLayout? = null
    private var titleView: TextView? = null
    private var hintView: TextView? = null

    private val autoRunnable = Runnable { autoCapture() }
    private val probeRunnable = Runnable { probe() }
    private val readNowRunnable = Runnable { readNow() }

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
                showPanel()
                // 미러를 바로 켜 둔다 — 첫 캡처 때 준비를 기다리지 않도록(실패해도 캡처 때 다시 시도한다)
                ensureMirror()
                // 첫 화면은 액티비티가 이미 열었다
                if (queue.isEmpty()) finishToApp(false) else enterStep()
            }
            ACTION_CAPTURE -> readNow()
            ACTION_SKIP -> skip()
            ACTION_STOP -> stopByUser()
        }
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        removePanel()
        super.onDestroy()
    }

    private fun parseQueue(json: String?): List<Target> {
        if (json.isNullOrBlank()) return emptyList()
        val arr = runCatching { JSONArray(json) }.getOrNull() ?: return emptyList()
        val out = ArrayList<Target>(arr.length())
        for (i in 0 until arr.length()) {
            val o = arr.optJSONObject(i) ?: continue
            val url = o.optString("url")
            if (url.isNotBlank()) out.add(Target(o.optString("id"), url, o.optString("name")))
        }
        return out
    }

    // ── 단계 진행 ─────────────────────────────────────────────────────────

    /** 지금 대상(이미 열려 있다)을 어떻게 읽을지 정하고 시작한다 */
    private fun enterStep() {
        val t = queue.getOrNull(index) ?: return finishToApp(gotAny)
        mode = CaptureApps.modeFor(this, t.id, t.url)
        blackStreak = 0
        renderPanel(t)
        when (mode) {
            CaptureApps.Mode.SKIP -> {
                val g = gen
                main.post { if (g == gen) advance(false) }
            }
            CaptureApps.Mode.AUTO -> main.postDelayed(autoRunnable, AUTO_CAPTURE_DELAY_MS)
            CaptureApps.Mode.GUIDED -> {
                guidedDeadline = SystemClock.uptimeMillis() + GUIDED_TIMEOUT_MS
                main.postDelayed(probeRunnable, FIRST_PROBE_DELAY_MS)
            }
        }
    }

    /** 다음 대상을 열고 시작한다. 더 없으면 앱으로 돌아간다 */
    private fun advance(got: Boolean) {
        if (finished) return
        gen++
        main.removeCallbacks(autoRunnable)
        main.removeCallbacks(probeRunnable)
        main.removeCallbacks(readNowRunnable)
        if (got) gotAny = true
        index++
        val next = queue.getOrNull(index) ?: return finishToApp(gotAny)
        // 다음 앱을 여는 순간 안내창이 보여야 안드로이드가 전환을 허용한다
        setPanelVisible(true)
        CaptureApps.open(this, next.id, next.url, newTask = true)
        enterStep()
    }

    /** 받아들인 화면을 쌓고 다음으로 */
    private fun accept(t: Target, text: String, trusted: Boolean) {
        StoreStore.appendPendingOcr(this, t.id, text, trusted)
        lastAcceptedText = text
        advance(true)
    }

    /** AUTO: 화면이 뜰 시간을 준 뒤 한 장 읽고 넘어간다 */
    private fun autoCapture() {
        val t = queue.getOrNull(index) ?: return
        val started = captureOnce { shot ->
            // 이전 서비스 화면 그대로면(전환이 막힘) 이 서비스 것으로 쌓지 않는다
            if (shot is Shot.Text && !sameScreen(shot.text, lastAcceptedText)) accept(t, shot.text, trusted = false)
            else advance(false)
        }
        if (!started) main.postDelayed(autoRunnable, RETRY_MS)
    }

    /** GUIDED: 몇 초마다 화면을 살펴, 구독 상태 화면(다음 결제 + 금액)이 보이면 읽고 넘어간다 */
    private fun probe() {
        val t = queue.getOrNull(index) ?: return
        if (SystemClock.uptimeMillis() > guidedDeadline) return advance(false)
        val started = captureOnce { shot ->
            when {
                shot is Shot.Text && SubscriptionSignal.looksLikeSubscription(shot.text) &&
                    !sameScreen(shot.text, lastAcceptedText) -> accept(t, shot.text, trusted = true)
                shot is Shot.Blocked && ++blackStreak >= BLOCKED_STREAK -> skipBlocked()
                else -> {
                    if (shot !is Shot.Blocked) blackStreak = 0
                    main.postDelayed(probeRunnable, PROBE_INTERVAL_MS)
                }
            }
        }
        if (!started) main.postDelayed(probeRunnable, RETRY_MS)
    }

    /** 그 앱이 화면 캡처를 막아 두었다 — 잠깐 알리고 건너뛴다 */
    private fun skipBlocked() {
        hintView?.text = "이 앱은 화면 캡처를 막아 두었어요. 건너뜁니다"
        val g = gen
        main.postDelayed({ if (g == gen) advance(false) }, 1500)
    }

    /** "읽기": 기다리지 않고 지금 화면을 읽고 넘어간다(사용자가 직접 확인했으니 같은 화면 검사는 하지 않는다) */
    private fun readNow() {
        if (finished) return
        val t = queue.getOrNull(index) ?: return
        main.removeCallbacks(autoRunnable)
        main.removeCallbacks(probeRunnable)
        if (busy) {
            // 살펴보던 캡처는 버리고, 끝나는 대로 다시 읽는다
            gen++
            main.postDelayed(readNowRunnable, RETRY_MS)
            return
        }
        val trusted = mode == CaptureApps.Mode.GUIDED
        captureOnce { shot ->
            when (shot) {
                is Shot.Text -> accept(t, shot.text, trusted)
                Shot.Blocked -> skipBlocked()
                Shot.Empty -> advance(false)
            }
        }
    }

    private fun skip() {
        if (!finished) advance(false)
    }

    /** "그만": 읽은 게 있으면 그걸로 돌아가고, 없으면 조용히 앱으로 돌아간다 */
    private fun stopByUser() {
        if (finished) return
        if (gotAny) return finishToApp(true)
        finished = true
        gen++
        runCatching { startActivity(openAppIntent()) }
        stop()
    }

    // ── 캡처 한 장 ────────────────────────────────────────────────────────

    /** 지금 화면을 한 장 읽는다. 이미 읽는 중이면 false */
    private fun captureOnce(onShot: (Shot) -> Unit): Boolean {
        if (busy || finished) return false
        busy = true
        val myGen = gen
        var settled = false
        val settle: (Shot) -> Unit = { shot ->
            if (!settled) {
                settled = true
                busy = false
                frameWaiter = null
                captureTimeout?.let { main.removeCallbacks(it) }
                setPanelVisible(true)
                if (myGen == gen && !finished) onShot(shot)
            }
        }
        val timeout = Runnable { settle(Shot.Empty) }
        captureTimeout = timeout
        main.postDelayed(timeout, CAPTURE_TIMEOUT_MS)

        // 안내창이 구독 화면을 가리지 않게 잠깐 숨긴 뒤(숨긴 장면이 미러에 들어올 시간을 주고) 읽는다
        setPanelVisible(false)
        main.postDelayed({
            if (settled) return@postDelayed
            if (!ensureMirror()) return@postDelayed settle(Shot.Empty)
            val take = {
                val img = heldImage
                val m = mirrorMetrics
                val bitmap = if (img != null && m != null) runCatching { toBitmap(img, m.width) }.getOrNull() else null
                setPanelVisible(true) // 장면은 잡았다 — 글자 인식 동안 안내창을 다시 보인다
                when {
                    bitmap == null -> settle(Shot.Empty)
                    isMostlyBlack(bitmap) -> settle(Shot.Blocked)
                    else -> recognize(bitmap, settle)
                }
            }
            if (heldImage != null) take() else frameWaiter = take // 첫 장면이 올 때까지 기다린다
        }, HIDE_SETTLE_MS)
        return true
    }

    /** 미러(가상 화면)를 한 번만 만들고, 들어오는 장면 중 가장 최근 것을 들고 있는다 */
    private fun ensureMirror(): Boolean {
        if (display != null) return true
        val d = data ?: return false
        val mpm = getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        val proj = projection ?: runCatching {
            mpm.getMediaProjection(resultCode, d).also {
                projection = it
                // 사용자가 상단바에서 화면 공유를 끄면 여기로 온다
                it.registerCallback(object : MediaProjection.Callback() {
                    override fun onStop() {
                        main.post { if (!finished) stopByUser() }
                    }
                }, main)
            }
        }.getOrNull() ?: return false

        val m = screenMetrics()
        mirrorMetrics = m
        val r = ImageReader.newInstance(m.width, m.height, PixelFormat.RGBA_8888, 3)
        r.setOnImageAvailableListener({ ir ->
            val img = runCatching { ir.acquireLatestImage() }.getOrNull() ?: return@setOnImageAvailableListener
            heldImage?.close()
            heldImage = img
            frameWaiter?.let { w ->
                frameWaiter = null
                w()
            }
        }, main)
        reader = r
        display = runCatching {
            proj.createVirtualDisplay(
                "submoa-capture",
                m.width,
                m.height,
                m.density,
                DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
                r.surface,
                null,
                main,
            )
        }.getOrNull()
        if (display == null) {
            runCatching { r.close() }
            reader = null
            return false
        }
        return true
    }

    private fun recognize(bitmap: Bitmap, settle: (Shot) -> Unit) {
        TextRecognition.getClient(KoreanTextRecognizerOptions.Builder().build())
            .process(InputImage.fromBitmap(bitmap, 0))
            .addOnSuccessListener { result ->
                val text = cleanText(result.text)
                settle(if (text.isNotBlank()) Shot.Text(text) else Shot.Empty)
            }
            .addOnFailureListener { settle(Shot.Empty) }
    }

    /**
     * 화면 캡처를 막은 앱(FLAG_SECURE)인가 — 그런 창은 **완전히 새까맣게(글자 한 점 없이)** 찍힌다.
     * 티빙·넷플릭스처럼 배경이 검은 앱도 글자·포스터는 있으므로, 가운데 영역을 촘촘히 훑다가
     * 검지 않은 점이 하나라도 나오면 바로 "막힌 게 아니다"로 본다(위아래 상태바·탭바는 뺀다).
     */
    private fun isMostlyBlack(bmp: Bitmap): Boolean {
        val top = bmp.height / 8
        val bottom = bmp.height - bmp.height / 8
        val row = IntArray(bmp.width)
        var y = top
        while (y < bottom) {
            bmp.getPixels(row, 0, bmp.width, 0, y, bmp.width, 1)
            var x = 0
            while (x < bmp.width) {
                val p = row[x]
                if (maxOf(Color.red(p), Color.green(p), Color.blue(p)) > 8) return false
                x += 8
            }
            y += 4
        }
        return true
    }

    /** 두 화면이 사실상 같은가(줄 대부분이 겹친다) — 앱 전환이 막혀 화면이 그대로인 경우를 잡는다 */
    private fun sameScreen(a: String, b: String?): Boolean {
        if (b == null) return false
        val la = a.lines().map { it.trim() }.filter { it.isNotEmpty() }.toSet()
        val lb = b.lines().map { it.trim() }.filter { it.isNotEmpty() }.toSet()
        if (la.isEmpty() || lb.isEmpty()) return false
        return la.intersect(lb).size * 10 >= minOf(la.size, lb.size) * 8
    }

    /** 우리 안내창·알림 문구가 섞여 들어왔으면 뺀다(안내창 제목 "넷플릭스 (2/5)", 버튼 글자 포함) */
    private fun cleanText(text: String): String =
        text.lines().filterNot { line ->
            val l = line.trim()
            l.isEmpty() || OWN_TEXT.any { l.contains(it) } || PANEL_TITLE.matches(l) || l in PANEL_LABELS
        }.joinToString("\n")

    /** 미러를 끈다 — 세션이 끝날 때만 */
    private fun releaseCapture() {
        frameWaiter = null
        runCatching { heldImage?.close() }
        heldImage = null
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
        // 같은 장면을 여러 번 읽을 수 있다(화면이 그대로면 새 장면이 안 온다) — 매번 처음부터 읽는다
        val buffer = plane.buffer
        buffer.rewind()
        bmp.copyPixelsFromBuffer(buffer)
        return if (rowPadding == 0) bmp else Bitmap.createBitmap(bmp, 0, 0, width, image.height)
    }

    // ── 떠 있는 안내창 ────────────────────────────────────────────────────

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    /**
     * 진행 상황과 버튼(읽기·건너뛰기·그만)을 보여 주는 작은 창. 화면 위쪽 가운데에 좁게 띄워
     * 앱의 뒤로가기·메뉴 버튼(양옆)과 아래 탭바를 가리지 않는다. '다른 앱 위에 표시'가 꺼져 있으면
     * 띄우지 않는다(그때는 알림의 버튼과 자동 감지로 진행한다).
     */
    private fun showPanel() {
        if (panel != null || !Settings.canDrawOverlays(this)) return
        val maxText = resources.displayMetrics.widthPixels - dp(2 * 64) - dp(28)
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(14), dp(10), dp(14), dp(10))
            background = GradientDrawable().apply {
                cornerRadius = dp(14).toFloat()
                setColor(Color.parseColor("#F20B1220"))
                setStroke(dp(1), Color.parseColor("#5538BDF8"))
            }
        }
        val title = TextView(this).apply {
            setTextColor(Color.WHITE)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 14f)
            setTypeface(typeface, Typeface.BOLD)
            maxWidth = maxText
        }
        val hint = TextView(this).apply {
            setTextColor(Color.parseColor("#CBD5E1"))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 12f)
            setPadding(0, dp(2), 0, 0)
            maxWidth = maxText
        }
        val row = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setPadding(0, dp(8), 0, 0)
            addView(panelButton(LABEL_READ, primary = true) { readNow() })
            addView(panelButton(LABEL_SKIP, primary = false) { skip() })
            addView(panelButton(LABEL_STOP, primary = false) { stopByUser() })
        }
        root.addView(title)
        root.addView(hint)
        root.addView(row)
        val lp = WindowManager.LayoutParams(
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,
            PixelFormat.TRANSLUCENT,
        ).apply {
            gravity = Gravity.TOP or Gravity.CENTER_HORIZONTAL
            y = dp(36)
        }
        runCatching { (getSystemService(WINDOW_SERVICE) as WindowManager).addView(root, lp) }
            .onSuccess {
                panel = root
                titleView = title
                hintView = hint
            }
    }

    private fun panelButton(label: String, primary: Boolean, onClick: () -> Unit) = TextView(this).apply {
        text = label
        gravity = Gravity.CENTER
        setTextSize(TypedValue.COMPLEX_UNIT_SP, 13f)
        setTextColor(if (primary) Color.parseColor("#082F49") else Color.WHITE)
        setPadding(dp(14), dp(7), dp(14), dp(7))
        background = GradientDrawable().apply {
            cornerRadius = dp(10).toFloat()
            setColor(if (primary) Color.parseColor("#38BDF8") else Color.parseColor("#33FFFFFF"))
        }
        layoutParams = LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.WRAP_CONTENT,
            LinearLayout.LayoutParams.WRAP_CONTENT,
        ).apply { marginEnd = dp(6) }
        setOnClickListener { onClick() }
    }

    private fun renderPanel(t: Target) {
        val total = queue.size
        val name = t.name.ifBlank { "구독 화면" }
        titleView?.text = if (total > 1) "$name (${index + 1}/$total)" else name
        hintView?.text = when (mode) {
            CaptureApps.Mode.AUTO -> "화면이 뜨면 자동으로 읽어요"
            CaptureApps.Mode.GUIDED -> "${CaptureApps.hintFor(t.id)}\n보이면 자동으로 읽어요. 안 되면 '$LABEL_READ'"
            CaptureApps.Mode.SKIP -> "이 폰에 앱이 없어 건너뜁니다"
        }
    }

    private fun setPanelVisible(visible: Boolean) {
        panel?.visibility = if (visible) View.VISIBLE else View.INVISIBLE
    }

    private fun removePanel() {
        val view = panel ?: return
        panel = null
        titleView = null
        hintView = null
        runCatching { (getSystemService(WINDOW_SERVICE) as WindowManager).removeView(view) }
    }

    // ── 끝내기 ───────────────────────────────────────────────────────────

    /**
     * 결과를 가지고 앱 홈으로 돌아간다. 홈이 OCR 글자를 꺼내 해석한다.
     * 자동 전환은 기기에 따라 막힐 수 있어, 눌러서 돌아올 수 있는 결과 알림도 함께 띄운다.
     */
    private fun finishToApp(gotText: Boolean) {
        if (finished) return
        finished = true
        gen++
        main.removeCallbacks(autoRunnable)
        main.removeCallbacks(probeRunnable)
        main.removeCallbacks(readNowRunnable)
        // 홈이 돌아왔을 때 결과를 정확히 안내하도록 상태를 남긴다
        StoreStore.saveCaptureStatus(this, if (gotText) "read" else "empty")
        postResultNotification(gotText)
        setPanelVisible(true)
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
        main.removeCallbacks(autoRunnable)
        main.removeCallbacks(probeRunnable)
        main.removeCallbacks(readNowRunnable)
        captureTimeout?.let { main.removeCallbacks(it) }
        removePanel()
        releaseCapture()
        runCatching { projection?.stop() }
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

    /**
     * 진행 중 알림. 화면 위로 튀어나오면(헤드업) 읽을 화면을 가리므로 조용한(LOW) 채널을 쓴다.
     * 채널 중요도는 한 번 만들면 바꿀 수 없어 새 채널 id를 쓴다.
     */
    private fun buildNotification(): Notification {
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(
            NotificationChannel(CHANNEL_ID, "구독 화면 읽는 중", NotificationManager.IMPORTANCE_LOW),
        )
        val open = PendingIntent.getActivity(this, 1, openAppIntent(), PendingIntent.FLAG_IMMUTABLE)
        return Notification.Builder(this, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_menu_camera)
            .setContentTitle("구독 화면을 읽는 중…")
            .setContentText("구독(이용권) 화면이 보이면 자동으로 읽어요")
            .setContentIntent(open)
            .addAction(Notification.Action.Builder(null, LABEL_READ, action(ACTION_CAPTURE)).build())
            .addAction(Notification.Action.Builder(null, LABEL_SKIP, action(ACTION_SKIP)).build())
            .addAction(Notification.Action.Builder(null, LABEL_STOP, action(ACTION_STOP)).build())
            .setOngoing(true)
            .build()
    }

    companion object {
        private const val CHANNEL_ID = "capture-progress"
        private const val RESULT_CHANNEL_ID = "screen-capture-result"
        private const val NOTIF_ID = 42
        private const val RESULT_NOTIF_ID = 43
        const val ACTION_START = "kr.submoa.app.CAPTURE_START"
        const val ACTION_CAPTURE = "kr.submoa.app.CAPTURE_NOW"
        const val ACTION_SKIP = "kr.submoa.app.CAPTURE_SKIP"
        const val ACTION_STOP = "kr.submoa.app.CAPTURE_STOP"
        const val EXTRA_CODE = "code"
        const val EXTRA_DATA = "data"
        const val EXTRA_QUEUE = "queue"

        private const val LABEL_READ = "읽기"
        private const val LABEL_SKIP = "건너뛰기"
        private const val LABEL_STOP = "그만"

        private const val AUTO_CAPTURE_DELAY_MS = 4000L
        private const val FIRST_PROBE_DELAY_MS = 3000L
        private const val PROBE_INTERVAL_MS = 2500L
        private const val GUIDED_TIMEOUT_MS = 90_000L
        private const val CAPTURE_TIMEOUT_MS = 6000L
        private const val HIDE_SETTLE_MS = 250L
        private const val RETRY_MS = 300L
        /** 연달아 이만큼 검은 화면이면 캡처를 막은 앱으로 보고 건너뛴다(앱이 뜨는 중 잠깐 검은 것과 구분) */
        private const val BLOCKED_STREAK = 3

        /** 캡처에 섞여 들어올 수 있는 우리 문구 — 해석 전에 뺀다 */
        private val OWN_TEXT = listOf("구독 화면을 읽는 중", "구독모아", "자동으로 읽어요", "화면을 열어 주세요", "화면 캡처를 막아")
        private val PANEL_TITLE = Regex(".*\\(\\d+/\\d+\\)$")
        private val PANEL_LABELS = setOf(LABEL_READ, LABEL_SKIP, LABEL_STOP, "$LABEL_READ $LABEL_SKIP $LABEL_STOP")

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
