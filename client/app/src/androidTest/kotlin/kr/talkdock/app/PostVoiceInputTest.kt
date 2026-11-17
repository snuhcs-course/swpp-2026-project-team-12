package kr.talkdock.app

import android.widget.EditText
import androidx.test.ext.junit.runners.AndroidJUnit4
import kr.talkdock.app.ui.PostVoiceInput
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

@RunWith(AndroidJUnit4::class)
class PostVoiceInputTest {
    private fun transcribe(ui: UiHarness) {
        val audio = File(ui.activity.cacheDir, "post-voice-test.m4a").apply { writeBytes(ByteArray(128)) }
        ui.test.runOnMainSync {
            val view = ui.all().filterIsInstance<PostVoiceInput>().single()
            PostVoiceInput::class.java.getDeclaredMethod("transcribe", File::class.java).apply { isAccessible = true }.invoke(view, audio)
        }
    }

    @Test fun postVoiceIsReviewedEditedAndAppendedWithoutPublishing() {
        for (large in listOf(false, true)) {
            val family = room(1, "따뜻한 우리 가족")
            MockApi { request -> when (request.path) {
                "/api/families/current/" -> jsonReply(family)
                "/api/speech/transcribe/" -> jsonReply(JSONObject().put("recognized", "오늘은 공원에서 산책했어요."))
                else -> emptyFeed()
            } }.use { api -> UiHarness(api, family, large, tutorialSeen = true).use { ui ->
                ui.await { ui.has("첫 소식을 기다리고 있어요") }
                ui.click("첫 소식 쓰기"); ui.await { ui.has("말로 쓰기") }
                ui.test.runOnMainSync { ui.all().filterIsInstance<EditText>().single().setText("가족 여러분 안녕하세요.") }
                transcribe(ui); ui.await { ui.has("글에 넣기") }
                ui.test.runOnMainSync {
                    assertEquals("가족 여러분 안녕하세요.", ui.all().filterIsInstance<EditText>().first().text.toString())
                    ui.all().filterIsInstance<EditText>().single { it.tag == "post-voice-transcript" }.setText("오늘은 공원에서 함께 산책했어요.")
                }
                ui.screenshot(if (large) "he-voice-review-large.png" else "he-voice-review.png")
                ui.click("글에 넣기")
                ui.test.runOnMainSync {
                    assertEquals("가족 여러분 안녕하세요.\n오늘은 공원에서 함께 산책했어요.", ui.all().filterIsInstance<EditText>().single().text.toString())
                }
                assertFalse(api.requests.any { it.method == "POST" && it.path == "/api/posts/" })
                assertTrue(api.requests.single { it.path == "/api/speech/transcribe/" }.room == "1")
            } }
        }
    }

    @Test fun failedTranscriptionKeepsThePostAndLetsTheUserRetry() {
        val family = room(1, "음성 다시 쓰기")
        MockApi { request -> when (request.path) {
            "/api/families/current/" -> jsonReply(family)
            "/api/speech/transcribe/" -> jsonReply(JSONObject().put("error", "짧게 다시 말해 주세요."), 400)
            else -> emptyFeed()
        } }.use { api -> UiHarness(api, family, tutorialSeen = true).use { ui ->
            ui.await { ui.has("첫 소식을 기다리고 있어요") }; ui.click("첫 소식 쓰기")
            ui.test.runOnMainSync { ui.all().filterIsInstance<EditText>().single().setText("작성 중인 글") }
            transcribe(ui); ui.await { ui.has("다시 말해 주세요\n짧게 다시 말해 주세요.") }
            ui.test.runOnMainSync {
                assertEquals("작성 중인 글", ui.all().filterIsInstance<EditText>().single().text.toString())
                assertTrue(ui.all().filterIsInstance<android.widget.Button>().single { it.text == "말로 쓰기" }.isEnabled)
            }
        } }
    }
}
