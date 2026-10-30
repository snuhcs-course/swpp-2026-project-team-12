package kr.talkdock.app

import android.content.Context
import android.content.Intent
import android.os.SystemClock
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.view.WindowInsets
import android.view.inspector.WindowInspector
import android.widget.ImageView
import android.widget.ScrollView
import android.widget.TextView
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.filters.SdkSuppress
import androidx.test.runner.lifecycle.ActivityLifecycleMonitorRegistry
import androidx.test.runner.lifecycle.Stage
import kr.talkdock.app.ui.FloatingAssistantView
import kr.talkdock.app.ui.PostQuestionPanel
import kr.talkdock.app.ui.FamilyMemoryPanel
import kr.talkdock.app.ui.AssistantBubbleMenu
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.net.ServerSocket
import java.util.Collections
import java.util.concurrent.Executors

/** Synthetic feed and local HTTP server: no real account or external AI calls. */
@RunWith(AndroidJUnit4::class)
class FloatingAssistantTest {
    private val family = JSONObject().put("id", 77).put("name", "도우미 테스트 가족")
        .put("members", JSONArray()).put("invite_code", "ASSIST")

    private inner class Server : AutoCloseable {
        private val socket = ServerSocket(0)
        private val executor = Executors.newCachedThreadPool()
        val base = "http://127.0.0.1:${socket.localPort}/api/"
        val questionPaths = Collections.synchronizedList(mutableListOf<String>())
        private val thread = Thread {
            while (!socket.isClosed) {
                val client = runCatching { socket.accept() }.getOrNull() ?: break
                executor.execute { client.use { runCatching {
                    val input = client.getInputStream().buffered()
                    fun line(): String {
                        val bytes = java.io.ByteArrayOutputStream()
                        while (true) { val next = input.read(); if (next == -1 || next == 10) break; if (next != 13) bytes.write(next) }
                        return bytes.toString("UTF-8")
                    }
                    val path = line().split(' ')[1]
                    var length = 0
                    while (true) {
                        val header = line(); if (header.isEmpty()) break
                        if (header.startsWith("Content-Length:", true)) length = header.substringAfter(':').trim().toInt()
                    }
                    var remaining = length
                    while (remaining > 0) { if (input.read() == -1) break; remaining-- }
                    val reply = when {
                        path == "/api/families/" -> JSONObject().put("rooms", JSONArray().put(family))
                        path == "/api/families/current/" -> family
                        path == "/api/posts/" -> JSONObject().put("posts", JSONArray((1..3).map { id ->
                            JSONObject().put("id", id).put("author_id", id).put("author_name", "작성자$id")
                                .put("relationship", "가족").put("created_at", "2026-10-26T12:00:00+09:00")
                                .put("caption", "소식 $id\n" + "함께한 하루의 이야기입니다.\n".repeat(8))
                                .put("images", JSONArray()).put("image_url", "").put("image_count", 0).put("comment_count", 0)
                        }))
                        path.startsWith("/api/digests/") -> JSONObject().put("status", "pending").put("digest_time", "21:00")
                        path.endsWith("/questions/") -> { questionPaths.add(path); JSONObject().put("text", "테스트 답변") }
                        else -> JSONObject().put("text", "가족 추억")
                    }.toString().toByteArray(Charsets.UTF_8)
                    client.getOutputStream().apply {
                        write("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: ${reply.size}\r\nConnection: close\r\n\r\n".toByteArray())
                        write(reply); flush()
                    }
                } } }
            }
        }.apply { isDaemon = true; start() }
        override fun close() { socket.close(); executor.shutdownNow(); thread.join(1000) }
    }

