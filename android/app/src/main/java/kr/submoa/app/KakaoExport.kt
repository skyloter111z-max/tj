package kr.submoa.app

import java.io.ByteArrayInputStream
import java.util.zip.ZipInputStream

/**
 * 카톡 "대화 내용 내보내기"로 공유받은 파일을 글자로 바꾼다.
 *
 * 카톡은 텍스트 파일을 그대로, 또는 zip으로 묶어 보낸다. 어느 쪽이든 텍스트만 꺼낸다.
 * 메시지를 나누고 카드 결제 알림만 고르는 일은 웹(lib/card-alerts/import.ts)이 한다.
 */
object KakaoExport {
    /** 이보다 큰 파일은 받지 않는다 — 몇 년치 카드 알림방도 수 MB를 넘지 않는다 */
    const val MAX_BYTES = 20 * 1024 * 1024

    private val MESSAGE_LINE = Regex("\\d{4}년 \\d{1,2}월 \\d{1,2}일 (오전|오후) \\d{1,2}:\\d{2}, ")
    private val LEGACY_LINE = Regex("\\d{4}\\. \\d{1,2}\\. \\d{1,2}\\. (오전|오후) \\d{1,2}:\\d{2}, ")

    /** 카톡 대화 내보내기 파일처럼 생겼는가. 아니면 받지 않는다 */
    fun looksLikeExport(text: String): Boolean =
        text.contains("카카오톡 대화") || MESSAGE_LINE.containsMatchIn(text) || LEGACY_LINE.containsMatchIn(text)

    fun decode(bytes: ByteArray): String? {
        if (bytes.size > MAX_BYTES) return null
        val isZip = bytes.size > 2 && bytes[0] == 'P'.code.toByte() && bytes[1] == 'K'.code.toByte()
        if (!isZip) return String(bytes, Charsets.UTF_8)
        ZipInputStream(ByteArrayInputStream(bytes)).use { zip ->
            while (true) {
                val entry = zip.nextEntry ?: return null
                if (!entry.isDirectory && entry.name.endsWith(".txt", ignoreCase = true)) {
                    return String(zip.readBytes(), Charsets.UTF_8)
                }
            }
        }
    }
}
