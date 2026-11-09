package kr.talkdock.app

import android.app.Dialog
import android.view.View
import android.widget.EditText
import android.widget.ImageView
import android.widget.TextView
import androidx.test.ext.junit.runners.AndroidJUnit4
import kr.talkdock.app.ui.PhotoCarousel
import kr.talkdock.app.ui.FeedPostCard
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

/** Real activities and gestures, isolated local HTTP fixtures; never calls live AI services. */
@RunWith(AndroidJUnit4::class)
class PhotoLetterDesignTest {
    private var fixtureOrigin = ""
    private fun post(id: Int): JSONObject = JSONObject().put("id", id).put("author_id", id)
        .put("author_name", listOf("정아", "아빠", "엄마")[id - 1]).put("relationship", "가족")
        .put("created_at", "2026-10-30T${17 - id}:30:00+09:00")
        .put("caption", listOf("할머니, 오늘도 즐거운 하루를 보냈어요.", "가족을 위해 저녁을 준비했어요.", "사진 없이 글로도 마음을 전해요.\n".repeat(8))[id - 1])
        .put("images", JSONArray().apply {
            repeat(if (id == 1) 3 else if (id == 2) 1 else 0) { put(JSONObject().put("url", "$fixtureOrigin/api/photos/$id/$it.png")) }
        }).put("comment_count", 1).put("comments", JSONArray().put(JSONObject().put("author_name", "할머니")
            .put("relationship", "가족").put("text", "참 보기 좋구나.")))

    private fun server(): MockApi {
        val test = androidx.test.platform.app.InstrumentationRegistry.getInstrumentation()
        val photo = test.targetContext.resources.openRawResource(R.drawable.family).use { it.readBytes() }
        val api = MockApi { request -> when {
            request.path == "/api/families/current/" -> jsonReply(room(77, "우리 가족"))
            request.path == "/api/posts/" -> jsonReply(JSONObject().put("posts", JSONArray((1..3).map { post(it) })))
            request.path.startsWith("/api/photos/") -> Reply(photo, type = "image/png")
            request.path.matches(Regex("/api/posts/[123]/")) -> jsonReply(post(request.path.split('/')[3].toInt()))
            request.path == "/api/posts/2/questions/" -> jsonReply(JSONObject().put("text", "아빠가 저녁을 준비한 소식이에요."))
            request.path.startsWith("/api/digests/?") -> jsonReply(JSONObject().put("status", "ready")
                .put("text", "정아는 즐거운 하루를 보냈어요. 아빠는 저녁을 준비하고 엄마는 편지를 남겼어요.")
                .put("posts", JSONArray((1..3).map { post(it) })))
            request.path == "/api/digests/history/" -> jsonReply(JSONObject().put("dates", JSONArray().put("2026-10-30")))
            else -> jsonReply(JSONObject())
        } }
        fixtureOrigin = api.base.removeSuffix("/api/")
        return api
    }
    private fun dialog(ui: UiHarness, field: String): Dialog? = ui.activity.javaClass.getDeclaredField(field).let {
        it.isAccessible = true; it.get(ui.activity) as? Dialog
    }
    @Test fun verticalPostsKeepTheirOwnBotContextAndOpenAllPhotosInDetail() {
        server().use { api -> UiHarness(api, room(77, "우리 가족")).use { ui ->
            ui.await { ui.all().filterIsInstance<FeedPostCard>().size == 3 }
            ui.selectLetter(1)
            val card = ui.all().filterIsInstance<FeedPostCard>().single { it.post.getInt("id") == 1 }
            ui.await { ui.all(card).filterIsInstance<ImageView>().any { it.drawable != null } }
            ui.test.runOnMainSync {
                val voice = ui.all(card).single { it.contentDescription == "말로 댓글" }
                assertTrue(voice.isClickable)
                assertTrue(voice.minimumHeight >= 48 * ui.activity.resources.displayMetrics.density)
                assertTrue(ui.all(voice).filterIsInstance<TextView>().isEmpty())
            }
            ui.screenshot("vertical-feed-home.png")
            ui.selectLetter(2)
            assertTrue("Browsing must not start AI requests", api.paths().none { it.contains("questions") || it.contains("message/") || it.contains("speech") })
            ui.openAssistantOption("이 소식 물어보기")
            ui.await { dialog(ui, "assistantDialog")?.isShowing == true }
            val question = dialog(ui, "assistantDialog")!!
            ui.test.runOnMainSync {
                assertTrue(ui.all(question.window!!.decorView).filterIsInstance<TextView>().any { it.text.toString() == "아빠의 소식" })
                ui.all(question.window!!.decorView).filterIsInstance<EditText>().single().setText("누구의 소식이야?")
                ui.all(question.window!!.decorView).first { it.contentDescription == "질문 보내기" }.performClick()
            }
            ui.await { ui.all(question.window!!.decorView).filterIsInstance<TextView>().any { it.text.toString().contains("아빠가 저녁") } }
            assertTrue(api.paths().contains("/api/posts/2/questions/"))
            ui.test.runOnMainSync { question.dismiss() }
            ui.selectLetter(1); ui.openCurrentPost()
            ui.await { ui.all().any { it is PhotoCarousel } && ui.has("참 보기 좋구나.") }
            ui.test.runOnMainSync {
                assertEquals(1, ui.all().filterIsInstance<PhotoCarousel>().size)
                assertTrue(ui.all().count { it.contentDescription?.toString()?.startsWith("사진 ") == true } >= 3)
            }
            assertTrue(api.paths().contains("/api/posts/1/"))
            ui.screenshot("vertical-feed-detail.png")
        } }
    }

