package kr.talkdock.app

import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.os.SystemClock
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.runner.lifecycle.ActivityLifecycleMonitorRegistry
import androidx.test.runner.lifecycle.Stage
import kr.talkdock.app.ui.FamilyMemoryPanel
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.ByteArrayOutputStream
import java.io.File
import java.net.ServerSocket
import java.util.Collections
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

@RunWith(AndroidJUnit4::class)
class FamilyMemorySearchTest {
    private data class Request(val path: String, val method: String, val auth: String, val body: JSONObject)
    private data class Reply(val text: String, val status: Int = 200)
    private val family = JSONObject().put("id", 1).put("name", "추억 테스트 가족")
        .put("members", JSONArray()).put("invite_code", "MEMORY")
    private fun answer(text: String) = Reply(JSONObject().put("text", text).toString())

    private inner class Server(val respond: (Request) -> Reply) : AutoCloseable {
        private val socket = ServerSocket(0)
        private val workers = Executors.newCachedThreadPool()
        val requests = Collections.synchronizedList(mutableListOf<Request>())
        val base = "http://127.0.0.1:${socket.localPort}/api/"
        private val accept = Thread {
            while (!socket.isClosed) {
                val client = runCatching { socket.accept() }.getOrNull() ?: break
                workers.execute { client.use { runCatching {
                    client.soTimeout = 5000
                    val stream = client.getInputStream().buffered()
                    val header = ByteArrayOutputStream()
                    while (header.size() < 65536) {
                        val next = stream.read()
                        if (next < 0) return@runCatching
                        header.write(next)
                        val bytes = header.toByteArray()
                        if (bytes.size >= 4 && bytes.takeLast(4) == listOf(13.toByte(), 10.toByte(), 13.toByte(), 10.toByte())) break
                    }
                    val lines = header.toString("UTF-8").split("\r\n")
                    val first = lines.first().split(" ")
                    fun field(name: String) = lines.firstOrNull { it.startsWith("$name:", true) }?.substringAfter(':')?.trim().orEmpty()
                    val bytes = ByteArray(field("Content-Length").toIntOrNull() ?: 0)
                    var offset = 0
                    while (offset < bytes.size) {
                        val count = stream.read(bytes, offset, bytes.size - offset)
                        if (count < 0) break
                        offset += count
                    }
                    val request = Request(first[1], first[0], field("Authorization"),
                        if (bytes.isEmpty()) JSONObject() else JSONObject(String(bytes, Charsets.UTF_8)))
                    requests.add(request)
                    val reply = when (request.path) {
                        "/api/families/" -> Reply(JSONObject().put("rooms", JSONArray().put(family)).toString())
                        "/api/families/current/" -> Reply(family.toString())
                        "/api/posts/" -> Reply(JSONObject().put("posts", JSONArray()).toString())
                        else -> respond(request)
                    }
                    val response = reply.text.toByteArray(Charsets.UTF_8)
                    client.getOutputStream().apply {
                        write("HTTP/1.1 ${reply.status} Test\r\nContent-Type: application/json\r\nContent-Length: ${response.size}\r\nConnection: close\r\n\r\n".toByteArray())
                        write(response); flush()
                    }
                } } }
            }
        }.apply { isDaemon = true; start() }
        fun searches() = synchronized(requests) { requests.filter { it.path == "/api/searching/history/" } }
        override fun close() { socket.close(); workers.shutdownNow(); accept.join(1000) }
    }

