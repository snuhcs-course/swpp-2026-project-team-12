package kr.talkdock.app

import android.content.Context
import android.widget.EditText
import android.widget.Spinner
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

/** Settings, account editing, registration, and account switching against the mock API. */
@RunWith(AndroidJUnit4::class)
class AccountScreensTest {
    private fun account(id: Int, username: String, name: String, token: String) =
        JSONObject().put("user_id", id).put("username", username).put("name", name).put("token", token)

    private fun UiHarness.fields() = all().filterIsInstance<EditText>()
    private fun MockApi.requestsTo(path: String) = synchronized(requests) { requests.filter { it.path == path } }

    @Test fun settingsShowRoomInviteMembersAndOwnerTools() {
        MockApi { request -> when (request.path) {
            "/api/families/current/" -> jsonReply(room(1, "설정 가족"))
            "/api/accounts/logout/" -> jsonReply(JSONObject().put("ok", true))
            else -> emptyFeed()
        } }.use { api -> UiHarness(api, room(1, "설정 가족")).use { ui ->
            ui.await { ui.has("첫 소식을 기다리고 있어요") }
            ui.click("설정"); ui.await { ui.has("가족을 초대해 보세요") }
            ui.test.runOnMainSync {
                assertTrue(ui.has("테스트 사용자님")); assertTrue(ui.has("초대 코드  REVIEW"))
                assertTrue("The owner can change the digest time", ui.has("하루 요약 시간  ·  21:00"))
                assertTrue(ui.has("나")); assertTrue(ui.has("큰 글씨로 보기"))
            }
            ui.click("큰 글씨로 보기"); ui.await { ui.has("기본 글씨로 보기") }
            val prefs = ui.test.targetContext.getSharedPreferences("talkdock-session", Context.MODE_PRIVATE)
            assertTrue(JSONObject(prefs.getString("current", "{}")!!).optBoolean("large"))
            ui.click("로그아웃"); ui.await { ui.has("토닥 시작하기") }
            assertEquals("mock-review-token", api.requestsTo("/api/accounts/logout/").single().token)
            assertNull("Logging out removes the saved session", prefs.getString("current", null))
        } }
    }

    @Test fun editAccountValidatesPasswordAndSavesTheRotatedToken() {
        MockApi { request -> when (request.path) {
            "/api/families/current/" -> jsonReply(room(1, "수정 가족"))
            "/api/accounts/me/" -> jsonReply(account(999, "review-user", "새 이름", "rotated-token"))
            else -> emptyFeed()
        } }.use { api -> UiHarness(api, room(1, "수정 가족")).use { ui ->
            ui.await { ui.has("첫 소식을 기다리고 있어요") }
            ui.click("설정"); ui.await { ui.has("내 계정 수정") }
            ui.click("내 계정 수정"); ui.await { ui.has("수정 내용 저장하기") }
            ui.test.runOnMainSync {
                assertTrue(ui.has("아이디: review-user · 변경할 수 없어요."))
                val (name, current, replacement) = ui.fields()
                assertEquals("테스트 사용자", name.text.toString())
                name.setText("새 이름"); current.setText("Old-pass-123"); replacement.setText("short")
            }
            ui.click("수정 내용 저장하기")
            ui.test.runOnMainSync { assertNotNull(ui.fields()[2].error) }
            assertTrue("An invalid new password must not be sent", api.requestsTo("/api/accounts/me/").isEmpty())
            ui.test.runOnMainSync { ui.fields()[2].setText("Better-pass-456") }
            ui.click("수정 내용 저장하기"); ui.await { ui.has("새 이름님") }
            val sent = JSONObject(api.requestsTo("/api/accounts/me/").single().body)
            assertEquals("새 이름", sent.getString("name"))
            assertEquals("Old-pass-123", sent.getString("current_password"))
            assertEquals("Better-pass-456", sent.getString("new_password"))
            assertEquals("Later requests must use the rotated token", "rotated-token", api.requestsTo("/api/families/current/").last().token)
        } }
    }

    @Test fun registerValidatesInputAndOpensTheRoomChoice() {
        MockApi { request -> when (request.path) {
            "/api/accounts/register/" -> jsonReply(account(5, "new-user", "새 가족", "new-token"), 201)
            "/api/families/current/" -> jsonReply(JSONObject().put("error", "가족방 없음"), 403)
            else -> emptyFeed()
        } }.use { api -> UiHarness(api, null, signedIn = false).use { ui ->
            ui.await { ui.has("토닥 시작하기") }
            ui.click("토닥 시작하기"); ui.await { ui.has("계정 만들기") && ui.fields().size == 3 }
            ui.click("계정 만들기")
            ui.test.runOnMainSync {
                val (name, username, password) = ui.fields()
                name.setText("새 가족"); username.setText("new-user"); password.setText("short")
            }
            ui.click("계정 만들기")  // rejected: no gender chosen yet
            ui.test.runOnMainSync { ui.all().filterIsInstance<Spinner>().single().setSelection(2) }
            ui.click("계정 만들기")
            ui.test.runOnMainSync { assertNotNull(ui.fields()[2].error) }
            assertTrue("Blank, genderless, or short-password forms must not be sent", api.requestsTo("/api/accounts/register/").isEmpty())
            ui.test.runOnMainSync { ui.fields()[2].setText("Family-pass-789") }
            ui.click("계정 만들기"); ui.await { ui.has("새 가족방 만들기") && ui.has("초대 코드로 참여하기") }
            val sent = JSONObject(api.requestsTo("/api/accounts/register/").single().body)
            assertEquals(listOf("new-user", "Family-pass-789", "새 가족", "female"),
                listOf(sent.getString("username"), sent.getString("password"), sent.getString("name"), sent.getString("gender")))
            assertEquals("new-token", api.requestsTo("/api/families/").last().token)
        } }
    }

    @Test fun phoneAccountsListSwitchesToAnotherAccountAndItsRoom() {
        val other = account(777, "other-user", "다른 가족", "other-token").put("room", room(2, "가족 B"))
        MockApi(rooms = { request -> jsonReply(JSONObject().put("rooms", org.json.JSONArray().put(
            if (request.token == "other-token") roomSummary(2, "가족 B") else roomSummary(1, "가족 A")))) }) { request ->
            when (request.path) {
                "/api/families/current/" -> jsonReply(if (request.room == "2") room(2, "가족 B") else room(1, "가족 A"))
                else -> emptyFeed()
            }
        }.use { api -> UiHarness(api, room(1, "가족 A"), others = listOf(other)).use { ui ->
            ui.await { ui.has("첫 소식을 기다리고 있어요") }
            ui.click("설정"); ui.await { ui.has("이 휴대폰의 다른 계정으로 보기") }
            ui.click("이 휴대폰의 다른 계정으로 보기"); ui.await { ui.has("누구의 화면을 볼까요?") }
            ui.test.runOnMainSync {
                assertTrue(ui.has("테스트 사용자 (review-user) · 가족 A"))
                assertTrue(ui.has("다른 계정으로 로그인")); assertTrue(ui.has("새 계정 만들기"))
            }
            ui.click("다른 가족 (other-user) · 가족 B"); ui.await { ui.has("가족 B") && ui.has("첫 소식을 기다리고 있어요") }
            val feed = api.requestsTo("/api/posts/").last()
            assertEquals(listOf("other-token", "2"), listOf(feed.token, feed.room))
        } }
    }
}
