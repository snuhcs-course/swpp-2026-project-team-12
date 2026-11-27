package kr.talkdock.app

import android.content.Context
import android.content.Intent
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout
import androidx.test.ext.junit.runners.AndroidJUnit4
import kr.talkdock.app.data.ApiFailureMessages
import kr.talkdock.app.notifications.TodakNotifications
import kr.talkdock.app.ui.FeedPostCard
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.util.concurrent.atomic.AtomicBoolean

/** PR #89 review: a failed request must not hide a feed that is already on screen. */
@RunWith(AndroidJUnit4::class)
class FeedFailureNoticeTest {
    private val family = room(1, "알림 테스트 가족")
    private fun post(id: Int) = JSONObject().put("id", id).put("author_id", 40 + id).put("author_name", "지우$id")
        .put("relationship", "손녀").put("caption", "오늘은 공원에서 단풍을 봤어요 $id").put("created_at", "2026-11-20T10:00:00+09:00")
        .put("images", JSONArray()).put("comment_count", 0)
    private fun badGateway() = Reply("<html>502 Bad Gateway</html>".toByteArray(), 502, "text/html")

    private fun UiHarness.feedCards() = all().filterIsInstance<FeedPostCard>().count { it.isShown }
    private fun UiHarness.invoke(name: String, vararg args: Pair<Class<*>, Any?>) = test.runOnMainSync {
        MainActivity::class.java.getDeclaredMethod(name, *args.map { it.first }.toTypedArray())
            .apply { isAccessible = true }.invoke(activity, *args.map { it.second }.toTypedArray())
    }
    private fun UiHarness.returnToFeed() = invoke("home", SwipeRefreshLayout::class.java to null)

    private fun feedServer(failFeed: AtomicBoolean, failPost: AtomicBoolean = AtomicBoolean(false)) = MockApi { request -> when {
        request.path == "/api/families/current/" -> jsonReply(family)
        request.path == "/api/posts/" -> if (failFeed.get()) badGateway() else jsonReply(JSONObject().put("posts", JSONArray().put(post(1)).put(post(2))))
        request.path == "/api/posts/2/" -> if (failPost.get()) badGateway() else jsonReply(post(2).put("comments", JSONArray()))
        else -> jsonReply(JSONObject())
    } }

    @Test fun failedRefreshKeepsTheFeedWithAPinnedRetryBanner() {
        val failing = AtomicBoolean(false)
        feedServer(failing).use { api -> UiHarness(api, family, tutorialSeen = true).use { ui ->
            ui.await { ui.feedCards() == 2 }
            failing.set(true)
            ui.returnToFeed()
            ui.await { ui.all().any { it.tag == "feed-refresh-notice" && it.isShown } }
            assertEquals("The earlier feed stays on screen", 2, ui.feedCards())
            assertTrue(ui.has(ApiFailureMessages.Task.FEED_REFRESH.title))
            assertTrue(ui.has(ApiFailureMessages.Cause.SERVER.line))
            assertFalse(ui.has(ApiFailureMessages.Task.FEED.title))  // not the full-screen feed error
            ui.screenshot("feed-refresh-banner.png")
            failing.set(false)
            ui.click("다시 불러오기")
            ui.await { ui.all().none { it.tag == "feed-refresh-notice" } }
            assertEquals(2, ui.feedCards())
        } }
    }

    @Test fun failedNotificationKeepsTheFeedAndRetriesTheSamePost() {
        val failPost = AtomicBoolean(true)
        val context = androidx.test.platform.app.InstrumentationRegistry.getInstrumentation().targetContext
        val push = context.getSharedPreferences("talkdock-push", Context.MODE_PRIVATE)
        val savedBinding = push.getString("binding", null)
        push.edit().putString("binding", "test-binding").commit()
        try {
            feedServer(AtomicBoolean(false), failPost).use { api -> UiHarness(api, family, tutorialSeen = true).use { ui ->
                ui.await { ui.feedCards() == 2 }
                // The same extras the real notification's tap intent carries (TodakNotifications).
                val open = Intent(context, MainActivity::class.java).putExtra(TodakNotifications.EXTRA, true)
                    .putExtra("event_id", "event-1").putExtra("binding", "test-binding").putExtra("user_id", "999")
                    .putExtra("room_id", "1").putExtra("post_id", "2").putExtra("kind", "comment")
                ui.invoke("onNewIntent", Intent::class.java to open)
                val dialogText = { text: String -> ui.test.uiAutomation.rootInActiveWindow
                    ?.findAccessibilityNodeInfosByText(text)?.isNotEmpty() == true }
                ui.await { dialogText(ApiFailureMessages.Task.NOTIFICATION.title) && dialogText("다시 열기") }
                ui.screenshot("notification-failure.png")
                assertEquals("The loaded feed is not replaced by the feed error screen", 2, ui.feedCards())
                assertFalse(ui.has(ApiFailureMessages.Task.FEED.title))
                val failedRequests = api.requests.count { it.path == "/api/posts/2/" }
                failPost.set(false)
                val retry = ui.test.uiAutomation.rootInActiveWindow.findAccessibilityNodeInfosByText("다시 열기").first()
                assertTrue(retry.performAction(android.view.accessibility.AccessibilityNodeInfo.ACTION_CLICK))
                ui.await { ui.hasPostDetail() }
                assertTrue(ui.has("오늘은 공원에서 단풍을 봤어요 2"))
                // 다시 열기 fetched the same post again (the detail screen may then load it once more).
                assertTrue(api.requests.count { it.path == "/api/posts/2/" } > failedRequests)
            } }
        } finally {
            push.edit().putString("binding", savedBinding).commit()
        }
    }
}