    private inner class Screen(server: Server, large: Boolean = false) : AutoCloseable {
        val test = InstrumentationRegistry.getInstrumentation()
        private val prefs = test.targetContext.getSharedPreferences("talkdock-session", Context.MODE_PRIVATE)
        private val saved = prefs.all.toMap()
        var activity: MainActivity
        init {
            val user = JSONObject().put("user_id", 999).put("username", "memory-test").put("name", "테스트")
                .put("token", "memory-test-token").put("large", large).put("room", family)
            prefs.edit().clear().putString("current", user.toString()).putString("server", server.base).commit()
            activity = test.startActivitySync(Intent(test.targetContext, MainActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)) as MainActivity
            await { has("첫 소식을 기다리고 있어요") }
        }
        fun views(view: View = activity.window.decorView): List<View> = listOf(view) +
            if (view is ViewGroup) (0 until view.childCount).flatMap { views(view.getChildAt(it)) } else emptyList()
        fun has(text: String) = views().filterIsInstance<TextView>().any { it.text.toString() == text }
        fun panel() = views().filterIsInstance<FamilyMemoryPanel>().single()
        fun await(condition: () -> Boolean) {
            val until = SystemClock.uptimeMillis() + 10000
            while (SystemClock.uptimeMillis() < until) {
                var ready = false
                test.runOnMainSync { ready = condition() }
                if (ready) return
                Thread.sleep(40)
            }
            fail("Memory screen condition timed out")
        }
        fun click(text: String) = test.runOnMainSync {
            var target: View = views().filterIsInstance<TextView>().first { it.text.toString() == text }
            while (!target.isClickable && target.parent is View) target = target.parent as View
            assertTrue(target.performClick())
        }
        fun open() { click("가족 추억 찾기"); await { views().any { it is FamilyMemoryPanel } } }
        fun ask(text: String) = test.runOnMainSync { panel().input.setText(text); panel().searchButton.performClick() }
        fun recreate() {
            val previous = activity
            test.runOnMainSync { previous.recreate() }
            await {
                val next = ActivityLifecycleMonitorRegistry.getInstance().getActivitiesInStage(Stage.RESUMED)
                    .filterIsInstance<MainActivity>().firstOrNull { it !== previous }
                if (next != null) activity = next
                next != null && views().any { it is FamilyMemoryPanel }
            }
        }
        fun screenshot(name: String) {
            test.waitForIdleSync()
            val bitmap = test.uiAutomation.takeScreenshot()
            File(test.targetContext.cacheDir, name).outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
            bitmap.recycle()
        }
        override fun close() {
            test.runOnMainSync { activity.finish() }; test.waitForIdleSync()
            val editor = prefs.edit().clear()
            saved.forEach { (key, value) -> when (value) {
                is String -> editor.putString(key, value)
                is Boolean -> editor.putBoolean(key, value)
                is Int -> editor.putInt(key, value)
                is Long -> editor.putLong(key, value)
                is Float -> editor.putFloat(key, value)
                is Set<*> -> editor.putStringSet(key, value.filterIsInstance<String>().toSet())
            } }
            editor.commit()
        }
    }

    @Test fun examplesBlankValidationAndInputLimitWorkInBothFontSizes() {
        for (large in listOf(false, true)) Server { answer("찾은 답변") }.use { server -> Screen(server, large).use { screen ->
            screen.open()
            screen.test.runOnMainSync {
                assertFalse(screen.panel().searchButton.isEnabled)
                screen.panel().input.setText(" \n "); screen.panel().searchButton.performClick()
                assertFalse(screen.panel().searchButton.isEnabled)
                screen.panel().input.setText("가".repeat(1001))
                assertEquals(1000, screen.panel().input.length())
            }
            screen.click("최근 가족 여행 이야기 찾아줘")
            screen.test.runOnMainSync { assertEquals("최근 가족 여행 이야기 찾아줘", screen.panel().input.text.toString()) }
            assertTrue(server.searches().isEmpty())
            screen.screenshot(if (large) "memory-large.png" else "memory-idle.png")
        } }
    }

    @Test fun sendsAuthenticatedFamilyWideQuestionAndRendersAnswer() {
        Server { answer("지난 가족 여행은 부산으로 다녀왔어요.") }.use { server -> Screen(server).use { screen ->
            screen.open(); screen.ask("  지난 가족 여행은 어디였어?  ")
            screen.await { screen.has("지난 가족 여행은 부산으로 다녀왔어요.") }
            val request = server.searches().single()
            assertEquals("POST", request.method); assertEquals("Bearer memory-test-token", request.auth)
            assertEquals(setOf("question"), request.body.keys().asSequence().toSet())
            assertEquals("지난 가족 여행은 어디였어?", request.body.getString("question"))
            assertFalse(server.requests.any { it.path.endsWith("/comments/") || it.path.endsWith("/questions/") })
            screen.screenshot("memory-answer.png")
        } }
    }

    @Test fun pendingSearchPreventsDuplicatesAndLeavingDiscardsItsAnswer() {
        val release = CountDownLatch(1)
        Server { request ->
            if (request.body.optString("question") == "오래 걸리는 질문") {
                release.await(5, TimeUnit.SECONDS); answer("이전 화면의 답변")
            } else answer("새 질문의 답변")
        }.use { server -> Screen(server).use { screen ->
            screen.open(); screen.ask("오래 걸리는 질문")
            screen.await { server.searches().size == 1 }
            screen.test.runOnMainSync {
                assertFalse(screen.panel().input.isEnabled); assertFalse(screen.panel().searchButton.isEnabled)
                screen.panel().searchButton.performClick()
                screen.activity.onBackPressedDispatcher.onBackPressed()
            }
            screen.await { screen.has("첫 소식을 기다리고 있어요") }
            assertEquals(1, server.searches().size)
            screen.open(); release.countDown()
            screen.ask("새 질문"); screen.await { screen.has("새 질문의 답변") }
            screen.test.runOnMainSync { assertFalse(screen.has("이전 화면의 답변")) }
        } }
    }

