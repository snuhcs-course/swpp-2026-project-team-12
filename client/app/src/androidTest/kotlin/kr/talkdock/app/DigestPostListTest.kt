package kr.talkdock.app

import android.view.View
import androidx.test.ext.junit.runners.AndroidJUnit4
import kr.talkdock.app.ui.PhotoCarousel
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

/** Journal covers and extra source links must still open their own post in both text sizes. */
@RunWith(AndroidJUnit4::class)
class DigestPostListTest {
    private val names = listOf("함준하", "홍정아", "김대협", "가족")
    private fun post(id: Int) = JSONObject().put("id", id).put("author_id", id)
        .put("author_name", names[id - 1]).put("relationship", "가족")
        .put("caption", "가족이 남긴 $id 번째 소식입니다. " + "오래 기억하고 싶은 하루예요. ".repeat(id))
        .put("created_at", "2026-10-30T09:00:00+09:00").put("comment_count", 0)
        .put("comments", JSONArray()).put("images", JSONArray())
    private fun server() = MockApi { request -> when {
        request.path == "/api/families/current/" -> jsonReply(room(77, "하루 요약 검증 가족"))
        request.path == "/api/posts/" -> emptyFeed()
        request.path.startsWith("/api/digests/?") -> jsonReply(JSONObject().put("status", "ready")
            .put("text", "가족이 오늘의 소식을 나눴어요.").put("posts", JSONArray((1..4).map { post(it) })))
        request.path.matches(Regex("/api/posts/[1234]/")) -> jsonReply(post(request.path.split('/')[3].toInt()))
        else -> jsonReply(JSONObject())
    } }
    @Test fun everyJournalSourceOpensItsOwnPostIncludingItemsBeyondThePhotoStrip() {
        for (large in listOf(false, true)) server().use { api -> UiHarness(api, room(77, "하루 요약 검증 가족"), large).use { ui ->
            ui.await { ui.has("첫 소식을 기다리고 있어요") }; ui.openDaily()
            ui.await { ui.has("이날의 소식 4개") }
            ui.test.runOnMainSync { assertTrue(ui.has("오늘도, 함께")); assertTrue(ui.all().none { it is PhotoCarousel }) }
            for (id in listOf(3, 1, 4, 2)) {
                val label = names[id - 1] + "의 소식 보기"
                if (id <= 3) ui.test.runOnMainSync { ui.all().first { it.contentDescription == label }.performClick() }
                else ui.click(label)
                ui.await { ui.has("댓글은 이 가족방에만 보여요.") }
                val request = synchronized(api.requests) { api.requests.last { it.path.matches(Regex("/api/posts/[1234]/")) } }
                assertEquals("/api/posts/$id/", request.path); assertEquals("77", request.room)
                ui.test.runOnMainSync { assertTrue(ui.has(post(id).getString("caption"))) }
                ui.openDaily(); ui.await { ui.has("이날의 소식 4개") }
            }
            assertTrue("Text-only journal covers must not download images", api.paths().none { it.contains("/image/") })
        } }
    }
}
