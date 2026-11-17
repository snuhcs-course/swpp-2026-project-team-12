package kr.talkdock.app

import android.widget.EditText
import android.widget.Spinner
import android.widget.TextView
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class UatAccountFeedbackTest {
    @Test fun registrationKeepsPasswordAndShowsServerReasonBesideIt() {
        MockApi { request -> when (request.path) {
            "/api/speech/voices/" -> jsonReply(JSONObject().put("voices", JSONArray()).put("default", ""))
            "/api/accounts/register/" -> jsonReply(JSONObject().put("error", "너무 흔한 비밀번호예요. 다른 비밀번호를 만들어 주세요.").put("field", "password"), 400)
            else -> jsonReply(JSONObject())
        } }.use { api -> UiHarness(api, null, signedIn = false).use { ui ->
            ui.await { ui.has("토닥 시작하기") }; ui.click("토닥 시작하기")
            ui.test.runOnMainSync {
                val fields = ui.all().filterIsInstance<EditText>()
                fields[0].setText("정순"); fields[1].setText("test-user")
                fields[2].setText("password123"); fields[3].setText("password123")
                ui.all().filterIsInstance<Spinner>().first().setSelection(2)
            }
            ui.click("계정 만들기")
            ui.await { ui.has("너무 흔한 비밀번호예요. 다른 비밀번호를 만들어 주세요.") }
            ui.test.runOnMainSync {
                val password = ui.all().filterIsInstance<EditText>()[2]
                assertEquals("password123", password.text.toString())
                assertNull("Inline guidance must not be covered by a native error popup", password.error)
                val message = ui.all().filterIsInstance<TextView>().first { it.text.toString().startsWith("너무 흔한") }
                assertTrue(message.isShown)
                assertTrue(message.textSize >= password.textSize)
            }
            ui.screenshot("uat-password-error.png")
        } }
    }

    @Test fun invitationCodeDisplaysAndSubmitsUppercase() {
        MockApi(rooms = { jsonReply(JSONObject().put("rooms", JSONArray())) }) { request ->
            if (request.path == "/api/families/lookup/") jsonReply(JSONObject().put("error", "테스트 초대코드"), 400)
            else jsonReply(JSONObject())
        }.use { api -> UiHarness(api, null).use { ui ->
            ui.await { ui.has("초대 코드로 참여하기") }; ui.click("초대 코드로 참여하기")
            ui.test.runOnMainSync {
                val fields = ui.all().filterIsInstance<EditText>()
                fields[0].setText("abc123"); fields[1].setText("family-pass")
                assertEquals("ABC123", fields[0].text.toString())
            }
            ui.click("가족 방 확인하기")
            ui.await { synchronized(api.requests) { api.requests.any { it.path == "/api/families/lookup/" } } }
            val request = synchronized(api.requests) { api.requests.first { it.path == "/api/families/lookup/" } }
            assertEquals("ABC123", JSONObject(request.body).getString("invite_code"))
        } }
    }

    @Test fun changingVoiceDiscardsThePreviousSampleWhileItIsLoading() {
        MockApi { request -> when (request.path) {
            "/api/speech/voices/" -> jsonReply(JSONObject().put("default", "a").put("voices", JSONArray()
                .put(JSONObject().put("key", "a").put("name", "목소리 A").put("sample", true))
                .put(JSONObject().put("key", "b").put("name", "목소리 B").put("sample", false))))
            "/api/speech/voices/a/sample/" -> { Thread.sleep(1000); Reply("not-audio".toByteArray(), 200) }
            else -> jsonReply(JSONObject())
        } }.use { api -> UiHarness(api, null, signedIn = false).use { ui ->
            ui.await { ui.has("토닥 시작하기") }; ui.click("토닥 시작하기")
            ui.await { ui.all().filterIsInstance<Spinner>().any { it.contentDescription == "소식을 읽어 줄 목소리 (선택)" && it.isShown } }
            ui.click("선택한 목소리 미리 듣기")
            ui.await { ui.has("목소리 예시를 준비하고 있어요.") }
            ui.test.runOnMainSync { ui.all().filterIsInstance<Spinner>().last().setSelection(1) }
            Thread.sleep(1500); ui.test.waitForIdleSync()
            assertFalse(ui.has("목소리 예시를 듣고 있어요."))
            assertFalse(ui.has("재생하지 못했어요. 미리 듣기를 다시 눌러 주세요."))
            ui.test.runOnMainSync { ui.all().filterIsInstance<Spinner>().last().setSelection(0) }
            ui.click("선택한 목소리 미리 듣기")
            Thread.sleep(300)
            assertEquals(1, synchronized(api.requests) { api.requests.count { it.path == "/api/speech/voices/a/sample/" } })
        } }
    }
}
