package kr.talkdock.app

import android.Manifest
import android.view.View
import android.view.ViewGroup
import android.widget.ScrollView
import androidx.test.ext.junit.runners.AndroidJUnit4
import kr.talkdock.app.ui.CommentComposer
import kr.talkdock.app.ui.ElderReplyPanel
import kr.talkdock.app.ui.FeedPostCard
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.util.Collections

/** Elderly mode listens and replies inside the feed card without opening another screen. */
@RunWith(AndroidJUnit4::class)
class ElderInlineReplyTest {
    private val caption = "할머니, 오늘 공원에서 단풍을 봤어요!"
    private val sentComments = Collections.synchronizedList(mutableListOf<String>())
    private fun post(id: Int) = JSONObject().put("id", id).put("author_id", 40 + id).put("author_name", "지우$id")
        .put("relationship", "손녀").put("caption", caption).put("created_at", "2026-11-20T10:00:00+09:00")
        .put("images", JSONArray()).put("comment_count", 0)
    private fun detail(id: Int) = post(id).put("comments", JSONArray().apply {
        sentComments.forEachIndexed { index, text ->
            put(JSONObject().put("id", index + 1).put("author_name", "테스트 사용자").put("relationship", "할머니").put("text", text))
        }
    })
    private fun audio(): Reply {
        val samples = 16000
        val bytes = java.nio.ByteBuffer.allocate(44 + samples * 2).order(java.nio.ByteOrder.LITTLE_ENDIAN)
        bytes.put("RIFF".toByteArray()).putInt(36 + samples * 2).put("WAVEfmt ".toByteArray())
            .putInt(16).putShort(1).putShort(1).putInt(16000).putInt(32000).putShort(2).putShort(16)
            .put("data".toByteArray()).putInt(samples * 2)
        repeat(samples) { bytes.putShort(0) }
        return Reply(bytes.array(), type = "audio/wav")
    }
    private fun server(summary: JSONObject = JSONObject().put("status", "ready").put("text", "지우가 공원에서 단풍을 봤대요.")) =
        MockApi { r -> when {
            r.path == "/api/families/current/" -> jsonReply(room(1, "우리 가족"))
            r.path == "/api/posts/" -> jsonReply(JSONObject().put("posts", JSONArray().put(post(1)).put(post(2))))
            r.path.matches(Regex("/api/posts/\\d+/")) -> jsonReply(detail(r.path.split('/')[3].toInt()))
            r.path == "/api/posts/1/comments/" -> { sentComments.add(JSONObject(r.body).getString("text")); jsonReply(JSONObject().put("id", 9)) }
            r.path.endsWith("/message/") -> jsonReply(summary)
            r.path.endsWith("/replies/transcribe/") -> jsonReply(JSONObject().put("recognized", "단풍 예쁘다"))
            r.path.endsWith("/replies/prepare/") -> jsonReply(JSONObject().put("id", 55).put("recognized", "단풍 예쁘다")
                .put("converted", "지우야, 단풍이 참 예쁘구나!"))
            r.path == "/api/replies/55/send/" -> { sentComments.add("지우야, 단풍이 참 예쁘구나!"); jsonReply(JSONObject().put("id", 10)) }
            r.path == "/api/speech/" -> audio()
            else -> jsonReply(JSONObject())
        } }
    private fun descendants(root: View): List<View> = listOf(root) + if (root is ViewGroup)
        (0 until root.childCount).flatMap { descendants(root.getChildAt(it)) } else emptyList()
    private fun UiHarness.card(id: Int = 1) = all().filterIsInstance<FeedPostCard>().single { it.post.getInt("id") == id }
    private fun UiHarness.tapIn(id: Int, label: String) = test.runOnMainSync {
        descendants(card(id)).first { it.contentDescription == label && it.isShown }.performClick()
    }
    private fun UiHarness.stillOnFeed() = all().filterIsInstance<FeedPostCard>().size == 2 && currentScreen() == "home"
    private fun UiHarness.panel(id: Int = 1) = descendants(card(id)).filterIsInstance<ElderReplyPanel>().singleOrNull()

