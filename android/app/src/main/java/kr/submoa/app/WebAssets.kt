package kr.submoa.app

import android.content.res.AssetManager
import android.webkit.WebResourceResponse
import androidx.webkit.WebViewAssetLoader
import java.io.IOException

/**
 * APK 안에 넣은 웹 앱(`npm run export` 결과, assets/web/)을 서버 없이 띄운다.
 *
 * Next 정적 내보내기는 `/onboarding` 링크를 `onboarding.html` 파일로, `/`를 `index.html`로 만든다.
 * 그래서 확장자 없는 경로는 .html·index.html 순으로 찾아 준다.
 * https://appassets.androidplatform.net 출처로 서빙해야 localStorage와 `/_next/...` 절대 경로가 동작한다.
 */
object WebAssets {
    const val HOST = "appassets.androidplatform.net"

    /** 요청 경로 → assets/web/ 아래에서 찾아볼 파일 후보 (순서대로) */
    fun candidates(path: String): List<String> {
        val p = path.trimStart('/')
        if (p.isEmpty() || p.endsWith("/")) return listOf("${p}index.html")
        val last = p.substringAfterLast('/')
        return if ('.' in last) listOf(p) else listOf("$p.html", "$p/index.html")
    }

    fun mimeType(file: String): String = when (file.substringAfterLast('.', "").lowercase()) {
        "html" -> "text/html"
        "js" -> "text/javascript"
        "css" -> "text/css"
        "json" -> "application/json"
        "txt" -> "text/plain" // Next 클라이언트 이동 때 받는 RSC 조각
        "svg" -> "image/svg+xml"
        "png" -> "image/png"
        "ico" -> "image/x-icon"
        "woff2" -> "font/woff2"
        else -> "application/octet-stream"
    }

    fun loader(assets: AssetManager): WebViewAssetLoader =
        WebViewAssetLoader.Builder()
            .setDomain(HOST)
            .addPathHandler("/", PathHandler(assets))
            .build()

    private class PathHandler(private val assets: AssetManager) : WebViewAssetLoader.PathHandler {
        override fun handle(path: String): WebResourceResponse? {
            for (file in candidates(path)) {
                val stream = try {
                    assets.open("web/$file")
                } catch (_: IOException) {
                    continue
                }
                return WebResourceResponse(mimeType(file), "utf-8", stream)
            }
            return null
        }
    }
}
