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
        private val positionPrefs = test.targetContext.getSharedPreferences("talkdock-assistant", Context.MODE_PRIVATE)
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
            await { views().filterIsInstance<TextView>().any { it.text.startsWith("소식 1\n") && (it.parent as View).height > 0 } }
        }
        fun views(view: View = activity.window.decorView): List<View> = listOf(view) +
            if (view is ViewGroup) (0 until view.childCount).flatMap { views(view.getChildAt(it)) } else emptyList()
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
                val card = views().filterIsInstance<TextView>().first { it.text.startsWith("소식 $id\n") }.parent as View
                val scroll = views().filterIsInstance<ScrollView>().first()
                val cardAt = IntArray(2); val scrollAt = IntArray(2)
                card.getLocationOnScreen(cardAt); scroll.getLocationOnScreen(scrollAt)
                scroll.scrollTo(0, scroll.scrollY + cardAt[1] + card.height / 2 - scrollAt[1] - scroll.height / 2)
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
            await { views().filterIsInstance<TextView>().any { it.text.startsWith("소식 1\n") } }
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

    @Test fun scrollingChangesTheCenteredPostWhileDraggingOnlyMovesTheCharacter() {
        Server().use { server -> Screen(server).use { screen ->
            screen.center(2)
            var oldY = 0f
            screen.test.runOnMainSync {
                oldY = screen.button().y
                assertTrue(screen.button().x > screen.activity.resources.displayMetrics.widthPixels / 2)
                assertEquals(-1f, screen.character().scaleX, 0f)
                assertFalse(screen.card(2).isActivated)
                val density = screen.activity.resources.displayMetrics.density
                assertEquals(91.2f * density, screen.button().width.toFloat(), 1.5f)
                assertEquals(105.6f * density, screen.button().height.toFloat(), 1.5f)
                assertTrue(screen.views().none { it.tag == "post-focus-shade" })
                assertEquals((screen.button().parent as View).width.toFloat(), screen.button().x + screen.button().width, 1f)
                val bodyCut = floatArrayOf(screen.character().drawable.intrinsicWidth * 50f / 1151f, 0f)
                screen.character().imageMatrix.mapPoints(bodyCut)
                assertEquals(0f, bodyCut[0], .01f)
            }
            screen.center(1)
            screen.test.runOnMainSync {
                assertEquals(oldY, screen.button().y, 1f)
                assertFalse(screen.card(1).isActivated)
                assertFalse(screen.card(2).isActivated)
            }
            screen.drag(-2000f, -150f)
            screen.await { screen.button().x < screen.activity.resources.displayMetrics.widthPixels / 2 }
            screen.test.runOnMainSync {
                assertEquals(1, screen.button().tag)
                assertEquals(1f, screen.character().scaleX, 0f)
                assertEquals(0f, screen.button().x, 1f)
            }
            assertTrue(server.questionPaths.isEmpty())
            screen.recreate()
            screen.await { screen.button().x < screen.activity.resources.displayMetrics.widthPixels / 2 }
            screen.center(3)
            screen.test.runOnMainSync {
                assertEquals(3, screen.button().tag)
                assertEquals(1f, screen.character().scaleX, 0f)
            }
        } }
    }

    @Test fun dragCancelAndAccessibleMovesDoNotOpenAQuestionOrChangeItsPost() {
        Server().use { server -> Screen(server).use { screen ->
            screen.center(2)
            var initialX = 0f
            screen.test.runOnMainSync { initialX = screen.button().x }
            screen.drag(-1500f, 500f, cancel = true)
            screen.test.runOnMainSync {
                assertEquals(initialX, screen.button().x, 1f)
                assertEquals(-1f, screen.character().scaleX, 0f)
                assertTrue(screen.button().performAccessibilityAction(FloatingAssistantView.ACTION_LEFT, null))
                assertTrue(screen.button().performAccessibilityAction(FloatingAssistantView.ACTION_UP, null))
                assertEquals(2, screen.button().tag)
                assertEquals(1f, screen.character().scaleX, 0f)
                assertTrue(screen.button().performAccessibilityAction(FloatingAssistantView.ACTION_RIGHT, null))
                assertEquals(-1f, screen.character().scaleX, 0f)
            }
            assertTrue(server.questionPaths.isEmpty())
        } }
    }

    @Test @SdkSuppress(minSdkVersion = 30)
    fun focusShadeDoesNotBlockFeedSwipesOrHeaderButtons() {
        Server().use { server -> Screen(server).use { screen ->
            screen.center(2)
            screen.tapCharacter()
            val at = IntArray(2); var width = 0; var height = 0
            screen.test.runOnMainSync {
                val shade = screen.views().single { it.tag == "post-focus-shade" }
                assertFalse(shade.isClickable); assertFalse(shade.isFocusable)
                val scroll = screen.views().filterIsInstance<ScrollView>().first()
                scroll.getLocationOnScreen(at); width = scroll.width; height = scroll.height
            }
            val now = SystemClock.uptimeMillis()
            for (step in 0..16) {
                val x = at[0] + width * .25f
                val y = at[1] + height * (.2f - .6f * step / 16f)
                val action = if (step == 0) MotionEvent.ACTION_DOWN else if (step == 16) MotionEvent.ACTION_UP else MotionEvent.ACTION_MOVE
                MotionEvent.obtain(now, SystemClock.uptimeMillis(), action, x, y, 0).also { screen.test.sendPointerSync(it); it.recycle() }
                SystemClock.sleep(12)
            }
            screen.await { screen.button().tag == 1 }
            val old = screen.card(1)
            screen.tap(screen.views().first { it.contentDescription == "가족 소식 새로고침" })
            screen.await {
                !old.isAttachedToWindow && screen.views().filterIsInstance<TextView>().any { it.text.startsWith("소식 1\n") } && screen.button().tag != null
            }
            screen.test.runOnMainSync { assertTrue(screen.views().none { it.tag == "post-focus-shade" }) }
            assertTrue(server.questionPaths.isEmpty())
        } }
    }

    @Test @SdkSuppress(minSdkVersion = 30)
    fun characterTogglesAnAnchoredBubbleWithoutBlockingTheFeed() {
        Server().use { server -> Screen(server).use { screen ->
            screen.center(2)
            screen.tapCharacter()
            screen.await { screen.views().any { it is AssistantBubbleMenu && it.width > 0 } }
            screen.test.runOnMainSync {
                val menu = screen.menu(); val button = screen.button()
                assertTrue(screen.card(2).isActivated)
                assertTrue(screen.views().any { it.tag == "post-focus-shade" })
                assertTrue(menu.x + menu.width < button.x + button.width / 4f)
                assertEquals(button.bubbleAttachmentX(), menu.x + menu.width, 1f)
                assertTrue(menu.width < (button.parent as View).width)
                assertTrue(menu.width <= (224 * screen.activity.resources.displayMetrics.density).toInt())
                assertTrue(menu.height < (button.parent as View).height / 2)
                val labels = screen.views(menu).filterIsInstance<TextView>()
                assertEquals(3, labels.size)
                assertTrue(labels.all { it.gravity and android.view.Gravity.HORIZONTAL_GRAVITY_MASK == android.view.Gravity.RIGHT })
                assertEquals(3, labels.map { it.background }.toSet().size)
                assertTrue(screen.views().filterIsInstance<TextView>().any { it.text.toString() == "가족의 지난 추억이 궁금하세요?" })
            }
            screen.test.waitForIdleSync(); SystemClock.sleep(250)
            screen.test.uiAutomation.takeScreenshot().also { bitmap ->
                java.io.File(screen.test.targetContext.cacheDir, "assistant-bubble-preview.png").outputStream().use {
                    bitmap.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, it)
                }; bitmap.recycle()
            }
            screen.tapCharacter()
            screen.await { screen.views().none { it is AssistantBubbleMenu } }
            screen.test.runOnMainSync {
                assertFalse(screen.card(2).isActivated)
                assertTrue(screen.views().none { it.tag == "post-focus-shade" })
            }
            screen.tapCharacter()
            screen.await { screen.views().any { it is AssistantBubbleMenu } }
            screen.drag(-2000f, 80f)
            screen.await { screen.views().none { it is AssistantBubbleMenu } }
            screen.test.runOnMainSync {
                assertFalse(screen.button().isSelected); assertEquals(2, screen.button().tag)
                assertTrue(screen.views().none { it.tag == "post-focus-shade" })
            }
            screen.tapCharacter()
            screen.await { screen.views().any { it is AssistantBubbleMenu } }
            screen.await { screen.menu().x >= screen.button().x + screen.button().width * .75f }
            screen.test.runOnMainSync { screen.button().performAccessibilityAction(FloatingAssistantView.ACTION_RIGHT, null) }
            screen.await { screen.views().none { it is AssistantBubbleMenu } }
            screen.tapCharacter()
            screen.await { screen.views().any { it is AssistantBubbleMenu } }
            screen.center(1)
            screen.test.runOnMainSync {
                assertEquals(1, screen.button().tag)
                screen.activity.onBackPressedDispatcher.onBackPressed()
            }
            screen.await { screen.views().none { it is AssistantBubbleMenu } }
            assertTrue(server.questionPaths.isEmpty())
        } }
    }

    @Test @SdkSuppress(minSdkVersion = 30)
    fun bubbleOptionsOpenMemoriesAndTheDailyDigest() {
        Server().use { server -> Screen(server).use { screen ->
            screen.center(2)
            screen.test.runOnMainSync {
                screen.button().performClick()
                screen.views().first { it.contentDescription == "가족의 지난 추억이 궁금하세요?" }.performClick()
            }
            screen.await { screen.views().any { it is FamilyMemoryPanel } }
            screen.test.runOnMainSync { screen.activity.onBackPressedDispatcher.onBackPressed() }
            screen.await { screen.views().any { it is FloatingAssistantView } }
            screen.test.runOnMainSync {
                screen.button().performClick()
                screen.views().first { it.contentDescription == "오늘 가족의 하루" }.performClick()
            }
            screen.await { screen.views().filterIsInstance<TextView>().any { it.text.toString().contains("하루 요약이 도착해요.") } }
            screen.test.runOnMainSync { assertTrue(screen.views().none { it is AssistantBubbleMenu }) }
            assertTrue(server.questionPaths.isEmpty())
        } }
    }

    @Test @SdkSuppress(minSdkVersion = 30)
    fun thePopupFreezesTheSelectedPostUntilItCloses() {
        Server().use { server -> Screen(server).use { screen ->
            fun windows() = WindowInspector.getGlobalWindowViews().flatMap { screen.views(it) }
            screen.center(2)
            screen.test.runOnMainSync { screen.button().performClick() }
            screen.await { screen.views().filterIsInstance<TextView>().any { it.text.toString() == "이 글에 대해 궁금하세요?" } }
            screen.test.runOnMainSync {
                screen.views().filterIsInstance<TextView>().first { it.text.toString() == "이 글에 대해 궁금하세요?" }.performClick()
            }
            screen.await { windows().any { it is PostQuestionPanel } }
            screen.center(1) // The open popup keeps the original post if the underlying feed changes.
            screen.test.runOnMainSync {
                val panel = windows().filterIsInstance<PostQuestionPanel>().single()
                panel.composer.input.setText("무슨 소식이야?")
                panel.composer.sendButton.performClick()
            }
            screen.await { server.questionPaths.isNotEmpty() }
            assertEquals(listOf("/api/posts/2/questions/"), server.questionPaths.toList())
            screen.test.runOnMainSync {
                windows().first { it.contentDescription?.toString() == "도우미 닫기" }.performClick()
            }
            screen.await { screen.activity.window.decorView.rootWindowInsets?.isVisible(WindowInsets.Type.ime()) != true }
            screen.center(1)
            screen.test.runOnMainSync { screen.button().performClick() }
            screen.test.runOnMainSync {
                screen.views().filterIsInstance<TextView>().first { it.text.toString() == "이 글에 대해 궁금하세요?" }.performClick()
            }
            screen.await { windows().filterIsInstance<TextView>().any { it.text.toString() == "작성자1님의 소식에 질문해 보세요." } }
        } }
    }
}
