package kr.talkdock.app

import android.view.View
import android.view.ViewGroup
import android.view.inspector.WindowInspector
import android.widget.TextView
import android.widget.Button
import androidx.test.ext.junit.runners.AndroidJUnit4
import kr.talkdock.app.ui.CommentComposer
import kr.talkdock.app.ui.FeedPostCard
import kr.talkdock.app.ui.PostQuestionPanel
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.util.Collections

/** Unsent comments, unfinished posts and past questions are kept on the phone only. */
@RunWith(AndroidJUnit4::class)
class LocalDraftsTest {
    private val sent = Collections.synchronizedList(mutableListOf<String>())
    private fun post(id: Int) = JSONObject().put("id", id).put("author_id", 40 + id).put("author_name", "지우$id")
        .put("relationship", "손녀").put("caption", "오늘의 소식 $id").put("created_at", "2026-11-20T10:00:00+09:00")
        .put("images", JSONArray()).put("comment_count", 0).put("comments", JSONArray())
    private fun server(posts: Boolean = true) = MockApi { r -> when {
        r.path == "/api/families/current/" -> jsonReply(room(1, "우리 가족"))
        r.path == "/api/posts/" && r.method == "GET" -> if (posts) jsonReply(JSONObject().put("posts", JSONArray().put(post(1)))) else emptyFeed()
        r.path == "/api/posts/1/" -> jsonReply(post(1))
        r.path == "/api/posts/1/comments/" -> { sent.add(JSONObject(r.body).getString("text")); jsonReply(JSONObject().put("id", 9)) }
        r.path.endsWith("/message/") -> jsonReply(JSONObject().put("status", "ready").put("text", "지우가 남긴 소식이에요."))
        r.path == "/api/posts/1/questions/" -> jsonReply(JSONObject().put("text", "답변: " + JSONObject(r.body).getString("question")))
        r.path == "/api/speech/" -> Reply(ByteArray(0), 503, "application/json")
        r.path == "/api/searching/history/" -> jsonReply(JSONObject().put("text", "답: " + JSONObject(r.body).getString("question"))
            .put("evidence_posts", JSONArray().put(post(1))).put("evidence_kind", "cited"))
        else -> jsonReply(JSONObject())
    } }
    private fun descendants(root: View): List<View> = listOf(root) + if (root is ViewGroup)
        (0 until root.childCount).flatMap { descendants(root.getChildAt(it)) } else emptyList()
    private fun UiHarness.detailComposer() = all().filterIsInstance<CommentComposer>().single { it.tag == "detail-comment" }
    // Dialogs live in their own windows; WindowInspector lists every window of this process. Call on the main thread.
    private fun windowText(text: String) = WindowInspector.getGlobalWindowViews().filter { it.isShown }
        .flatMap { descendants(it) }.filterIsInstance<TextView>().firstOrNull { it.text.toString() == text }
    private fun UiHarness.back() = test.runOnMainSync { activity.onBackPressedDispatcher.onBackPressed() }

    @Test fun unsentCommentComesBackOnTheSamePostAndIsForgottenAfterSending() = server().use { api ->
        UiHarness(api, room(1, "우리 가족"), tutorialSeen = true).use { ui ->
            ui.openCurrentPost()
            ui.test.runOnMainSync { ui.detailComposer().input.setText("이따 다시 쓸 댓글") }
            ui.back(); ui.await { ui.currentScreen() == "home" }
            ui.openCurrentPost()
            ui.test.runOnMainSync { assertEquals("이따 다시 쓸 댓글", ui.detailComposer().input.text.toString()) }
            ui.screenshot("draft-1-comment-restored.png")
            ui.test.runOnMainSync { ui.detailComposer().sendButton.performClick() }
            ui.await { sent == listOf("이따 다시 쓸 댓글") }
            ui.await { ui.detailComposer().input.text.isEmpty() }
            ui.back(); ui.await { ui.currentScreen() == "home" }
            ui.openCurrentPost()
            ui.test.runOnMainSync { assertTrue(ui.detailComposer().input.text.isEmpty()) }
        }
    }

