package kr.submoa.app

import org.junit.Assert.assertEquals
import org.junit.Test

class WebAssetsTest {
    @Test
    fun `확장자 없는 경로는 html 파일로 찾는다`() {
        assertEquals(listOf("onboarding.html", "onboarding/index.html"), WebAssets.candidates("/onboarding"))
        assertEquals(listOf("party/p-netflix-1.html", "party/p-netflix-1/index.html"), WebAssets.candidates("/party/p-netflix-1"))
    }

    @Test
    fun `루트와 디렉터리는 index html`() {
        assertEquals(listOf("index.html"), WebAssets.candidates("/"))
        assertEquals(listOf("party/index.html"), WebAssets.candidates("/party/"))
    }

    @Test
    fun `정적 파일은 그대로`() {
        assertEquals(listOf("_next/static/chunks/main.js"), WebAssets.candidates("/_next/static/chunks/main.js"))
        assertEquals("text/javascript", WebAssets.mimeType("_next/static/chunks/main.js"))
        assertEquals("text/plain", WebAssets.mimeType("onboarding.txt"))
    }
}
