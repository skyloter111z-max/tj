package kr.submoa.app

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/**
 * 스토어 구독 스크린샷 처리용 저장소.
 *
 *   pendingOcr  읽은 화면들의 글자. [{id, text}]의 JSON 배열로 쌓는다 — "주요 OTT 모두 읽기"는
 *               여러 화면을 차례로 읽으므로, 각 글자에 어느 서비스 화면이었는지(id)를 붙여 둔다.
 *               (일반 플레이·공유 스크린샷은 id가 빈 문자열이다.) 웹이 한 번 꺼내 파싱하면 지운다.
 *   storeSubs   웹이 그 글자에서 뽑은 스토어 구독 [{id, amount, cycle}]의 JSON.
 */
object StoreStore {
    private fun pendingOcr(context: Context) = File(context.filesDir, "pending-ocr.json")
    private fun storeSubs(context: Context) = File(context.filesDir, "store-subs.json")
    private fun captureStatus(context: Context) = File(context.filesDir, "capture-status.txt")

    /** 마지막 캡처 결과: "read"(글자를 읽음) / "empty"(화면은 잡았지만 글자 없음·인식 실패). 웹이 꺼내 안내한다 */
    @Synchronized
    fun saveCaptureStatus(context: Context, status: String) = captureStatus(context).writeText(status)

    @Synchronized
    fun takeCaptureStatus(context: Context): String {
        val f = captureStatus(context)
        if (!f.exists()) return ""
        return f.readText().also { f.delete() }
    }

    /**
     * 읽은 화면 하나를 쌓는다. id는 그 화면이 어느 서비스였는지(없으면 "").
     * trusted: 그 서비스 앱 안에서 읽은 화면이다 — 앱 안 화면엔 서비스 이름이 안 나오는 경우가 많아,
     * 웹이 이름 확인 없이 그 서비스로 해석하도록 표시한다.
     */
    @Synchronized
    fun appendPendingOcr(context: Context, id: String, text: String, trusted: Boolean = false) {
        val f = pendingOcr(context)
        val arr = runCatching { JSONArray(if (f.exists()) f.readText() else "[]") }.getOrDefault(JSONArray())
        arr.put(JSONObject().put("id", id).put("text", text).put("trusted", trusted))
        f.writeText(arr.toString())
    }

    @Synchronized
    fun takePendingOcr(context: Context): String {
        val f = pendingOcr(context)
        if (!f.exists()) return "[]"
        return f.readText().also { f.delete() }
    }

    @Synchronized
    fun saveStoreSubs(context: Context, json: String) = storeSubs(context).writeText(json)

    @Synchronized
    fun storeSubsJson(context: Context): String =
        storeSubs(context).let { if (it.exists()) it.readText() else "[]" }

    @Synchronized
    fun clearStoreSubs(context: Context) {
        storeSubs(context).delete()
    }
}
