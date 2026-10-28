package kr.talkdock.app

import android.text.TextUtils
import android.view.View
import android.widget.ScrollView
import android.widget.TextView
import androidx.test.ext.junit.runners.AndroidJUnit4
import kr.talkdock.app.ui.DigestPostRow
import kr.talkdock.app.ui.PhotoCarousel
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class DigestPostListTest {
    private val captions = listOf(
        "가족과 함께 단풍 구경을 다녀왔어요.\n점심도 먹고 사진도 많이 찍어서 오래 기억에 남을 하루였어요.",
        "이 드라마 참 재미있다.",
        "",
    )
    private fun post(id: Int) = JSONObject().put("id", id).put("author_id", id)
        .put("author_name", listOf("함준하", "홍정아", "김대협")[id - 1])
        .put("relationship", "가족").put("caption", captions[id - 1])
        .put("created_at", "2026-10-27T09:00:00+09:00").put("comment_count", 0).put("comments", JSONArray())
        .put("images", JSONArray().put(JSONObject().put("url", "/api/posts/$id/image/").put("width", 1200).put("height", 1800)))
        .put("image_url", "/api/posts/$id/image/").put("image_count", 1)

    private fun server() = MockApi { request -> when {
        request.path == "/api/families/current/" -> jsonReply(room(77, "하루 요약 검증 가족"))
        request.path == "/api/posts/" -> emptyFeed()
        request.path.startsWith("/api/digests/?") -> jsonReply(JSONObject().put("status", "ready")
            .put("text", "단풍을 구경하고 드라마 이야기를 나눴어요.")
            .put("posts", JSONArray((1..3).map { post(it) })))
        request.path.matches(Regex("/api/posts/[123]/")) -> jsonReply(post(request.path.split('/')[3].toInt()).put("images", JSONArray()).put("image_url", "").put("image_count", 0))
        else -> jsonReply(JSONObject())
    } }

    @Test fun compactRowsAvoidPhotosAndOpenTheirOwnSourcePostInBothTextSizes() {
        for (large in listOf(false, true)) server().use { api -> UiHarness(api, room(77, "하루 요약 검증 가족"), large).use { screen ->
            screen.await { screen.has("첫 소식을 기다리고 있어요") }
            screen.openAssistantOption("오늘 가족의 하루")
            screen.await {
                val rows = screen.all().filterIsInstance<DigestPostRow>()
                screen.has("이날의 소식 3개") && rows.size == 3 && rows.all { it.height > 0 }
            }
            screen.test.runOnMainSync {
                assertTrue(screen.has("함준하")); assertTrue(screen.has("홍정아")); assertTrue(screen.has("김대협"))
                assertTrue(screen.has("사진으로 전한 소식"))
                assertFalse(screen.has("소식 보기"))
                assertTrue(screen.all().none { it is PhotoCarousel })
                val rows = screen.all().filterIsInstance<DigestPostRow>()
                for (row in rows) {
                    assertTrue(row.isClickable && row.isFocusable)
                    assertTrue(row.height >= screen.activity.resources.displayMetrics.density * 48)
                    assertTrue(screen.all(row).filterIsInstance<TextView>().all { it.maxLines == 1 })
                }
                val preview = screen.all(rows[0]).filterIsInstance<TextView>().last()
                assertEquals(TextUtils.TruncateAt.END, preview.ellipsize)
                assertFalse(preview.text.contains('\n'))
                assertTrue("Long source text must be visibly truncated", preview.layout.getEllipsisCount(0) > 0)
                screen.all().filterIsInstance<ScrollView>().first().fullScroll(View.FOCUS_DOWN)
            }
            screen.test.waitForIdleSync()
            screen.screenshot(if (large) "digest-compact-large.png" else "digest-compact.png")
            assertTrue("Digest rows must not download photos", api.paths().none { it.contains("/image/") || it.contains("/images/") })
            for (id in listOf(2, 1, 3)) {
                screen.test.runOnMainSync {
                    assertTrue(screen.all().filterIsInstance<DigestPostRow>()[id - 1].performClick())
                }
                screen.await { screen.has("따뜻한 한마디 남기기") }
                val detailRequest = synchronized(api.requests) { api.requests.last { it.path.matches(Regex("/api/posts/[123]/")) } }
                assertEquals("/api/posts/$id/", detailRequest.path)
                assertEquals("77", detailRequest.room)
                screen.test.runOnMainSync {
                    assertTrue(screen.has(captions[id - 1].ifBlank { "사진으로 남긴 오늘의 하루" }))
                }
                screen.openAssistantOption("오늘 가족의 하루")
                screen.await { screen.has("이날의 소식 3개") }
            }
        } }
    }
}
