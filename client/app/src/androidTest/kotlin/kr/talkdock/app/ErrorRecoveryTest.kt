package kr.talkdock.app

import android.Manifest
import android.view.View
import android.view.accessibility.AccessibilityNodeInfo
import android.widget.EditText
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

@RunWith(AndroidJUnit4::class)
class ErrorRecoveryTest {
    private fun nodes(root: AccessibilityNodeInfo?): List<AccessibilityNodeInfo> = if (root == null) emptyList() else
        listOf(root) + (0 until root.childCount).flatMap { nodes(root.getChild(it)) }

    @Test fun voiceErrorNamesTheActionAndCanRestartRecordingDirectly() {
        val family = room(1, "따뜻한 우리 가족")
        MockApi { request -> when (request.path) {
            "/api/families/current/" -> jsonReply(family)
            "/api/posts/1/replies/transcribe/" -> jsonReply(JSONObject().put("error", "말씀을 듣지 못했어요. 짧게 다시 말해 주세요."), 400)
            else -> emptyFeed()
        } }.use { api -> UiHarness(api, family, tutorialSeen = true).use { ui ->
            ui.await { ui.has("첫 소식을 기다리고 있어요") }
            ui.test.uiAutomation.grantRuntimePermission(ui.activity.packageName, Manifest.permission.RECORD_AUDIO)
            val post = JSONObject().put("id", 1).put("author_name", "준하").put("caption", "오늘은 공원을 산책했어요.").put("images", JSONArray())
            ui.test.runOnMainSync {
                MainActivity::class.java.getDeclaredMethod("voice", JSONObject::class.java, Boolean::class.javaPrimitiveType)
                    .apply { isAccessible = true }.invoke(ui.activity, post, false)
            }
            ui.await { ui.has("듣고 있어요") }
            Thread.sleep(1000)
            ui.test.runOnMainSync {
                (MainActivity::class.java.getDeclaredField("voiceButton").apply { isAccessible = true }.get(ui.activity) as View).performClick()
            }
            ui.await { nodes(ui.test.uiAutomation.rootInActiveWindow).any { it.text?.toString() == "다시 말해 주세요" } }
            val audio = MainActivity::class.java.getDeclaredField("recording").apply { isAccessible = true }.get(ui.activity) as File
            assertTrue("The rejected recording remains available until the user chooses how to recover", audio.exists())
            ui.screenshot("he-error-voice.png")
            val retry = nodes(ui.test.uiAutomation.rootInActiveWindow).single { it.text?.toString() == "다시 말하기" }
            assertTrue(retry.performAction(AccessibilityNodeInfo.ACTION_CLICK))
            ui.await { ui.has("듣고 있어요") }
            assertFalse("Rerecording removes the rejected audio", audio.exists())
            assertFalse(api.requests.any { it.path == "/api/posts/" && it.method == "POST" })
        } }
    }

    @Test fun invalidPostHasAnActionTitleAndPreservesTheWrittenDraft() {
        val family = room(1, "소식 다시 쓰기")
        MockApi { request -> when {
            request.path == "/api/families/current/" -> jsonReply(family)
            request.method == "POST" && request.path == "/api/posts/" -> jsonReply(JSONObject().put("error", "이야기를 조금 줄여 주세요."), 400)
            else -> emptyFeed()
        } }.use { api -> UiHarness(api, family, tutorialSeen = true).use { ui ->
            ui.await { ui.has("첫 소식을 기다리고 있어요") }; ui.click("첫 소식 쓰기")
            ui.test.runOnMainSync { ui.all().filterIsInstance<EditText>().single().setText("가족에게 전할 이야기") }
            ui.click("가족에게 전하기")
            ui.await { nodes(ui.test.uiAutomation.rootInActiveWindow).any { it.text?.toString() == "소식 내용을 확인해 주세요" } }
            assertTrue(nodes(ui.test.uiAutomation.rootInActiveWindow).single { it.text?.toString() == "확인" }.performAction(AccessibilityNodeInfo.ACTION_CLICK))
            ui.test.runOnMainSync { assertEquals("가족에게 전할 이야기", ui.all().filterIsInstance<EditText>().single().text.toString()) }
        } }
    }
}