    @Test fun savedPostDraftReopensWithItsTextUntilItIsPublishedOrDiscarded() = server(posts = false).use { api ->
        UiHarness(api, room(1, "우리 가족"), tutorialSeen = true).use { ui ->
            fun openComposer() {
                ui.awaitOrDescribe { ui.all().any { it.tag == "home-compose" && it.isShown } }
                ui.test.runOnMainSync { ui.all().first { it.tag == "home-compose" }.performClick() }
                ui.await { ui.has("가족에게 전하기") }
            }
            fun caption() = ui.all().filterIsInstance<android.widget.EditText>().single()
            fun leaveWith(label: String, shot: String? = null) {
                ui.back()
                ui.await { windowText(label) != null }
                shot?.let(ui::screenshot)
                ui.test.runOnMainSync { assertTrue(label, windowText(label)!!.performClick()) }
                ui.await { ui.currentScreen() == "home" }
            }
            openComposer()
            ui.test.runOnMainSync { caption().setText("쓰다 만 소식") }
            leaveWith("임시 저장", "draft-2-post-leave-dialog.png")
            openComposer()
            ui.test.runOnMainSync { assertEquals("쓰다 만 소식", caption().text.toString()) }
            ui.screenshot("draft-3-post-restored.png")
            leaveWith("그만하기")
            openComposer()
            ui.test.runOnMainSync { assertTrue(caption().text.isEmpty()) }
        }
    }

    @Test fun earlierMemorySearchesReopenFromOneToggleWithoutAskingAgain() = server().use { api ->
        UiHarness(api, room(1, "우리 가족"), tutorialSeen = true).use { ui ->
            fun openMemories() {
                ui.awaitOrDescribe { ui.all().any { it.tag == "main-tab:memories" } }
                ui.test.runOnMainSync { ui.all().single { it.tag == "main-tab:memories" }.performClick() }
                ui.awaitOrDescribe { ui.all().any { it is kr.talkdock.app.ui.FamilyMemoryPanel } }
            }
            fun panel() = ui.all().filterIsInstance<kr.talkdock.app.ui.FamilyMemoryPanel>().single()
            fun ask(question: String) {
                ui.test.runOnMainSync { panel().input.setText(question); panel().searchButton.performClick() }
                ui.awaitOrDescribe { ui.has("답: $question") }
            }
            openMemories()
            ui.test.runOnMainSync { assertTrue(ui.all().none { it.tag == "memory-history-toggle" }) }
            ask("여행은 어디로 갔지?"); ask("카메라는 누구 거야?")
            // A new panel (after switching tabs) reads the saved searches back from the device.
            ui.test.runOnMainSync { ui.all().single { it.tag == "main-tab:home" }.performClick() }
            ui.awaitOrDescribe { ui.currentScreen() == "home" }
            openMemories()
            ui.awaitOrDescribe { ui.all().any { it.tag == "memory-history-toggle" } }
            ui.test.runOnMainSync {
                val toggle = ui.all().single { it.tag == "memory-history-toggle" } as Button
                assertEquals("이전에 찾아본 추억 2개 보기 ▾", toggle.text.toString())
                assertTrue(ui.all().none { it.tag == "memory-history-item" })
            }
            ui.screenshot("draft-8-memory-history-closed.png")
            ui.test.runOnMainSync { (ui.all().single { it.tag == "memory-history-toggle" } as Button).performClick() }
            ui.awaitOrDescribe { ui.all().count { it.tag == "memory-history-item" && it.isShown } == 2 }
            ui.screenshot("draft-9-memory-history-open.png")
            ui.test.runOnMainSync {
                val items = ui.all().filter { it.tag == "memory-history-item" }.map { it as Button }
                assertEquals(listOf("카메라는 누구 거야?", "여행은 어디로 갔지?"), items.map { it.text.toString() })
                items.last().performClick()
            }
            ui.awaitOrDescribe { ui.has("답: 여행은 어디로 갔지?") }
            ui.test.runOnMainSync {
                assertEquals("여행은 어디로 갔지?", panel().input.text.toString())
                assertFalse(ui.has("답: 카메라는 누구 거야?"))
            }
            assertEquals("A saved search is shown without asking again", 2, api.paths().count { it == "/api/searching/history/" })
        }
    }