    private inner class Screen(server: Server) : AutoCloseable {
        val test = InstrumentationRegistry.getInstrumentation()
        private val sessionPrefs = test.targetContext.getSharedPreferences("talkdock-session", Context.MODE_PRIVATE)
        private val positionPrefs = test.targetContext.getSharedPreferences("talkdock-assistant-letter", Context.MODE_PRIVATE)
        private val savedSession = sessionPrefs.all.toMap()
        private val savedPosition = positionPrefs.all.toMap()
        var activity: MainActivity
        init {
            val user = JSONObject().put("user_id", 999).put("username", "assistant-test")
                .put("token", "local-test-token").put("room", family).put("large", false)
            sessionPrefs.edit().clear().putString("server", server.base).putString("current", user.toString()).commit()
            positionPrefs.edit().clear().commit()
            activity = test.startActivitySync(Intent(test.targetContext, MainActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)) as MainActivity
            await { views().any { it is kr.talkdock.app.ui.PhotoLetterDeck && it.height > 0 } }
        }
        fun views(view: View = activity.window.decorView): List<View> {
            fun walk(root: View): List<View> = listOf(root) + if (root is ViewGroup) (0 until root.childCount).flatMap { walk(root.getChildAt(it)) } else emptyList()
            val result = walk(view).toMutableList()
            if (view === activity.window.decorView) {
                val field = activity.javaClass.getDeclaredField("assistantDialog").apply { isAccessible = true }
                (field.get(activity) as? android.app.Dialog)?.takeIf { it.isShowing }?.window?.decorView?.let { result.addAll(walk(it)) }
            }
            return result
        }
        fun button() = views().filterIsInstance<FloatingAssistantView>().single()
        fun character() = button().getChildAt(0) as ImageView
        fun card(id: Int) = views().filterIsInstance<TextView>().first { it.text.startsWith("소식 $id\n") }.parent as View
        fun menu() = views().filterIsInstance<AssistantBubbleMenu>().single()
        fun tapCharacter() = tap(button())
        fun tap(view: View) {
            val point = IntArray(2); var x = 0f; var y = 0f
            test.runOnMainSync { view.getLocationOnScreen(point); x = point[0] + view.width / 2f; y = point[1] + view.height / 2f }
            val now = SystemClock.uptimeMillis()
            for (action in listOf(MotionEvent.ACTION_DOWN, MotionEvent.ACTION_UP)) {
                MotionEvent.obtain(now, SystemClock.uptimeMillis(), action, x, y, 0).also { test.sendPointerSync(it); it.recycle() }
            }
            test.waitForIdleSync()
        }
        fun await(condition: () -> Boolean) {
            val end = SystemClock.uptimeMillis() + 10000
            while (SystemClock.uptimeMillis() < end) {
                var ready = false; test.runOnMainSync { ready = condition() }
                if (ready) return
                Thread.sleep(40)
            }
            fail("Floating assistant condition timed out")
        }
        fun center(id: Int) {
            test.runOnMainSync {
                val deck = views().filterIsInstance<kr.talkdock.app.ui.PhotoLetterDeck>().single()
                for (index in 0 until deck.letterCount) { deck.show(index); if (deck.currentPost.optInt("id") == id) break }
            }
            await { button().tag == id }
        }
        fun drag(dx: Float, dy: Float, cancel: Boolean = false) = test.runOnMainSync {
            val view = button(); val now = SystemClock.uptimeMillis()
            for ((action, x, y) in listOf(Triple(MotionEvent.ACTION_DOWN, 20f, 20f),
                Triple(MotionEvent.ACTION_MOVE, 20f + dx, 20f + dy),
                Triple(if (cancel) MotionEvent.ACTION_CANCEL else MotionEvent.ACTION_UP, 20f + dx, 20f + dy))) {
                MotionEvent.obtain(now, SystemClock.uptimeMillis(), action, x, y, 0).also {
                    view.dispatchTouchEvent(it); it.recycle()
                }
            }
        }
        fun recreate() {
            val old = activity; test.runOnMainSync { old.recreate() }
            await {
                val next = ActivityLifecycleMonitorRegistry.getInstance().getActivitiesInStage(Stage.RESUMED)
                    .filterIsInstance<MainActivity>().firstOrNull { it !== old }
                if (next != null) activity = next
                next != null && views().any { it is FloatingAssistantView }
            }
            await { views().any { it is kr.talkdock.app.ui.PhotoLetterDeck } }
        }
        private fun restore(prefs: android.content.SharedPreferences, values: Map<String, *>) {
            val editor = prefs.edit().clear()
            values.forEach { (key, value) -> when (value) {
                is String -> editor.putString(key, value)
                is Boolean -> editor.putBoolean(key, value)
                is Int -> editor.putInt(key, value)
                is Float -> editor.putFloat(key, value)
                is Long -> editor.putLong(key, value)
                is Set<*> -> editor.putStringSet(key, value.filterIsInstance<String>().toSet())
            } }
            editor.commit()
        }
        override fun close() {
            test.runOnMainSync { activity.finish() }; test.waitForIdleSync()
            restore(sessionPrefs, savedSession); restore(positionPrefs, savedPosition)
        }
    }

