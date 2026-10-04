package kr.submoa.app

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/**
 * 카톡 내보내기로 가져온 과거 결제 알림.
 *
 *   pending  공유받은 원본 텍스트. 웹이 한 번 꺼내 가면 바로 지운다 — 잘못 공유한 개인 대화가
 *            기기에 남지 않게 하려는 것이다.
 *   imported 웹이 그 원본에서 골라낸 카드 결제 알림만. [{"body": "...", "receivedAt": "YYYY-MM-DD"}]
 *            카드사 알림방을 여러 개 가져오면 합친다.
 */
object ImportStore {
    private fun pending(context: Context) = File(context.filesDir, "pending-export.txt")
    private fun imported(context: Context) = File(context.filesDir, "imported-alerts.json")

    fun savePending(context: Context, text: String) = pending(context).writeText(text)

    @Synchronized
    fun takePending(context: Context): String {
        val file = pending(context)
        if (!file.exists()) return ""
        return file.readText().also { file.delete() }
    }

    @Synchronized
    fun addImported(context: Context, json: String) {
        val merged = LinkedHashMap<String, JSONObject>()
        for (array in listOf(readArray(imported(context)), runCatching { JSONArray(json) }.getOrNull() ?: JSONArray())) {
            for (i in 0 until array.length()) {
                val o = array.optJSONObject(i) ?: continue
                val body = o.optString("body")
                val receivedAt = o.optString("receivedAt")
                if (body.isEmpty() || receivedAt.isEmpty()) continue
                merged["$receivedAt|$body"] = JSONObject().put("body", body).put("receivedAt", receivedAt)
            }
        }
        imported(context).writeText(JSONArray(merged.values).toString())
    }

    @Synchronized
    fun importedJson(context: Context): String = readArray(imported(context)).toString()

    @Synchronized
    fun clearImported(context: Context) {
        imported(context).delete()
    }

    private fun readArray(file: File): JSONArray =
        if (file.exists()) runCatching { JSONArray(file.readText()) }.getOrNull() ?: JSONArray() else JSONArray()
}