    @Test fun earlierQuestionsStayBehindOneToggleWhenTheQuestionSheetOpensAgain() = server().use { api ->
        UiHarness(api, room(1, "우리 가족"), large = true, tutorialSeen = true).use { ui ->
            fun card() = ui.all().filterIsInstance<FeedPostCard>().single()
            fun openQuestions() {
                ui.awaitOrDescribe { descendants(card()).any { it.contentDescription == "소식 듣기" && it.isShown } }
                ui.test.runOnMainSync { descendants(card()).first { it.contentDescription == "소식 듣기" && it.isShown }.performClick() }
                ui.await { descendants(card()).any { it.tag == "post-audio-ask" && it.isShown } }
                ui.test.runOnMainSync { descendants(card()).first { it.tag == "post-audio-ask" }.performClick() }
                ui.await { ui.all().any { it is PostQuestionPanel } }
            }
            fun close() {
                ui.test.runOnMainSync { ui.all().first { it.contentDescription == "도우미 닫기" }.performClick() }
                ui.await { ui.all().none { it is PostQuestionPanel } }
            }
            ui.await { ui.all().any { it is FeedPostCard } }
            openQuestions()
            ui.test.runOnMainSync { assertTrue(ui.all().none { it.tag == "question-history-toggle" }) }
            ui.test.runOnMainSync {
                val composer = ui.all().filterIsInstance<PostQuestionPanel>().single().composer
                composer.input.setText("누구랑 갔어?"); composer.sendButton.performClick()
            }
            ui.await { ui.has("답변: 누구랑 갔어?") }
            close()
            openQuestions()
            ui.await { ui.all().any { it.tag == "question-history-toggle" } }
            ui.test.runOnMainSync {
                val toggle = ui.all().single { it.tag == "question-history-toggle" } as Button
                assertEquals("이전에 물어본 질문 1개 보기 ▾", toggle.text.toString())
                assertFalse(ui.all().single { it.tag == "question-history-list" }.isShown)
            }
            ui.screenshot("draft-4-question-history-closed.png")
            ui.test.runOnMainSync { (ui.all().single { it.tag == "question-history-toggle" } as Button).performClick() }
            ui.test.runOnMainSync {
                assertTrue(ui.all().single { it.tag == "question-history-list" }.isShown)
                assertTrue(ui.has("누구랑 갔어?")); assertTrue(ui.has("답변: 누구랑 갔어?"))
            }
            ui.screenshot("draft-5-question-history-open.png")
            // The earlier turn is sent as context for the next question.
            ui.test.runOnMainSync {
                val composer = ui.all().filterIsInstance<PostQuestionPanel>().single().composer
                composer.input.setText("언제였어?"); composer.sendButton.performClick()
            }
            ui.await { ui.has("답변: 언제였어?") }
            val prior = JSONObject(api.requests.last { it.path == "/api/posts/1/questions/" }.body).getJSONArray("prior_dialogue")
            assertEquals("누구랑 갔어?", prior.getJSONObject(0).getString("text"))
        }
    }
}

/** What was on screen when a wait failed, so a failure says why. */
internal fun UiHarness.awaitOrDescribe(timeout: Long = 10000, condition: () -> Boolean) {
    try { await(timeout, condition) } catch (failure: AssertionError) {
        var state = ""
        test.runOnMainSync {
            state = "screen=" + currentScreen() + " texts=" + all().filterIsInstance<android.widget.TextView>().filter { it.isShown }
                .map { it.text.toString() }.filter { it.isNotBlank() }.take(40) + " labels=" + all().filter { it.isShown }
                .mapNotNull { it.contentDescription?.toString() }.take(40)
        }
        throw AssertionError("UI condition timed out: " + state)
    }
}