    @Test fun afterListeningTheCardsReplyIsTypedAndSentInsideTheCard() = server().use { api ->
        UiHarness(api, room(1, "우리 가족"), large = true, tutorialSeen = true).use { ui ->
            ui.await { ui.all().filterIsInstance<FeedPostCard>().size == 2 }
            ui.tapIn(1, "소식 듣기")
            ui.await { ui.has("지우가 공원에서 단풍을 봤대요.") }
            // The card's own 댓글 달기 is the only reply button; none is repeated under the summary.
            ui.test.runOnMainSync { assertEquals(1, descendants(ui.card(1)).count { it.contentDescription == "댓글 달기" }) }
            ui.tapIn(1, "댓글 달기")
            ui.await { ui.panel() != null }
            ui.test.runOnMainSync { assertTrue(ui.stillOnFeed()) }
            ui.screenshot("elder-11-inline-reply.png")
            val draft = "단풍 사진도 보고 싶구나"
            ui.test.runOnMainSync {
                descendants(ui.panel()!!).filterIsInstance<CommentComposer>().single().input.setText(draft)
            }
            ui.tapIn(1, "댓글 보내기")
            ui.await { sentComments == listOf(draft) }
            ui.await { ui.panel() == null && ui.has(draft) }
            ui.test.runOnMainSync { assertTrue(ui.stillOnFeed()) }
        }
    }

    @Test fun spokenReplyIsConfirmedThenSentWithoutLeavingTheFeed() = server().use { api ->
        UiHarness(api, room(1, "우리 가족"), large = true, tutorialSeen = true).use { ui ->
            ui.test.uiAutomation.grantRuntimePermission(ui.activity.packageName, Manifest.permission.RECORD_AUDIO)
            ui.await { ui.all().filterIsInstance<FeedPostCard>().size == 2 }
            var position = 0
            ui.test.runOnMainSync { position = ui.all().filterIsInstance<ScrollView>().first().scrollY }
            ui.tapIn(1, "댓글 달기")
            ui.await { ui.panel() != null }
            ui.tapIn(1, "말로 답하기")
            ui.await { ui.has("듣고 있어요") }
            Thread.sleep(900)
            ui.tapIn(1, "다 말했어요")
            ui.await(10000) { ui.has("이렇게 보낼게요") && ui.has("지우야, 단풍이 참 예쁘구나!") }
            ui.screenshot("elder-12-voice-reply-review.png")
            assertFalse(api.paths().any { it.endsWith("/send/") })
            ui.test.runOnMainSync { assertTrue(ui.stillOnFeed()) }
            ui.click("가족에게 보내기")
            ui.await { api.requests.count { it.method == "POST" && it.path == "/api/replies/55/send/" } == 1 }
            ui.await { ui.panel() == null && ui.has("지우야, 단풍이 참 예쁘구나!") }
            ui.test.runOnMainSync {
                assertTrue(ui.stillOnFeed())
                assertTrue(kotlin.math.abs(ui.all().filterIsInstance<ScrollView>().first().scrollY - position) < ui.activity.resources.displayMetrics.heightPixels)
            }
        }
    }

    @Test fun onlyOneCardKeepsAReplyOpenAndListeningClosesIt() = server().use { api ->
        UiHarness(api, room(1, "우리 가족"), large = true, tutorialSeen = true).use { ui ->
            ui.await { ui.all().filterIsInstance<FeedPostCard>().size == 2 }
            ui.tapIn(1, "댓글 달기"); ui.await { ui.panel(1) != null }
            ui.tapIn(2, "댓글 달기"); ui.await { ui.panel(2) != null && ui.panel(1) == null }
            ui.tapIn(2, "답장 닫기"); ui.await { ui.panel(2) == null }
            // Listening on another card, or on the same card, folds an open reply away.
            ui.tapIn(1, "댓글 달기"); ui.await { ui.panel(1) != null }
            ui.tapIn(2, "소식 듣기"); ui.await { ui.panel(1) == null }
            ui.tapIn(1, "댓글 달기"); ui.await { ui.panel(1) != null }
            ui.tapIn(1, "소식 듣기"); ui.await { ui.panel(1) == null }
            ui.test.runOnMainSync { assertTrue(ui.stillOnFeed()) }
            assertTrue(api.requests.none { it.method == "POST" && it.path != "/api/speech/" && it.path != "/api/notifications/device/" })
        }
    }

