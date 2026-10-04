package kr.submoa.app

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/**
 * 카드 결제 알림을 앱 내부 저장소에만 쌓는다. 서버로 보내지 않는다.
 *
 * 카톡은 새 메시지가 올 때마다 같은 채팅방 알림을 갱신하며 이전 메시지까지 다시 싣는다.
 * 그래서 (수신 시각, 본문)으로 중복을 거른다.
 */
class AlertStore private constructor(private val file: File) {
    private val seen = HashSet<String>()
    private val alerts = ArrayList<Pair<String, Long>>()

    init {
        if (file.exists()) {
            file.forEachLine { line ->
                runCatching { JSONObject(line) }.getOrNull()?.let {
                    remember(it.getString("body"), it.getLong("postedAt"))
                }
            }
        }
    }

    private fun key(body: String, postedAt: Long) = "$postedAt|$body"

    private fun remember(body: String, postedAt: Long): Boolean {
        if (!seen.add(key(body, postedAt))) return false
        alerts.add(body to postedAt)
        return true
    }

    @Synchronized
    fun add(body: String, postedAt: Long) {
        if (!remember(body, postedAt)) return
        val line = JSONObject().put("body", body).put("postedAt", postedAt).toString()
        file.appendText(line + "\n")
        if (alerts.size > MAX_ALERTS) compact()
    }

    /** 오래된 것부터 버린다. 판정에는 최근 1~2년이면 충분하다 */
    private fun compact() {
        val keep = alerts.takeLast(MAX_ALERTS / 2)
        alerts.clear()
        seen.clear()
        file.writeText("")
        keep.forEach { (body, postedAt) -> add(body, postedAt) }
    }

    /** 웹에 넘길 JSON: [{"body": "...", "postedAt": 1696300000000}, ...] */
    @Synchronized
    fun toJson(): String {
        val array = JSONArray()
        alerts.forEach { (body, postedAt) ->
            array.put(JSONObject().put("body", body).put("postedAt", postedAt))
        }
        return array.toString()
    }

    companion object {
        private const val MAX_ALERTS = 5000

        @Volatile
        private var instance: AlertStore? = null

        fun get(context: Context): AlertStore =
            instance ?: synchronized(this) {
                instance ?: AlertStore(File(context.applicationContext.filesDir, "card-alerts.jsonl"))
                    .also { instance = it }
            }
    }
}
