package kr.submoa.app

import android.content.Context
import java.io.File

/**
 * 스토어 구독 스크린샷 처리용 저장소.
 *
 *   pendingOcr  스크린샷을 OCR한 글자. 웹이 한 번 꺼내 파싱하면 지운다.
 *   storeSubs   웹이 그 글자에서 뽑은 스토어 구독 [{id, amount, cycle}]의 JSON.
 */
object StoreStore {
    private fun pendingOcr(context: Context) = File(context.filesDir, "pending-ocr.txt")
    private fun storeSubs(context: Context) = File(context.filesDir, "store-subs.json")

    fun savePendingOcr(context: Context, text: String) = pendingOcr(context).writeText(text)

    @Synchronized
    fun takePendingOcr(context: Context): String {
        val f = pendingOcr(context)
        if (!f.exists()) return ""
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