    @Test fun pagingChangesThePostWhileDraggingOnlyMovesTheCharacter() {
        Server().use { server -> Screen(server).use { screen ->
            screen.center(2)
            screen.drag(-1500f, -120f)
            var x = 0f; var y = 0f
            screen.test.runOnMainSync {
                assertEquals(2, screen.button().tag); x = screen.button().x; y = screen.button().y
                assertEquals(1f, screen.character().scaleX, 0f)
            }
            screen.recreate()
            screen.test.runOnMainSync { assertEquals(2, screen.button().tag); assertEquals(x, screen.button().x, 2f); assertEquals(y, screen.button().y, 2f) }
            screen.center(3)
            assertTrue(server.questionPaths.isEmpty())
        } }
    }
    @Test fun dragCancelAndAccessibleMovesDoNotOpenAQuestionOrChangeItsPost() {
        Server().use { server -> Screen(server).use { screen ->
            screen.center(2)
            var initial = 0f
            screen.test.runOnMainSync { initial = screen.button().x }
            screen.drag(-1500f, 500f, cancel = true)
            screen.test.runOnMainSync {
                assertEquals(initial, screen.button().x, 2f)
                assertTrue(screen.button().performAccessibilityAction(FloatingAssistantView.ACTION_LEFT, null))
                assertTrue(screen.button().performAccessibilityAction(FloatingAssistantView.ACTION_UP, null))
                assertEquals(2, screen.button().tag); assertEquals(1f, screen.character().scaleX, 0f)
                assertTrue(screen.button().performAccessibilityAction(FloatingAssistantView.ACTION_RIGHT, null))
                assertEquals(-1f, screen.character().scaleX, 0f)
            }
            assertTrue(server.questionPaths.isEmpty())
        } }
    }
    @Test fun outsideTapAndPagingDismissThePopoverWithoutStartingAi() {
        Server().use { server -> Screen(server).use { screen ->
            screen.tapCharacter(); screen.await { screen.views().any { it is AssistantBubbleMenu } }
            screen.test.runOnMainSync { screen.views().single { it.tag == "assistant-menu-shade" }.performClick() }
            screen.await { screen.views().none { it is AssistantBubbleMenu } }
            screen.tapCharacter(); screen.await { screen.views().any { it is AssistantBubbleMenu } }
            screen.center(1)
            screen.await { screen.views().none { it is AssistantBubbleMenu } }
            assertTrue(server.questionPaths.isEmpty())
        } }
    }
    @Test fun twoActionPopoverFitsBothDockingEdgesAndRetainsAccessibleTargets() {
        Server().use { server -> Screen(server).use { screen ->
            for (edge in listOf(FloatingAssistantView.ACTION_RIGHT, FloatingAssistantView.ACTION_LEFT)) {
                screen.test.runOnMainSync { screen.button().performAccessibilityAction(edge, null) }
                screen.tapCharacter(); screen.await { screen.views().any { it is AssistantBubbleMenu && it.width > 0 } }
                screen.test.runOnMainSync {
                    val menu = screen.menu(); val root = menu.parent as View
                    assertTrue(menu.x >= 0); assertTrue(menu.x + menu.width <= root.width + 1)
                    assertTrue(menu.y >= 0); assertTrue(menu.y + menu.height <= root.height + 1)
                    for (label in listOf("이 소식 물어보기", "가족 추억 찾기")) {
                        val row = screen.views(menu).single { it.contentDescription == label }
                        assertTrue(row.isClickable && row.isFocusable); assertTrue(row.height >= screen.activity.resources.displayMetrics.density * 48)
                    }
                    assertFalse(screen.views(menu).filterIsInstance<TextView>().any { it.text.toString() == "오늘 가족의 하루" })
                    screen.button().performClick()
                }
            }
        } }
    }
    @Test fun memoryOptionAndDailyTabUseSeparateRoutes() {
        Server().use { server -> Screen(server).use { screen ->
            screen.tapCharacter(); screen.await { screen.views().any { it is AssistantBubbleMenu } }
            screen.test.runOnMainSync { screen.views().single { it.contentDescription == "가족 추억 찾기" }.performClick() }
            screen.await { screen.views().any { it is FamilyMemoryPanel } }
            screen.test.runOnMainSync { screen.activity.onBackPressedDispatcher.onBackPressed() }
            screen.await { screen.views().any { it is kr.talkdock.app.ui.PhotoLetterDeck } }
            screen.test.runOnMainSync {
                val label = screen.views().filterIsInstance<TextView>().single { it.text.toString() == "하루" }
                (label.parent as View).performClick()
            }
            screen.await { screen.views().filterIsInstance<TextView>().any { it.text.toString().contains("21:00") } }
            assertTrue(server.questionPaths.isEmpty())
        } }
    }
    @Test fun questionKeepsChosenPostAndASecondQuestionUsesTheNewLetter() {
        Server().use { server -> Screen(server).use { screen ->
            fun openQuestion(id: Int) {
                screen.center(id); screen.tapCharacter()
                screen.await { screen.views().any { it is AssistantBubbleMenu } }
                screen.test.runOnMainSync { screen.views().single { it.contentDescription == "이 소식 물어보기" }.performClick() }
                screen.await { screen.views().any { it is PostQuestionPanel } }
            }
            openQuestion(2)
            screen.center(3)
            screen.test.runOnMainSync {
                val panel = screen.views().filterIsInstance<PostQuestionPanel>().single()
                panel.composer.input.setText("어떤 이야기예요?"); panel.composer.sendButton.performClick()
            }
            screen.await { server.questionPaths.contains("/api/posts/2/questions/") }
            screen.test.runOnMainSync { screen.activity.onBackPressedDispatcher.onBackPressed() }
            screen.await { screen.views().none { it is PostQuestionPanel } }
            openQuestion(1)
            screen.test.runOnMainSync {
                val panel = screen.views().filterIsInstance<PostQuestionPanel>().single()
                assertFalse(screen.views(panel).filterIsInstance<TextView>().any { it.text.toString() == "테스트 답변" })
                panel.composer.input.setText("이건요?"); panel.composer.sendButton.performClick()
            }
            screen.await { server.questionPaths.contains("/api/posts/1/questions/") }
        } }
    }
}
