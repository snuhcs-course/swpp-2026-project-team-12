package kr.talkdock.app

import android.content.Context
import android.content.Intent
import android.os.SystemClock
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.widget.ScrollView
import android.widget.TextView
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import kr.talkdock.app.ui.TodakWaitingView
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.net.ServerSocket
import java.util.concurrent.CountDownLatch
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

/** Exercises real feed gestures and HTTP responses against a test-only local server. */
@RunWith(AndroidJUnit4::class)
class FeedRefreshTest {
    private val test = InstrumentationRegistry.getInstrumentation()

    private fun views(view: View): List<View> = listOf(view) +
        if (view is ViewGroup) (0 until view.childCount).flatMap { views(view.getChildAt(it)) } else emptyList()

    private fun awaitUi(condition: () -> Boolean) {
        val deadline = SystemClock.uptimeMillis() + 5000
        while (SystemClock.uptimeMillis() < deadline) {
            var ready = false
            test.runOnMainSync { ready = condition() }
            if (ready) return
            Thread.sleep(25)
        }
        fail("UI did not reach the expected state")
    }

    private fun swipe(view: View, horizontal: Boolean = false, short: Boolean = false) {
        val location = IntArray(2)
        var width = 0
        test.runOnMainSync {
            view.getLocationOnScreen(location); width = view.width
        }
        val density = view.resources.displayMetrics.density
        val x = location[0] + if (horizontal) 32 * density else width / 2f
        // Start in the feed's top padding; 24dp now lands on the edge of the "가족 추억 찾기" button.
        val y = location[1] + 4 * density
        val distance = (if (short) 20 else 220) * density
        val down = SystemClock.uptimeMillis()
        for (step in 0..12) {
            val action = when (step) { 0 -> MotionEvent.ACTION_DOWN; 12 -> MotionEvent.ACTION_UP; else -> MotionEvent.ACTION_MOVE }
            val event = MotionEvent.obtain(down, SystemClock.uptimeMillis(), action,
                x + if (horizontal) distance * step / 12f else 0f,
                y + if (horizontal) 0f else distance * step / 12f, 0)
            test.uiAutomation.injectInputEvent(event, true)
            event.recycle()
            Thread.sleep(20)
        }
    }

    @Test fun pullRefreshPreservesFeedUntilSuccessAndKeepsItOnFailure() {
        data class Response(val caption: String, val status: Int = 200, val gate: CountDownLatch? = null)
        val responses = LinkedBlockingQueue<Response>()
        val requests = AtomicInteger()
        val server = ServerSocket(0)
        val release = CountDownLatch(1)
        val worker = Thread {
            while (!server.isClosed) {
                try {
                    server.accept().use { socket ->
                        socket.soTimeout = 5000
                        val input = socket.getInputStream().bufferedReader()
                        val requestLine = input.readLine().orEmpty()
                        var line = input.readLine()
                        while (!line.isNullOrEmpty()) line = input.readLine()
                        val path = requestLine.split(" ").getOrNull(1)
                        if (path == "/api/families/" || path == "/api/families/current/") {
                            val room = JSONObject().put("id",1).put("name","테스트 가족방").put("members",JSONArray())
                            val reply = if (path == "/api/families/") JSONObject().put("rooms", JSONArray().put(room)) else room
                            val bytes = reply.toString().toByteArray(Charsets.UTF_8)
                            socket.getOutputStream().apply {
                                write("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: ${bytes.size}\r\nConnection: close\r\n\r\n".toByteArray())
                                write(bytes); flush()
                            }
                            return@use
                        }
                        requests.incrementAndGet()
                        val response = responses.poll(5, TimeUnit.SECONDS) ?: error("Unexpected feed request")
                        response.gate?.await(5, TimeUnit.SECONDS)
                        val posts = JSONArray()
                        repeat(8) { index -> posts.put(JSONObject().put("id", index + 1)
                            .put("author_name", "가족").put("relationship", "손주")
                            .put("created_at", "2026-10-17T09:00:00+09:00")
                            .put("caption", response.caption).put("comment_count", 0).put("images", JSONArray())) }
                        val body = if (response.status == 200) JSONObject().put("posts", posts).toString()
                            else "{\"detail\":\"새로고침 테스트 오류\"}"
                        val bytes = body.toByteArray(Charsets.UTF_8)
                        val header = "HTTP/1.1 ${response.status} Test\r\nContent-Type: application/json; charset=utf-8\r\nContent-Length: ${bytes.size}\r\nConnection: close\r\n\r\n"
                        socket.getOutputStream().apply { write(header.toByteArray()); write(bytes); flush() }
                    }
                } catch (_: Exception) { if (!server.isClosed) requests.set(-100) }
            }
        }.apply { isDaemon = true; start() }
        val prefs = test.targetContext.getSharedPreferences("talkdock-session", Context.MODE_PRIVATE)
        val savedCurrent = prefs.getString("current", null)
        val savedServer = prefs.getString("server", null)
        var activity: MainActivity? = null
        try {
            responses.put(Response("새로고침 전 소식"))
            val account = JSONObject().put("user_id", 999).put("token", "test-token").put("name", "테스트")
                .put("large", false).put("room", JSONObject().put("id", 1).put("name", "테스트 가족방"))
            prefs.edit().putString("current", account.toString())
                .putString("server", "http://127.0.0.1:${server.localPort}/api/").commit()
            val launched = test.startActivitySync(Intent(test.targetContext, MainActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)) as MainActivity
            activity = launched
            fun hasText(text: String) = views(launched.window.decorView).filterIsInstance<TextView>().any { it.text.toString() == text }
            awaitUi { hasText("새로고침 전 소식") }
            lateinit var refresh: SwipeRefreshLayout
            test.runOnMainSync { refresh = views(launched.window.decorView).filterIsInstance<SwipeRefreshLayout>().single() }
            swipe(refresh, horizontal = true)
            swipe(refresh, short = true)
            Thread.sleep(400)
            assertEquals("Horizontal swipes and short pulls must not refresh", 1, requests.get())
            responses.put(Response("새로 불러온 소식", gate = release))
            swipe(refresh)
            awaitUi { requests.get() == 2 && refresh.isRefreshing }
            test.runOnMainSync {
                assertTrue(hasText("새로고침 전 소식"))
                assertTrue(views(launched.window.decorView).none { it is TodakWaitingView })
            }
            swipe(refresh)
            Thread.sleep(300)
            assertEquals("Only one refresh request may be in flight", 2, requests.get())
            release.countDown()
            awaitUi { hasText("새로 불러온 소식") && !refresh.isRefreshing }
            Thread.sleep(400)
            responses.put(Response("", status = 500))
            swipe(refresh)
            awaitUi { requests.get() == 3 && !refresh.isRefreshing }
            test.runOnMainSync { assertTrue("Failed refresh must preserve the displayed feed", hasText("새로 불러온 소식")) }
        } finally {
            release.countDown()
            test.runOnMainSync { activity?.finish() }
            server.close(); worker.join(1000)
            prefs.edit().apply {
                if (savedCurrent == null) remove("current") else putString("current", savedCurrent)
                if (savedServer == null) remove("server") else putString("server", savedServer)
            }.commit()
        }
    }
}
