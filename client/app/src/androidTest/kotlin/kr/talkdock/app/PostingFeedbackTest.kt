package kr.talkdock.app

import android.view.View
import android.widget.EditText
import androidx.test.ext.junit.runners.AndroidJUnit4
import kr.talkdock.app.ui.CommentComposer
import kr.talkdock.app.ui.FeedPostCard
import kr.talkdock.app.ui.TodakWaitingView
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit.SECONDS

@RunWith(AndroidJUnit4::class)
class PostingFeedbackTest {
    private val family = room(1, "우리 가족")
    private val caption = "봄 햇살 아래 가족과 산책했어요."
    private val comment = "사진 보니 같이 걷고 싶네요!"

    private fun news(comments: JSONArray = JSONArray()) = JSONObject()
        .put("id", 1).put("author_id", 999).put("author_name", "지우").put("relationship", "나")
        .put("caption", caption).put("created_at", "2026-10-19T10:00:00+09:00")
        .put("images", JSONArray()).put("comments", comments).put("comment_count", comments.length())

    private fun feed(post: JSONObject) = jsonReply(JSONObject().put("posts", JSONArray().put(post)))

    private fun UiHarness.press(tag: String) = test.runOnMainSync {
        assertTrue(all().single { it.tag == tag }.performClick())
    }

    private fun UiHarness.assertUnblocked() = test.runOnMainSync {
        assertTrue(all().any { it.tag == "posting-status" && it.isShown })
        assertTrue(all().none { it is TodakWaitingView })
    }

    @Test fun postingLeavesTheComposerImmediatelyAndPreservesTheNextDraft() {
        val uploaded = CountDownLatch(1)
        var saved = false
        MockApi { request -> when {
            request.path == "/api/families/current/" -> jsonReply(family)
            request.path == "/api/posts/" && request.method == "POST" -> {
                uploaded.await(12, SECONDS)
                saved = true
                jsonReply(news(), 201)
            }
            request.path == "/api/posts/" && saved -> feed(news())
            else -> emptyFeed()
        } }.use { api -> UiHarness(api, family, tutorialSeen = true).use { ui ->
            try {
                ui.await { ui.has("첫 소식을 기다리고 있어요") }
                ui.press("home-compose")
                ui.test.runOnMainSync { ui.all().filterIsInstance<EditText>().single().setText(caption) }
                ui.click("가족에게 전하기")
                ui.await { ui.has("게시 확인 중") && ui.has("첫 소식을 기다리고 있어요") }
                ui.assertUnblocked()
                ui.press("home-compose")
                ui.await { ui.has("가족에게 전하기") && ui.has("게시 확인 중") }
                val draft = "업로드 중에도 쓸 수 있는 다음 소식"
                ui.test.runOnMainSync { ui.all().filterIsInstance<EditText>().single().setText(draft) }
                uploaded.countDown()
                ui.await { ui.all().none { it.tag == "posting-status" && it.isShown } }
                ui.test.runOnMainSync {
                    assertEquals(draft, ui.all().filterIsInstance<EditText>().single().text.toString())
                    ui.all().filterIsInstance<EditText>().single().setText("")
                    ui.activity.onBackPressedDispatcher.onBackPressed()
                }
                ui.await { ui.all().any { it is FeedPostCard && it.post.optString("caption") == caption } }
                assertEquals(1, api.requests.count { it.method == "POST" && it.path == "/api/posts/" })
            } finally { uploaded.countDown() }
        } }
    }

    @Test fun commentKeepsSendingAfterLeavingItsDetail() {
        val sent = CountDownLatch(1)
        val comments = JSONArray()
        MockApi { request -> when (request.path) {
            "/api/families/current/" -> jsonReply(family)
            "/api/posts/" -> feed(news(comments))
            "/api/posts/1/" -> jsonReply(news(comments))
            "/api/posts/1/comments/" -> {
                sent.await(12, SECONDS)
                comments.put(JSONObject().put("id", 1).put("author_name", "지우").put("relationship", "나")
                    .put("text", JSONObject(request.body).getString("text")))
                jsonReply(JSONObject().put("id", 1), 201)
            }
            else -> emptyFeed()
        } }.use { api -> UiHarness(api, family, tutorialSeen = true).use { ui ->
            try {
                ui.openCurrentPost()
                ui.test.runOnMainSync {
                    val composer = ui.all().filterIsInstance<CommentComposer>().single()
                    composer.input.setText(comment)
                    composer.sendButton.performClick()
                }
                ui.await { ui.has("댓글 전송 중") }
                ui.assertUnblocked()
                ui.press("guide-back")
                ui.await { ui.has("댓글 전송 중") && ui.all().any { it is FeedPostCard } }
                sent.countDown()
                ui.await { ui.all().any { it.contentDescription == "댓글 1" } &&
                    ui.all().none { it.tag == "posting-status" && it.isShown } }
                ui.openCurrentPost()
                ui.await { ui.has("댓글 1") && ui.has(comment) }
                assertEquals(1, api.paths().count { it == "/api/posts/1/comments/" })
            } finally { sent.countDown() }
        } }
    }
}
