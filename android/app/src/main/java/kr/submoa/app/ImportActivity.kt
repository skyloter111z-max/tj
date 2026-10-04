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
        val text = runCatching { readShared(intent) }.getOrNull()
        if (text != null && KakaoExport.looksLikeExport(text)) {
            ImportStore.savePending(this, text)
            startActivity(
                Intent(this, MainActivity::class.java)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
                    .putExtra(MainActivity.EXTRA_IMPORTED, true),
            )
        } else {
            Toast.makeText(this, "카카오톡 대화 내보내기 파일이 아니에요", Toast.LENGTH_LONG).show()
        }
        finish()
    }

    private fun readShared(intent: Intent): String? {
        val uri: Uri? = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            intent.getParcelableExtra(Intent.EXTRA_STREAM, Uri::class.java)
        } else {
            @Suppress("DEPRECATION")
            intent.getParcelableExtra(Intent.EXTRA_STREAM)
        }
        if (uri != null) {
            contentResolver.openInputStream(uri)?.use { input ->
                return KakaoExport.decode(input.readBytes())
            }
        }
        return intent.getStringExtra(Intent.EXTRA_TEXT)?.takeIf { it.isNotBlank() }
    }
}