    @Test fun settingsAndDailyAreReachableInBothScreenModes() {
        for (large in listOf(false, true)) server().use { api -> UiHarness(api, room(77, "우리 가족"), large).use { ui ->
            ui.await { ui.all().filterIsInstance<FeedPostCard>().size == 3 }
            ui.openSettings(); ui.await { ui.has("내 계정 수정") }
            ui.test.runOnMainSync { ui.all().first { it.contentDescription == "이전 화면" }.performClick() }
            ui.await { ui.all().any { it is FeedPostCard } }
            ui.openDaily()
            ui.await { ui.has("오늘도, 함께") && ui.has("오늘 이야기 듣기") }
            ui.test.runOnMainSync {
                assertTrue(ui.has("이날의 소식 3개"))
                assertTrue(ui.all().any { it.contentDescription == "정아의 소식 보기" })
            }
            ui.screenshot(if (large) "vertical-feed-daily-elder.png" else "vertical-feed-daily.png")
            ui.test.runOnMainSync { ui.all().first { it.contentDescription == "정아의 소식 보기" }.performClick() }
            ui.await { ui.has("참 보기 좋구나.") }
            assertTrue(api.paths().contains("/api/posts/1/"))
        } }
    }

    @Test fun voiceReplyStartsOnlyAfterTheExplicitReplyActionAndBackCancelsIt() {
        val test = androidx.test.platform.app.InstrumentationRegistry.getInstrumentation()
        test.uiAutomation.grantRuntimePermission(test.targetContext.packageName, android.Manifest.permission.RECORD_AUDIO)
        server().use { api -> UiHarness(api, room(77, "우리 가족")).use { ui ->
            ui.await { ui.all().any { it is FeedPostCard } }
            assertTrue(api.paths().none { it.contains("transcribe") || it.contains("replies") })
            ui.selectLetter(1)
            ui.test.runOnMainSync {
                val card = ui.all().filterIsInstance<FeedPostCard>().single { it.post.getInt("id") == 1 }
                ui.all(card).single { it.contentDescription == "말로 댓글" }.performClick()
            }
            ui.await { ui.has("듣고 있어요") && ui.all().any { it.contentDescription == "말하기 마치기" } }
            ui.screenshot("vertical-feed-voice.png")
            ui.test.runOnMainSync { ui.activity.onBackPressedDispatcher.onBackPressed() }
            ui.await { ui.all().any { it is FeedPostCard } }
            assertTrue("Cancelling a voice draft must not upload or send it", api.paths().none { it.contains("transcribe") || it.contains("replies") })
            val field = ui.activity.javaClass.getDeclaredField("recorder").apply { isAccessible = true }
            ui.test.runOnMainSync { assertNull(field.get(ui.activity)) }
        } }
    }
}
