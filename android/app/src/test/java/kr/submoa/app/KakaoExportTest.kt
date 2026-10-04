package kr.submoa.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.ByteArrayOutputStream
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

class KakaoExportTest {
    private val export = "﻿삼성카드 님과 카카오톡 대화\r\n저장한 날짜 : 2026년 10월 4일 오후 9:16\r\n\r\n" +
        "2026년 10월 3일 오후 9:24, 삼성카드 : 삼성1088승인 홍*동\r\n88,000원 일시불\r\n10/03 21:24 바다식당\r\n"

    @Test
    fun `카톡 내보내기 파일을 알아본다`() {
        assertTrue(KakaoExport.looksLikeExport(export))
        assertTrue(KakaoExport.looksLikeExport("2026. 10. 3. 오후 9:24, 삼성카드 : 삼성1088승인"))
    }

    @Test
    fun `다른 파일은 받지 않는다`() {
        assertFalse(KakaoExport.looksLikeExport("회의록\n- 다음 주 일정"))
    }

    @Test
    fun `텍스트 파일은 그대로 읽는다`() {
        assertEquals(export, KakaoExport.decode(export.toByteArray()))
    }

    @Test
    fun `zip으로 오면 안의 txt를 꺼낸다`() {
        val bytes = ByteArrayOutputStream().also { out ->
            ZipOutputStream(out).use { zip ->
                zip.putNextEntry(ZipEntry("photo.jpg")); zip.write(byteArrayOf(1, 2, 3)); zip.closeEntry()
                zip.putNextEntry(ZipEntry("KakaoTalkChats.txt")); zip.write(export.toByteArray()); zip.closeEntry()
            }
        }.toByteArray()
        assertEquals(export, KakaoExport.decode(bytes))
    }

    @Test
    fun `너무 큰 파일은 받지 않는다`() {
        assertNull(KakaoExport.decode(ByteArray(KakaoExport.MAX_BYTES + 1)))
    }
}