    @Test fun serverFailureKeepsExactDraftAndRetrySucceeds() {
        var attempts = 0
        Server {
            if (++attempts == 1) Reply(JSONObject().put("error", "검색을 잠시 사용할 수 없어요.").toString(), 503)
            else answer("다시 찾은 답변")
        }.use { server -> Screen(server).use { screen ->
            screen.open(); screen.ask("  보존할 질문\n그 여행  ")
            screen.await { screen.has("검색을 잠시 사용할 수 없어요.") }
            screen.test.runOnMainSync {
                assertEquals("  보존할 질문\n그 여행  ", screen.panel().input.text.toString())
                assertTrue(screen.panel().searchButton.isEnabled); screen.panel().searchButton.performClick()
            }
            screen.await { screen.has("다시 찾은 답변") }
            assertEquals(2, server.searches().size)
        } }
    }

    @Test fun expiredLoginOffersWorkingSignInAction() {
        Server { Reply("{\"error\":\"Unauthorized\"}", 401) }.use { server -> Screen(server).use { screen ->
            screen.open(); screen.ask("생일 이야기")
            screen.await { screen.has("로그인이 만료되었어요. 다시 로그인해 주세요.") }
            screen.test.runOnMainSync { assertEquals("생일 이야기", screen.panel().input.text.toString()) }
            screen.click("다시 로그인하기"); screen.await { screen.has("비밀번호") }
            assertNull(kr.talkdock.app.data.SessionStore(screen.test.targetContext).current())
        } }
    }

    @Test fun invalidOrEmptyAnswerIsAnErrorAndKeepsDraft() {
        for (reply in listOf("{\"text\":\"\"}", "{}", "not-json")) Server { Reply(reply) }.use { server -> Screen(server).use { screen ->
            screen.open(); screen.ask("기록을 찾아줘")
            screen.await { screen.views().filterIsInstance<TextView>().any { it.isShown && it.text.contains("다시 시도해 주세요") } }
            screen.test.runOnMainSync {
                assertEquals("기록을 찾아줘", screen.panel().input.text.toString())
                assertTrue(screen.panel().searchButton.isEnabled); assertFalse(screen.has("토닥이 찾은 이야기"))
            }
        } }
    }

    @Test fun recreationPreservesQuestionAndAnswerWithoutRepeatingSearch() {
        Server { answer("회전해도 남아 있는 답변") }.use { server -> Screen(server).use { screen ->
            screen.open(); screen.ask("가족 여행")
            screen.await { screen.has("회전해도 남아 있는 답변") }
            screen.test.runOnMainSync { screen.panel().input.setText("다음에 물을 질문") }
            screen.recreate()
            screen.test.runOnMainSync {
                assertTrue(screen.has("회전해도 남아 있는 답변")); assertTrue(screen.has("가족 여행"))
                assertEquals("다음에 물을 질문", screen.panel().input.text.toString())
            }
            assertEquals(1, server.searches().size)
        } }
    }

    @Test fun familyRoomAlsoOpensSearch() {
        Server { answer("답변") }.use { server -> Screen(server).use { screen ->
            screen.click("가족방"); screen.await { screen.has("지금 보는 가족방") }
            screen.open()
            screen.test.runOnMainSync { assertTrue(screen.has("함께 쌓아온 추억 찾기")) }
        } }
    }

    @Test fun recreationDoesNotRestoreAnotherAccountsAnswer() {
        Server { answer("이전 계정의 가족 답변") }.use { server -> Screen(server).use { screen ->
            screen.open(); screen.ask("이전 계정의 질문")
            screen.await { screen.has("이전 계정의 가족 답변") }
            val prefs = screen.test.targetContext.getSharedPreferences("talkdock-session", Context.MODE_PRIVATE)
            val changed = JSONObject(prefs.getString("current", "{}")!!).put("user_id", 1000)
            prefs.edit().putString("current", changed.toString()).commit()
            screen.recreate()
            screen.test.runOnMainSync {
                assertFalse(screen.has("이전 계정의 가족 답변"))
                assertFalse(screen.has("토닥이 찾은 이야기"))
                assertEquals("", screen.panel().input.text.toString())
            }
            assertEquals(1, server.searches().size)
        } }
    }
}
