package kr.talkdock.app

import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Rect
import android.os.SystemClock
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import android.widget.ScrollView
import kr.talkdock.app.ui.PhotoCarousel
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
    private data class Request(val path: String, val method: String, val auth: String, val body: JSONObject, val room: String)
    private data class Reply(val text: String, val status: Int = 200, val image: ByteArray? = null)
    private val family = JSONObject().put("id", 1).put("name", "추억 테스트 가족")
        .put("members", JSONArray()).put("invite_code", "MEMORY")
    private fun answer(text: String) = Reply(JSONObject().put("text", text).toString())

    private inner class Server(val posts: JSONArray = JSONArray(), val respond: (Request) -> Reply) : AutoCloseable {
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
                        if (bytes.isEmpty()) JSONObject() else JSONObject(String(bytes, Charsets.UTF_8)), field("X-Family-Room"))
                    requests.add(request)
                    val reply = when (request.path) {
                        "/api/families/" -> Reply(JSONObject().put("rooms", JSONArray().put(family)).toString())
                        "/api/families/current/" -> Reply(family.toString())
                        "/api/posts/" -> Reply(JSONObject().put("posts", posts).toString())
                        else -> respond(request)
                    }
                    fun absolutePhotoUrls(value: Any?) {
                        when (value) {
                            is JSONObject -> value.keys().asSequence().toList().forEach { key ->
                                if (key == "url" && value.optString(key) == "test-photo/") value.put(key, base + "test-photo/")
                                else absolutePhotoUrls(value.opt(key))
                            }
                            is JSONArray -> (0 until value.length()).forEach { absolutePhotoUrls(value.opt(it)) }
                        }
                    }
                    val json = runCatching { JSONObject(reply.text).also { absolutePhotoUrls(it) }.toString() }.getOrDefault(reply.text)
                    val response = reply.image ?: json.toByteArray(Charsets.UTF_8)
                    val type = if (reply.image != null) "image/png" else "application/json"
                    client.getOutputStream().apply {
                        write("HTTP/1.1 ${reply.status} Test\r\nContent-Type: $type\r\nContent-Length: ${response.size}\r\nConnection: close\r\n\r\n".toByteArray())
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
            await { has("첫 소식을 기다리고 있어요") || has("가족의 소식") }
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
        fun open() {
            var inFamilyRoom = false
            test.runOnMainSync { inFamilyRoom = has("가족 추억 찾기") }
            if (inFamilyRoom) click("가족 추억 찾기") else {
                test.runOnMainSync {
                    assertTrue(views().filterIsInstance<kr.talkdock.app.ui.FloatingAssistantView>().single().performClick())
                }
                await { has("가족 추억 찾기") }
                click("가족 추억 찾기")
            }
            await { views().any { it is FamilyMemoryPanel } }
        }
        fun ask(text: String) = test.runOnMainSync { panel().input.setText(text); panel().searchButton.performClick() }
        fun recreate(memory: Boolean = true) {
            val previous = activity
            test.runOnMainSync { previous.recreate() }
            await {
                val next = ActivityLifecycleMonitorRegistry.getInstance().getActivitiesInStage(Stage.RESUMED)
                    .filterIsInstance<MainActivity>().firstOrNull { it !== previous }
                if (next != null) activity = next
                next != null && (if (memory) views().any { it is FamilyMemoryPanel } else has("가족의 소식"))
            }
        }
        fun scrollTo(view: View) = test.runOnMainSync {
            val scroll = views().filterIsInstance<ScrollView>().first()
            val rect = Rect(); view.getDrawingRect(rect)
            scroll.offsetDescendantRectToMyCoords(view, rect)
            scroll.scrollTo(0, rect.top)
        }
        fun screenshot(name: String) {
            test.waitForIdleSync()
            val frames = CountDownLatch(1)
            test.runOnMainSync {
                activity.window.decorView.postOnAnimation {
                    activity.window.decorView.postOnAnimation { frames.countDown() }
                }
            }
            assertTrue(frames.await(3, TimeUnit.SECONDS))
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

    @Test fun blankValidationAndInputLimitWorkInBothFontSizes() {
        for (large in listOf(false, true)) Server { answer("찾은 답변") }.use { server -> Screen(server, large).use { screen ->
            screen.open()
            screen.test.runOnMainSync {
                assertFalse(screen.panel().searchButton.isEnabled)
                screen.panel().input.setText(" \n "); screen.panel().searchButton.performClick()
                assertFalse(screen.panel().searchButton.isEnabled)
                screen.panel().input.setText("가".repeat(1001))
                assertEquals(1000, screen.panel().input.length())
            }
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
            screen.test.runOnMainSync { screen.views().first { it.contentDescription == "프로필 메뉴" }.performClick() }
            screen.await {
                val f = screen.activity.javaClass.getDeclaredField("profileMenuDialog").apply { isAccessible = true }
                (f.get(screen.activity) as? android.app.Dialog)?.isShowing == true
            }
            screen.test.runOnMainSync {
                val f = screen.activity.javaClass.getDeclaredField("profileMenuDialog").apply { isAccessible = true }
                val dialog = f.get(screen.activity) as android.app.Dialog
                var view: View = screen.views(dialog.window!!.decorView).filterIsInstance<TextView>().first { it.text.toString() == "가족방 바꾸기" }
                while (!view.isClickable && view.parent is View) view = view.parent as View
                view.performClick()
            }
            screen.await { screen.has("지금 보는 가족방") }
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

    private fun evidencePost(id: Int, photos: Int = 0) = JSONObject().put("id", id).put("author_id", 999)
        .put("author_name", "추억 테스트 가족").put("relationship", "가족")
        .put("created_at", "2026-10-01T09:00:00+09:00").put("caption", "가족과 부산 여행을 다녀왔어요. 소중한 하루였어요.")
        .put("comment_count", 2).put("images", JSONArray().apply {
            repeat(photos) { put(JSONObject().put("id", it).put("url", "test-photo/")) }
        }).put("image_count", photos).put("comments", JSONArray())

    private fun evidenceReply(posts: JSONArray, text: String = "부산으로 가족 여행을 다녀왔어요.") =
        Reply(JSONObject().put("text", text).put("evidence_posts", posts).put("evidence_kind", "cited").toString())

    private fun photoReply(): Reply {
        val bitmap = Bitmap.createBitmap(640, 420, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(bitmap); canvas.drawColor(Color.rgb(217, 237, 246))
        val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.rgb(126, 173, 181) }
        canvas.drawRect(0f, 270f, 640f, 420f, paint)
        paint.color = Color.rgb(255, 219, 132); canvas.drawCircle(500f, 90f, 45f, paint)
        paint.color = Color.rgb(83, 109, 121); paint.textSize = 40f
        canvas.drawText("Family trip", 205f, 230f, paint)
        val stream = ByteArrayOutputStream(); bitmap.compress(Bitmap.CompressFormat.PNG, 100, stream); bitmap.recycle()
        return Reply("", image = stream.toByteArray())
    }

    @Test fun evidenceUsesTheSameFullPostAsFeedInBothFontSizes() {
        for (large in listOf(false, true)) {
            val post = evidencePost(12, 2)
            Server(JSONArray().put(post)) { request ->
                if (request.path.endsWith("test-photo/")) photoReply()
                else evidenceReply(JSONArray().put(post).put(post).put(evidencePost(9)))
            }.use { server -> Screen(server, large).use { screen ->
                var feedTexts = emptyList<String>()
                screen.test.runOnMainSync {
                    val card = screen.views().single { it.tag == "feed-post:12" }
                    feedTexts = screen.views(card).filterIsInstance<TextView>()
                        .filter { it !is android.widget.EditText }.map { it.text.toString() }
                }
                screen.open(); screen.ask("지난 가족 여행은?")
                screen.await { screen.has("부산으로 가족 여행을 다녀왔어요.") && screen.views().any { it.tag == "feed-post:12" } }
                screen.test.runOnMainSync {
                    val card = screen.views().single { it.tag == "feed-post:12" }
                    val evidenceTexts = screen.views(card).filterIsInstance<TextView>()
                        .filter { it !is android.widget.EditText }.map { it.text.toString() }
                    assertEquals(feedTexts, evidenceTexts)
                    assertEquals(1, screen.views().count { it.tag == "feed-post:9" })
                    assertEquals(1, screen.views(card).filterIsInstance<PhotoCarousel>().size)
                    assertTrue(screen.has("이 이야기가 담긴 소식"))
                    assertTrue(screen.has("AI 요약"))
                }
                val card = screen.views().single { it.tag == "feed-post:12" }
                screen.scrollTo(card)
                screen.await { screen.views(card).filterIsInstance<android.widget.ImageView>().firstOrNull()
                    ?.drawable is android.graphics.drawable.BitmapDrawable }
                if (!large) {
                    screen.scrollTo(screen.views().filterIsInstance<TextView>().first { it.text.toString() == "토닥이 찾은 이야기" })
                    screen.screenshot("memory-evidence-answer.png")
                    screen.scrollTo(card)
                }
                screen.screenshot(if (large) "memory-evidence-large.png" else "memory-evidence-post.png")
                screen.test.runOnMainSync {
                    val thumbnail = screen.views(card).first { it.contentDescription == "2번째 사진으로 이동" }
                    thumbnail.performClick()
                }
                screen.await { screen.views(card).filterIsInstance<PhotoCarousel>().single().currentIndex == 1 }
            } }
        }
    }

    @Test fun evidenceDetailBackAndRecreationKeepAnswerDraftPostsAndScrollWithoutNewSearch() {
        val post = evidencePost(12, 2)
        Server { request -> when (request.path) {
            "/api/posts/12/" -> Reply(post.toString())
            "/api/test-photo/" -> photoReply()
            else -> evidenceReply(JSONArray().put(post).put(evidencePost(9)))
        } }.use { server -> Screen(server).use { screen ->
            screen.open(); screen.ask("가족 여행")
            screen.await { screen.has("부산으로 가족 여행을 다녀왔어요.") }
            val card = screen.views().single { it.tag == "feed-post:12" }
            screen.scrollTo(card)
            var scrollY = 0
            screen.test.runOnMainSync {
                screen.panel().input.setText("다음에 물을 질문")
                scrollY = screen.views().filterIsInstance<ScrollView>().first().scrollY
                assertTrue(scrollY > 0)
            }
            screen.click("댓글 2"); screen.await { screen.has("댓글 0") }
            screen.recreate(memory = false)
            screen.await { screen.has("댓글 0") }
            screen.test.runOnMainSync { screen.activity.onBackPressedDispatcher.onBackPressed() }
            screen.await { screen.views().any { it is FamilyMemoryPanel } }
            screen.await { screen.views().filterIsInstance<ScrollView>().first().scrollY > 0 }
            screen.test.runOnMainSync {
                assertEquals("다음에 물을 질문", screen.panel().input.text.toString())
                assertTrue(screen.has("부산으로 가족 여행을 다녀왔어요."))
                assertEquals(scrollY, screen.views().filterIsInstance<ScrollView>().first().scrollY)
            }
            screen.recreate()
            screen.await { screen.views().filterIsInstance<ScrollView>().first().scrollY > 0 }
            screen.test.runOnMainSync {
                assertEquals("다음에 물을 질문", screen.panel().input.text.toString())
                assertEquals(2, screen.views().count { it.tag?.toString()?.startsWith("feed-post:") == true })
            }
            assertEquals(1, server.searches().size)
        } }
    }

    @Test fun deployedServerSourcesOpenAuthenticatedOriginalPostsAndSkipDeletedOnes() {
        Server { request -> when (request.path) {
            "/api/posts/12/" -> Reply(evidencePost(12).toString())
            "/api/posts/9/" -> Reply("{}", 404)
            else -> Reply("""{"text":"운영 서버 형식의 답변","memories":[{"sources":[
                {"id":"first","name":"post_12"},{"id":"duplicate","name":"post_12"},
                {"id":"deleted","name":"post_9"},{"id":"family","name":"family_1"}]}]}""")
        } }.use { server -> Screen(server).use { screen ->
            screen.open(); screen.ask("옛 여행")
            screen.await { screen.has("운영 서버 형식의 답변") }
            screen.test.runOnMainSync {
                assertEquals(1, screen.views().count { it.tag == "feed-post:12" })
                assertFalse(screen.views().any { it.tag == "feed-post:9" })
                assertTrue(screen.has("답변을 만들 때 검색한 소식이에요."))
            }
            val fetched = server.requests.filter { it.path.matches(Regex("/api/posts/[0-9]+/")) }
            assertEquals(2, fetched.size)
            assertTrue(fetched.all { it.auth == "Bearer memory-test-token" && it.room == "1" })
        } }
    }

    @Test fun newSearchClearsOldEvidenceAndNoSourcesShowsEmptyState() {
        Server { request -> if (request.body.optString("question") == "첫 질문") evidenceReply(JSONArray().put(evidencePost(12)))
            else evidenceReply(JSONArray(), "관련 기록을 찾지 못했어요.")
        }.use { server -> Screen(server).use { screen ->
            screen.open(); screen.ask("첫 질문")
            screen.await { screen.views().any { it.tag == "feed-post:12" } }
            screen.ask("다음 질문")
            screen.await { screen.has("관련 기록을 찾지 못했어요.") }
            screen.test.runOnMainSync {
                assertTrue(screen.has("연결된 원문 게시글이 없어요."))
                assertFalse(screen.views().any { it.tag == "feed-post:12" })
            }
        } }
    }

}
