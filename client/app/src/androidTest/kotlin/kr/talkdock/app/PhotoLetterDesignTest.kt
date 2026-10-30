package kr.talkdock.app

import android.app.Dialog
import android.graphics.Rect
import android.os.SystemClock
import android.view.MotionEvent
import android.view.View
import android.widget.EditText
import android.widget.ImageView
import android.widget.TextView
import androidx.test.ext.junit.runners.AndroidJUnit4
import kr.talkdock.app.ui.FloatingAssistantView
import kr.talkdock.app.ui.PhotoCarousel
import kr.talkdock.app.ui.PhotoLetterDeck
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
        val photo = test.context.assets.open("photo-letter-fixture.png").use { it.readBytes() }
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
    private fun clickIn(ui: UiHarness, root: View, label: String) = ui.test.runOnMainSync {
        var view: View = ui.all(root).filterIsInstance<TextView>().first { it.text.toString() == label }
        while (!view.isClickable && view.parent is View) view = view.parent as View
        assertTrue(view.performClick())
    }
    private fun swipeLeft(ui: UiHarness, view: View) {
        val bounds = Rect()
        ui.test.runOnMainSync { assertTrue(view.getGlobalVisibleRect(bounds)) }
        val down = SystemClock.uptimeMillis()
        for (step in 0..14) {
            val action = when (step) { 0 -> MotionEvent.ACTION_DOWN; 14 -> MotionEvent.ACTION_UP; else -> MotionEvent.ACTION_MOVE }
            val event = MotionEvent.obtain(down, SystemClock.uptimeMillis(), action,
                bounds.left + bounds.width() * (.8f - step / 14f * .6f), bounds.top + bounds.height() * .35f, 0)
            ui.test.uiAutomation.injectInputEvent(event, true); event.recycle(); Thread.sleep(15)
        }
    }

    @Test fun horizontalLettersKeepTheirOwnBotContextAndOpenAllPhotosInDetail() {
        server().use { api -> UiHarness(api, room(77, "우리 가족")).use { ui ->
            ui.await { ui.all().any { it is PhotoLetterDeck } }
            lateinit var deck: PhotoLetterDeck
            ui.test.runOnMainSync { deck = ui.all().filterIsInstance<PhotoLetterDeck>().single() }
            ui.await { ui.all(deck.currentCard).filterIsInstance<ImageView>().any { it.drawable != null } }
            ui.test.runOnMainSync {
                assertEquals(1, deck.currentPost.getInt("id"))
                val primary = ui.all(deck).first { it.contentDescription == "말로 답장하기" }
                val visible = Rect(); assertTrue(primary.getGlobalVisibleRect(visible)); assertEquals(primary.height, visible.height())
                assertFalse(ui.has("AI 요약")); assertFalse(ui.has("댓글 1")); assertFalse(ui.has("가족방")); assertFalse(ui.has("설정"))
            }
            Thread.sleep(500); ui.screenshot("photo-letter-home.png")
            swipeLeft(ui, deck)
            ui.await { deck.currentPost.optInt("id") == 2 && ui.all().filterIsInstance<FloatingAssistantView>().single().tag == 2 }
            assertTrue("Browsing must not start AI requests", api.paths().none { it.contains("questions") || it.contains("summary") || it.contains("speech") })
            ui.test.runOnMainSync { ui.all().filterIsInstance<FloatingAssistantView>().single().performClick() }
            ui.await { ui.has("이 소식 물어보기") && ui.has("가족 추억 찾기") }
            assertFalse(ui.has("오늘 가족의 하루"))
            ui.screenshot("photo-letter-bot-menu.png")
            ui.click("이 소식 물어보기")
            ui.await { dialog(ui, "assistantDialog")?.isShowing == true }
            val question = dialog(ui, "assistantDialog")!!
            ui.test.runOnMainSync {
                assertTrue(ui.all(question.window!!.decorView).filterIsInstance<TextView>().any { it.text.toString() == "아빠의 소식" })
                ui.all(question.window!!.decorView).filterIsInstance<EditText>().single().setText("누구의 소식이야?")
                ui.all(question.window!!.decorView).first { it.contentDescription == "질문 보내기" }.performClick()
            }
            ui.await { ui.all(question.window!!.decorView).filterIsInstance<TextView>().any { it.text.toString().contains("아빠가 저녁") } }
            assertTrue(api.paths().contains("/api/posts/2/questions/"))
            ui.screenshot("photo-letter-bot-question.png")
            ui.test.runOnMainSync { question.dismiss(); deck.show(0) }
            ui.test.runOnMainSync { ui.all(deck.currentCard).first { it.isClickable && it.contentDescription?.contains("누르면 상세 보기") == true }.performClick() }
            ui.await { ui.all().any { it is PhotoCarousel } && ui.has("참 보기 좋구나.") }
            ui.test.runOnMainSync { assertEquals(1, ui.all().filterIsInstance<PhotoCarousel>().size) }
            assertTrue(api.paths().contains("/api/posts/1/"))
            ui.await { ui.all(ui.all().filterIsInstance<PhotoCarousel>().single()).filterIsInstance<ImageView>().first().drawable != null }
            ui.screenshot("photo-letter-detail.png")
        } }
    }

    @Test fun profileOwnsSettingsAndDailyIsAvailableInBothTextSizes() {
        for (large in listOf(false, true)) server().use { api -> UiHarness(api, room(77, "우리 가족"), large).use { ui ->
            ui.await { ui.all().any { it is PhotoLetterDeck } }
            ui.test.runOnMainSync { ui.all().first { it.contentDescription == "프로필 메뉴" }.performClick() }
            ui.await { dialog(ui, "profileMenuDialog")?.isShowing == true }
            val profile = dialog(ui, "profileMenuDialog")!!
            clickIn(ui, profile.window!!.decorView, "설정")
            ui.await { ui.has("내 계정 수정") }
            ui.test.runOnMainSync { ui.all().first { it.contentDescription == "이전 화면" }.performClick() }
            ui.await { ui.all().any { it is PhotoLetterDeck } }
            ui.click("하루")
            ui.await { ui.has("오늘도, 함께") && ui.has("오늘 이야기 듣기") }
            ui.test.runOnMainSync {
                assertTrue(ui.has("이날의 소식 3개")); assertFalse(ui.has("설정"))
                assertTrue(ui.all().any { it.contentDescription == "정아의 소식 보기" })
            }
            ui.await { ui.all().filterIsInstance<ImageView>().count { it.contentDescription?.contains("님의 사진") == true && it.drawable != null } == 2 }
            Thread.sleep(400); ui.screenshot(if (large) "photo-letter-daily-large.png" else "photo-letter-daily.png")
            ui.test.runOnMainSync { ui.all().first { it.contentDescription == "정아의 소식 보기" }.performClick() }
            ui.await { ui.has("참 보기 좋구나.") }
            assertTrue(api.paths().contains("/api/posts/1/"))
        } }
    }

    @Test fun voiceReplyStartsOnlyAfterTheExplicitReplyActionAndBackCancelsIt() {
        val test = androidx.test.platform.app.InstrumentationRegistry.getInstrumentation()
        test.uiAutomation.executeShellCommand("pm grant kr.talkdock.app android.permission.RECORD_AUDIO").use {
            android.os.ParcelFileDescriptor.AutoCloseInputStream(it).readBytes()
        }
        server().use { api -> UiHarness(api, room(77, "우리 가족")).use { ui ->
            ui.await { ui.all().any { it is PhotoLetterDeck } }
            assertTrue(api.paths().none { it.contains("transcribe") || it.contains("replies") })
            ui.click("말로 답장하기")
            ui.await { ui.has("듣고 있어요") && ui.all().any { it.contentDescription == "말하기 마치기" } }
            Thread.sleep(800); ui.screenshot("photo-letter-voice.png")
            ui.test.runOnMainSync { ui.activity.onBackPressedDispatcher.onBackPressed() }
            ui.await { ui.all().any { it is PhotoLetterDeck } }
            assertTrue("Cancelling a voice draft must not upload or send it", api.paths().none { it.contains("transcribe") || it.contains("replies") })
            val field = ui.activity.javaClass.getDeclaredField("recorder").apply { isAccessible = true }
            ui.test.runOnMainSync { assertNull(field.get(ui.activity)) }
        } }
    }
}