    @Test fun afterListeningTodakQuestionsOpenFromTheCardWithoutABot() = server().use { api ->
        UiHarness(api, room(1, "우리 가족"), large = true, tutorialSeen = true).use { ui ->
            ui.await { ui.all().filterIsInstance<FeedPostCard>().size == 2 }
            ui.tapIn(1, "소식 듣기")
            ui.await { ui.has("지우가 공원에서 단풍을 봤대요.") && ui.has("이 소식 관련해서 궁금한 점을 토닥이에게 물어보세요!") }
            ui.screenshot("elder-10-listen-summary-ask.png")
            ui.test.runOnMainSync { assertEquals(0, descendants(ui.card(2)).count { it.contentDescription == "소식 물어보기" }) }
            ui.tapIn(1, "소식 물어보기")
            ui.await { ui.all().any { it is kr.talkdock.app.ui.PostQuestionPanel } }
            ui.test.runOnMainSync { ui.all().first { it.contentDescription == "도우미 닫기" }.performClick() }
            ui.await { ui.all().none { it is kr.talkdock.app.ui.PostQuestionPanel } }
            // The elderly screen has no floating assistant; asking happens from the card only.
            ui.test.runOnMainSync { assertTrue(ui.all().none { it is kr.talkdock.app.ui.FloatingAssistantView }) }
        }
    }

    @Test fun guidePointsAtReplyOnlyAfterThePostHasBeenRead() = server().use { api ->
        UiHarness(api, room(1, "우리 가족"), large = true, tutorialSeen = false).use { ui ->
            fun cue(view: View?) = view?.let { androidx.core.view.ViewCompat.getStateDescription(it)?.toString() }
            fun guided() = ui.all().filterIsInstance<FeedPostCard>().single { cue(it.listenAction) == "안내: 소식 듣기" }
            ui.await { ui.all().filterIsInstance<FeedPostCard>().any { cue(it.listenAction) == "안내: 소식 듣기" } }
            var id = 0
            ui.test.runOnMainSync { val card = guided(); id = card.post.getInt("id"); card.listenAction!!.performClick() }
            // While the summary is prepared and read aloud, nothing points at the next step yet.
            ui.test.runOnMainSync {
                assertTrue(ui.card(id).audio.isPlaying)
                assertNotEquals("안내: 댓글 달기", cue(ui.card(id).replyAction))
            }
            ui.await { ui.has("지우가 공원에서 단풍을 봤대요.") }
            ui.await { cue(ui.card(id).replyAction) == "안내: 댓글 달기" }
            ui.test.runOnMainSync { assertFalse(ui.card(id).audio.isPlaying) }
        }
    }

    @Test fun unavailableSummaryReadsTheFamilyCaptionAtOnce() = server(JSONObject().put("status", "failed")).use { api ->
        UiHarness(api, room(1, "우리 가족"), large = true, tutorialSeen = true).use { ui ->
            ui.await { ui.all().filterIsInstance<FeedPostCard>().size == 2 }
            ui.tapIn(1, "소식 듣기")
            ui.await { ui.has("요약 대신 가족이 쓴 글을 읽어 드려요.") }
            ui.await { api.requests.any { it.path == "/api/speech/" && it.body.contains(caption) } }
            ui.test.runOnMainSync {
                assertTrue(ui.has("설명 다시 준비하기"))
                assertEquals(1, descendants(ui.card(1)).count { it.contentDescription == "댓글 달기" })
                assertTrue(ui.has("이 소식 관련해서 궁금한 점을 토닥이에게 물어보세요!"))
            }
        }
    }
}
