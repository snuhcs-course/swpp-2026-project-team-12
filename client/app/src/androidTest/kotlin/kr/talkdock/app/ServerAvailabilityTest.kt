package kr.talkdock.app

import android.content.Context
import android.os.SystemClock
import android.view.accessibility.AccessibilityNodeInfo
import android.widget.TextView
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.runner.lifecycle.ActivityLifecycleMonitorRegistry
import androidx.test.runner.lifecycle.Stage
import kr.talkdock.app.data.ApiFailureMessages
import kr.talkdock.app.ui.FamilyMemoryPanel
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicBoolean

@RunWith(AndroidJUnit4::class)
class ServerAvailabilityTest {
    private fun maintenance() = Reply("<html>Maintenance</html>".toByteArray(), 503, "text/html")

    @Test fun feedShowsMaintenanceNoticeAndManualRetryRecovers() {
        for (large in listOf(false, true)) {
            val attempts = AtomicInteger()
            MockApi { request -> when (request.path) {
                "/api/families/current/" -> jsonReply(room(1, "점검 안내 테스트"))
                "/api/posts/" -> if (attempts.incrementAndGet() == 1) maintenance() else emptyFeed()
                else -> emptyFeed()
            } }.use { api -> UiHarness(api, room(1, "점검 안내 테스트"), large = large).use { ui ->
                ui.await { ui.has(ApiFailureMessages.UNAVAILABLE) && ui.has("다시 불러오기") }
                ui.test.waitForIdleSync(); SystemClock.sleep(400)
                ui.screenshot(if (large) "maintenance-feed-large.png" else "maintenance-feed.png")
                ui.click("다시 불러오기")
                ui.await { ui.has("첫 소식을 기다리고 있어요") }
                assertEquals(2, attempts.get())
            } }
        }
    }

    @Test fun familySearchKeepsDraftDuringMaintenanceAndRetrySucceeds() {
        val attempts = AtomicInteger()
        MockApi { request -> when (request.path) {
            "/api/families/current/" -> jsonReply(room(1, "점검 안내 테스트"))
            "/api/searching/history/" -> if (attempts.incrementAndGet() == 1) maintenance()
                else jsonReply(JSONObject().put("text", "복구 후 찾은 이야기"))
            else -> emptyFeed()
        } }.use { api -> UiHarness(api, room(1, "점검 안내 테스트")).use { ui ->
            ui.await { ui.has("첫 소식을 기다리고 있어요") }
            ui.click("가족 추억 찾기")
            val draft = "  가족 여행은 어디로 갔었지?  "
            fun panel() = ui.all().filterIsInstance<FamilyMemoryPanel>().single()
            ui.test.runOnMainSync { panel().input.setText(draft); panel().searchButton.performClick() }
            ui.await { ui.has(ApiFailureMessages.UNAVAILABLE) }
            ui.test.runOnMainSync {
                assertEquals(draft, panel().input.text.toString())
                assertTrue(panel().searchButton.isEnabled)
                assertTrue(ui.all().filterIsInstance<TextView>().none { it.isShown && it.text.toString() == "다시 로그인하기" })
            }
            ui.test.waitForIdleSync(); SystemClock.sleep(400); ui.screenshot("maintenance-search.png")
            ui.test.runOnMainSync { panel().searchButton.performClick() }
            ui.await { ui.has("복구 후 찾은 이야기") }
            assertEquals(2, attempts.get())
        } }
    }

    @Test fun startupMaintenanceShowsNoticeWithoutRemovingSavedLogin() {
        val available = AtomicBoolean(false)
        MockApi { request ->
            if (!available.get()) maintenance()
            else if (request.path == "/api/families/current/") jsonReply(room(1, "점검 안내 테스트"))
            else emptyFeed()
        }.use { api -> UiHarness(api, room(1, "점검 안내 테스트")).use { ui ->
            fun contains(node: AccessibilityNodeInfo?, text: String): Boolean {
                if (node == null) return false
                if (node.text?.toString() == text) return true
                return (0 until node.childCount).any { contains(node.getChild(it), text) }
            }
            ui.await {
                val window = ui.test.uiAutomation.rootInActiveWindow
                contains(window, "잠시 이용이 어려워요") && contains(window, ApiFailureMessages.UNAVAILABLE)
            }
            ui.test.runOnMainSync { assertTrue(ui.has("다시 연결하기")) }
            assertNotNull(ui.test.targetContext.getSharedPreferences("talkdock-session", Context.MODE_PRIVATE).getString("current", null))
            assertFalse(api.requests.any { it.path == "/api/posts/" })
            ui.test.waitForIdleSync(); SystemClock.sleep(400); ui.screenshot("maintenance-startup.png")
            available.set(true)
            ui.click("다시 연결하기")
            try {
                ui.await { contains(ui.test.uiAutomation.rootInActiveWindow, "첫 소식을 기다리고 있어요") }
                assertTrue(api.requests.any { it.path == "/api/posts/" })
            } finally {
                ui.test.runOnMainSync {
                    ActivityLifecycleMonitorRegistry.getInstance().getActivitiesInStage(Stage.RESUMED)
                        .filterIsInstance<MainActivity>().forEach { it.finish() }
                }
            }
        } }
    }
}
