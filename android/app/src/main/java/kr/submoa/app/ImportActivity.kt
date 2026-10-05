package kr.submoa.app

import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.widget.Toast

/**
 * 카톡 "대화 내용 내보내기 → 텍스트만 보내기"의 공유 목록에 "구독모아"로 뜬다.
 *
 * 화면 없이 파일만 받아 두고 앱 홈을 연다. 홈이 원본을 꺼내 카드 결제 알림만 골라 저장한다.
 * 카톡 대화 내보내기 파일이 아니면 받지 않는다.
 */
class ImportActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // 이미지 공유 = 스토어 구독 스크린샷 → OCR
        val imageUri = sharedUri(intent)?.takeIf { (intent.type ?: "").startsWith("image/") }
        if (imageUri != null) {
            StoreOcr.recognize(this, imageUri) { ocr ->
                if (ocr != null) {
                    StoreStore.savePendingOcr(this, ocr)
                    openHome(imported = false)
                } else {
                    Toast.makeText(this, "스크린샷에서 글자를 읽지 못했어요", Toast.LENGTH_LONG).show()
                }
                finish()
            }
            return
        }

        // 그 밖 = 카카오톡 대화 내보내기 텍스트/zip
        val text = runCatching { readShared(intent) }.getOrNull()
        if (text != null && KakaoExport.looksLikeExport(text)) {
            ImportStore.savePending(this, text)
            openHome(imported = true)
        } else {
            Toast.makeText(this, "카카오톡 대화 내보내기 파일이 아니에요", Toast.LENGTH_LONG).show()
        }
        finish()
    }

    private fun openHome(imported: Boolean) {
        startActivity(
            Intent(this, MainActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
                .putExtra(MainActivity.EXTRA_IMPORTED, imported),
        )
    }

    private fun sharedUri(intent: Intent): Uri? =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            intent.getParcelableExtra(Intent.EXTRA_STREAM, Uri::class.java)
        } else {
            @Suppress("DEPRECATION")
            intent.getParcelableExtra(Intent.EXTRA_STREAM)
        }

    private fun readShared(intent: Intent): String? {
        val uri: Uri? = sharedUri(intent)
        if (uri != null) {
            contentResolver.openInputStream(uri)?.use { input ->
                return KakaoExport.decode(input.readBytes())
            }
        }
        return intent.getStringExtra(Intent.EXTRA_TEXT)?.takeIf { it.isNotBlank() }
    }
}
