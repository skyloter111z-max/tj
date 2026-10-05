package kr.submoa.app

import android.content.Context
import android.net.Uri
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.text.TextRecognition
import com.google.mlkit.vision.text.korean.KoreanTextRecognizerOptions

/**
 * 스토어 구독 스크린샷을 온디바이스로 글자 인식한다(ML Kit 한국어).
 * 네트워크도, 추가 권한도 필요 없다. 인식한 글자는 웹이 parseStoreScreenshot으로 해석한다.
 */
object StoreOcr {
    fun recognize(context: Context, image: Uri, onDone: (String?) -> Unit) {
        val input = try {
            InputImage.fromFilePath(context, image)
        } catch (_: Exception) {
            onDone(null); return
        }
        TextRecognition.getClient(KoreanTextRecognizerOptions.Builder().build())
            .process(input)
            .addOnSuccessListener { onDone(it.text.takeIf { t -> t.isNotBlank() }) }
            .addOnFailureListener { onDone(null) }
    }
}
