package kr.talkdock.app

import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.os.SystemClock
import android.view.View
import android.view.ViewGroup
import android.widget.*
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.runner.lifecycle.ActivityLifecycleMonitorRegistry
import androidx.test.runner.lifecycle.Stage
import kr.talkdock.app.ui.DailyQuestionPanel
import kr.talkdock.app.ui.PhotoLetterDeck
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.BufferedInputStream
import java.io.File
import java.net.ServerSocket
import java.util.concurrent.atomic.AtomicBoolean

/** Real view navigation, input failures and feed restoration, without external AI services. */
@RunWith(AndroidJUnit4::class)
class DailyQuestionTest {
    private val test = InstrumentationRegistry.getInstrumentation()
    private fun views(view: View): List<View> = listOf(view) + if (view is ViewGroup)
        (0 until view.childCount).flatMap { views(view.getChildAt(it)) } else emptyList()

    private fun awaitUi(condition: () -> Boolean) {
        val end = SystemClock.uptimeMillis() + 8000
        while (SystemClock.uptimeMillis() < end) {
            var ready = false
            test.runOnMainSync { ready = condition() }
            if (ready) return
            Thread.sleep(30)
        }
        fail("Daily question UI did not reach the expected state")
    }

    private class Server(var kind: String = "choice") : AutoCloseable {
        val socket = ServerSocket(0)
        val failAnswer = AtomicBoolean(false)
        val failComment = AtomicBoolean(false)
        val failDetailAfterComment = AtomicBoolean(false)
        @Volatile var hasNewPost = false
        @Volatile var answer: JSONObject? = null
        val comments = JSONArray()
        val options get() = if (kind == "text") JSONArray() else JSONArray(
            if (kind == "tier") listOf("집에서 쉬기", "밖에서 산책") else listOf("집에서 쉬기", "밖에서 산책", "기타"))
        private fun question() = JSONObject().put("id", 31).put("post_id", 301).put("date", "2026-10-31")
            .put("version", "31:family:1").put("title", "주말엔 뭘 할까요?").put("kind", kind).put("options", options)
            .put("answers", JSONArray().put(JSONObject().put("id", 1).put("author_id", 2).put("author_name", "할머니")
                .put("choice", if (kind == "text" || kind == "tier") "" else "밖에서 산책").put("text", "같이 바람 쐬면 좋겠어.")
                .put("tiers", if (kind == "tier") JSONObject().put("집에서 쉬기", "B").put("밖에서 산책", "S") else JSONObject())))
            .also { data -> answer?.let { data.getJSONArray("answers").put(JSONObject(it.toString())) } }
            .put("comments", JSONArray(comments.toString()))
        private fun line(input: BufferedInputStream): String {
            val bytes = java.io.ByteArrayOutputStream()
            while (true) { val value = input.read(); if (value == -1 || value == 10) break; if (value != 13) bytes.write(value) }
            return bytes.toString("UTF-8")
        }
        private val worker = Thread {
            while (!socket.isClosed) try {
                socket.accept().use { client ->
                    client.soTimeout = 5000
                    val input = BufferedInputStream(client.getInputStream())
                    val first = line(input).split(" ")
                    val method = first[0]; val path = first.getOrElse(1) { "" }
                    var length = 0
                    while (true) { val header = line(input); if (header.isEmpty()) break
                        if (header.startsWith("Content-Length:", true)) length = header.substringAfter(':').trim().toInt() }
                    val bytes = ByteArray(length); var count = 0
                    while (count < length) { val read = input.read(bytes, count, length - count); if (read < 0) break; count += read }
                    val payload = if (length > 0) JSONObject(String(bytes, Charsets.UTF_8)) else JSONObject()
                    val room = JSONObject().put("id", 1).put("name", "테스트 가족방").put("members", JSONArray())
                    var status = 200
                    val response: JSONObject = when {
                        path == "/api/families/" -> JSONObject().put("rooms", JSONArray().put(room))
                        path == "/api/families/current/" -> room
                        path == "/api/posts/" -> {
                            val posts = JSONArray()
                            for (id in (if (hasNewPost) 3 else 2) downTo 1) posts.put(JSONObject().put("id", id)
                                .put("author_name", "정아").put("relationship", "가족").put("caption", "가족 소식 $id" +
                                    if (id == 1) "\n오늘은 가족에게 긴 소식을 전해요.\n우리 가족 모두 잘 지내고 있나요?" else "")
                                .put("created_at", "2026-10-31T1$id:00:00+09:00").put("images", JSONArray()).put("comment_count", 0))
                            JSONObject().put("posts", posts).put("daily_question", JSONObject().put("id", 31).put("date", "2026-10-31").put("title", "주말엔 뭘 할까요?").put("version", "31:family:1"))
                        }
                        path.endsWith("/answer/") && method == "PUT" -> {
                            if (failAnswer.getAndSet(false)) { status = 503; JSONObject().put("error", "답변 저장 실패 · 다시 시도해 주세요.") }
                            else { answer = JSONObject(payload.toString()).put("id", 2).put("author_id", 1).put("author_name", "정아"); question() }
                        }
                        path == "/api/posts/301/comments/" -> {
                            if (failComment.getAndSet(false)) { status = 503; JSONObject().put("error", "댓글 저장 실패 · 다시 시도해 주세요.") }
                            else { comments.put(JSONObject().put("id", comments.length() + 1).put("author_id", 1).put("author_name", "정아").put("text", payload.getString("text"))); JSONObject().put("id", comments.length()) }
                        }
                        path.startsWith("/api/daily-questions/history/") -> JSONObject().put("questions", JSONArray().put(JSONObject().put("id", 31).put("date", "2026-10-31").put("title", "주말엔 뭘 할까요?")))
                        path.startsWith("/api/daily-questions/") -> if (comments.length() > 0 && failDetailAfterComment.getAndSet(false)) {
                            status = 503; JSONObject().put("error", "댓글은 저장했지만 새 목록을 불러오지 못했어요.")
                        } else question()
                        else -> JSONObject()
                    }
                    val body = response.toString().toByteArray(Charsets.UTF_8)
                    client.getOutputStream().apply {
                        write("HTTP/1.1 $status Test\r\nContent-Type: application/json; charset=utf-8\r\nContent-Length: ${body.size}\r\nConnection: close\r\n\r\n".toByteArray())
                        write(body); flush()
                    }
                }
            } catch (_: Exception) { if (!socket.isClosed) Thread.sleep(10) }
        }.apply { isDaemon = true; start() }
        override fun close() { socket.close(); worker.join(1000) }
    }

    private fun withApp(large: Boolean = false, kind: String = "choice", body: (MainActivity, Server) -> Unit) {
        val prefs = test.targetContext.getSharedPreferences("talkdock-session", Context.MODE_PRIVATE)
        val savedCurrent = prefs.getString("current", null); val savedServer = prefs.getString("server", null)
        var activity: MainActivity? = null
        Server(kind).use { server ->
            try {
                val account = JSONObject().put("user_id", 1).put("username", "daily-test").put("token", "local")
                    .put("name", "정아").put("large", large).put("room", JSONObject().put("id", 1).put("name", "테스트 가족방"))
                prefs.edit().putString("current", account.toString()).putString("server", "http://127.0.0.1:${server.socket.localPort}/api/").commit()
                activity = test.startActivitySync(Intent(test.targetContext, MainActivity::class.java)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)) as MainActivity
                val launched = activity!!
                awaitUi { views(launched.window.decorView).any { it is PhotoLetterDeck } }
                body(launched, server)
            } finally {
                test.runOnMainSync {
                    activity?.finish()
                    ActivityLifecycleMonitorRegistry.getInstance().getActivitiesInStage(Stage.RESUMED)
                        .filterIsInstance<MainActivity>().forEach { it.finish() }
                }
                prefs.edit().apply {
                    if (savedCurrent == null) remove("current") else putString("current", savedCurrent)
                    if (savedServer == null) remove("server") else putString("server", savedServer)
                }.commit()
            }
        }
    }

    private fun click(activity: MainActivity, label: String) = test.runOnMainSync {
        views(activity.window.decorView).first { it.contentDescription?.toString() == label || (it is TextView && it.text.toString() == label) }.performClick()
    }
    private fun hasText(activity: MainActivity, value: String) = views(activity.window.decorView).filterIsInstance<TextView>().any { it.text.toString() == value }
    private fun editor(activity: MainActivity) = views(activity.window.decorView).filterIsInstance<EditText>().first { it.contentDescription == "오늘의 질문 답변 입력" }
    private fun screenshot(activity: MainActivity, name: String) {
        test.waitForIdleSync()
        val bitmap = test.uiAutomation.takeScreenshot()
        File(activity.cacheDir, name).outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
        bitmap.recycle()
        // Keep the inspection artifacts after Gradle uninstalls the test APKs.
        if (android.os.Build.VERSION.SDK_INT >= 31) {
            val pipes = test.uiAutomation.executeShellCommandRw("dd of=/sdcard/Download/todak-$name")
            android.os.ParcelFileDescriptor.AutoCloseOutputStream(pipes[1]).use {
                File(activity.cacheDir, name).inputStream().use { image -> image.copyTo(it) }
            }
            android.os.ParcelFileDescriptor.AutoCloseInputStream(pipes[0]).use { it.readBytes() }
        }
    }

    @Test fun headerEntrySurvivesNewPostsAndReturnsToSameLetterAndScroll() = withApp { activity, server ->
        lateinit var scroll: ScrollView
        var position = 0
        // Guarantee a scrollable viewport on tall emulator profiles too.
        test.runOnMainSync {
            val surface = activity.findViewById<ViewGroup>(android.R.id.content).getChildAt(0)
            surface.layoutParams = surface.layoutParams.apply { height = (640 * activity.resources.displayMetrics.density).toInt() }
        }
        test.waitForIdleSync()
        test.runOnMainSync {
            val all = views(activity.window.decorView)
            all.filterIsInstance<PhotoLetterDeck>().single().show(1)
            scroll = all.filterIsInstance<ScrollView>().single()
            val entry = all.first { it.contentDescription == "오늘의 질문" }
            assertTrue(hasText(activity, "주말엔 뭘 할까요?"))
            assertTrue(entry is kr.talkdock.app.ui.DailyQuestionEntryView)
            var parent = entry.parent
            while (parent is View) { assertFalse("Entry must stay outside the feed scroll", parent is ScrollView); parent = parent.parent }
        }
        test.waitForIdleSync()
        test.runOnMainSync { scroll.scrollTo(0, 40); position = scroll.scrollY; assertTrue("Fixture must actually scroll", position > 0) }
        screenshot(activity, "daily-question-home.png")
        click(activity, "오늘의 질문")
        awaitUi { hasText(activity, "가족 답변 1") }
        test.runOnMainSync { assertTrue(views(activity.window.decorView).filterIsInstance<TextView>().any { it.text.contains("같이 바람 쐬면 좋겠어.") }) }
        server.hasNewPost = true
        test.runOnMainSync { activity.onBackPressedDispatcher.onBackPressed() }
        awaitUi { hasText(activity, "가족 소식 1\n오늘은 가족에게 긴 소식을 전해요.\n우리 가족 모두 잘 지내고 있나요?") && hasText(activity, "3 / 3") &&
            views(activity.window.decorView).filterIsInstance<ScrollView>().single().scrollY == position }
        test.runOnMainSync {
            val actual = views(activity.window.decorView).filterIsInstance<ScrollView>().single()
            assertEquals(position, actual.scrollY)
            assertTrue(views(activity.window.decorView).any { it.contentDescription == "오늘의 질문" })
        }
    }

    @Test fun answerFailureKeepsDraftAndCommentsRemainPostWide() = withApp { activity, server ->
        click(activity, "오늘의 질문"); awaitUi { hasText(activity, "가족 답변 1") }
        click(activity, "밖에서 산책")
        test.runOnMainSync { editor(activity).setText("할머니와 산책하고 싶어요.") }
        server.failAnswer.set(true); click(activity, "오늘의 질문 답변 저장")
        awaitUi { hasText(activity, "답변 저장 실패 · 다시 시도해 주세요.") }
        test.runOnMainSync { assertEquals("할머니와 산책하고 싶어요.", editor(activity).text.toString()) }
        click(activity, "오늘의 질문 답변 저장"); awaitUi { hasText(activity, "가족 답변 2") }
        test.runOnMainSync {
            assertEquals("밖에서 산책", server.answer!!.getString("choice"))
            val all = views(activity.window.decorView)
            val options = all.filterIsInstance<RadioButton>().filter { it.tag == "daily-question-option" }
            assertEquals(listOf("집에서 쉬기", "밖에서 산책", "기타"), options.map { it.text.toString() })
            assertTrue(options.all { !it.isEnabled })
            assertTrue(options.single { it.text == "밖에서 산책" }.isChecked)
            assertFalse(all.filterIsInstance<TextView>().any { it.text == "이 답변에 대해 이야기" || it.text == "인용 취소" })
            val answers = all.filterIsInstance<TextView>().filter { it.tag == "daily-answer-choice" }
            assertEquals(2, answers.size)
            assertTrue(answers.all { it.typeface.isBold && it.currentTextColor == activity.getColor(kr.talkdock.app.R.color.todak_accent) })
        }
        screenshot(activity, "daily-question-answers.png")
        test.runOnMainSync { views(activity.window.decorView).filterIsInstance<EditText>().single().setText("어디로 갈까요?") }
        server.failComment.set(true); click(activity, "댓글 보내기")
        awaitUi { hasText(activity, "댓글 저장 실패 · 다시 시도해 주세요.") }
        server.failDetailAfterComment.set(true)
        click(activity, "댓글 보내기"); awaitUi { hasText(activity, "댓글 1") }
        assertEquals("An accepted comment must not be resent after refresh failure", 1, server.comments.length())
        assertEquals("어디로 갈까요?", server.comments.getJSONObject(0).getString("text"))
        click(activity, "내 답변 수정"); awaitUi { views(activity.window.decorView).filterIsInstance<EditText>().any { it.contentDescription == "오늘의 질문 답변 입력" } }
        test.runOnMainSync { editor(activity).setText("함께 공원에 가요.") }
        click(activity, "오늘의 질문 답변 저장"); awaitUi { hasText(activity, "가족 답변 2") && hasText(activity, "함께 공원에 가요.") }
    }

    @Test fun largeTextEntryAndShortAnswerRemainReadableAndHistoryOpens() = withApp(large = true, kind = "text") { activity, _ ->
        screenshot(activity, "daily-question-home-large.png")
        click(activity, "오늘의 질문"); awaitUi { hasText(activity, "가족 답변 1") }
        test.runOnMainSync { assertTrue(editor(activity).textSize / activity.resources.displayMetrics.scaledDensity >= 22f); editor(activity).setText("고무줄놀이를 좋아했어요.") }
        screenshot(activity, "daily-question-text-large.png")
        click(activity, "오늘의 질문 답변 저장"); awaitUi { hasText(activity, "가족 답변 2") }
        click(activity, "지난 질문"); awaitUi { hasText(activity, "2026-10-31\n주말엔 뭘 할까요?") }
        click(activity, "2026-10-31\n주말엔 뭘 할까요?"); awaitUi { hasText(activity, "고무줄놀이를 좋아했어요.") }
    }

    @Test fun tierInputUsesAccessibleTapSelectionInsteadOfDragging() = withApp(kind = "tier") { activity, server ->
        click(activity, "오늘의 질문"); awaitUi { hasText(activity, "가족 답변 1") }
        test.runOnMainSync {
            val choices = views(activity.window.decorView).filterIsInstance<Spinner>()
            choices[0].setSelection(1); choices[1].setSelection(3)
        }
        test.waitForIdleSync(); click(activity, "오늘의 질문 답변 저장")
        awaitUi { hasText(activity, "가족 답변 2") }
        assertEquals("S", server.answer!!.getJSONObject("tiers").getString("집에서 쉬기"))
        assertEquals("B", server.answer!!.getJSONObject("tiers").getString("밖에서 산책"))
    }

    @Test fun submittedWeatherKeepsAllChoicesInLargeText() = withApp(large = true, kind = "weather") { activity, _ ->
        click(activity, "오늘의 질문"); awaitUi { hasText(activity, "가족 답변 1") }
        click(activity, "집에서 쉬기"); click(activity, "오늘의 질문 답변 저장")
        awaitUi { hasText(activity, "가족 답변 2") }
        test.runOnMainSync {
            val options = views(activity.window.decorView).filterIsInstance<RadioButton>()
            assertEquals(3, options.size)
            assertTrue(options.single { it.text == "집에서 쉬기" }.isChecked)
            assertTrue(options.all { !it.isEnabled })
        }
        screenshot(activity, "daily-question-choice-large.png")
        click(activity, "내 답변 수정")
        awaitUi { views(activity.window.decorView).filterIsInstance<RadioButton>().all { it.isEnabled } }
        click(activity, "밖에서 산책"); click(activity, "오늘의 질문 답변 저장")
        awaitUi { views(activity.window.decorView).filterIsInstance<RadioButton>().single { it.text == "밖에서 산책" }.isChecked && hasText(activity, "가족 답변 2") }
    }

    @Test fun cancellingVoiceAnswerRestoresUnsentChoiceAndText() = withApp { activity, server ->
        test.uiAutomation.executeShellCommand("pm grant kr.talkdock.app android.permission.RECORD_AUDIO")
            .use { android.os.ParcelFileDescriptor.AutoCloseInputStream(it).readBytes() }
        click(activity, "오늘의 질문"); awaitUi { hasText(activity, "가족 답변 1") }
        click(activity, "밖에서 산책")
        test.runOnMainSync { editor(activity).setText("아직 보내지 않은 내 이야기") }
        click(activity, "말로 답하기"); awaitUi { hasText(activity, "말로 답장") }
        test.runOnMainSync { activity.onBackPressedDispatcher.onBackPressed() }
        awaitUi { views(activity.window.decorView).filterIsInstance<EditText>().any { it.contentDescription == "오늘의 질문 답변 입력" } }
        test.runOnMainSync {
            assertEquals("아직 보내지 않은 내 이야기", editor(activity).text.toString())
            assertTrue(views(activity.window.decorView).filterIsInstance<RadioButton>().single { it.text == "밖에서 산책" }.isChecked)
        }
        assertNull(server.answer)
    }

    @Test fun otherChoiceHasInlineRequiredInputAndRetainsItsValueWhenEdited() = withApp { activity, server ->
        click(activity, "오늘의 질문"); awaitUi { hasText(activity, "가족 답변 1") }
        fun other() = views(activity.window.decorView).filterIsInstance<EditText>().single { it.contentDescription == "기타 내용 입력" }
        test.runOnMainSync { assertEquals(View.GONE, other().visibility) }
        click(activity, "기타")
        awaitUi { other().visibility == View.VISIBLE }
        click(activity, "오늘의 질문 답변 저장")
        test.runOnMainSync { assertNotNull(other().error) }
        assertNull(server.answer)
        test.runOnMainSync { other().setText("노래 듣기"); editor(activity).setText("같이 듣고 싶어요.") }
        click(activity, "집에서 쉬기")
        test.runOnMainSync {
            assertEquals(View.GONE, other().visibility)
            assertEquals(1, views(activity.window.decorView).filterIsInstance<RadioButton>().count { it.isChecked })
        }
        click(activity, "기타"); test.runOnMainSync { assertEquals("노래 듣기", other().text.toString()) }
        screenshot(activity, "daily-question-other-input.png")
        click(activity, "오늘의 질문 답변 저장"); awaitUi { hasText(activity, "가족 답변 2") }
        assertEquals("노래 듣기", server.answer!!.getString("other_text"))
        test.runOnMainSync {
            assertTrue(hasText(activity, "기타 · 노래 듣기"))
            assertTrue(hasText(activity, "같이 듣고 싶어요."))
        }
        click(activity, "내 답변 수정"); awaitUi { other().visibility == View.VISIBLE }
        test.runOnMainSync { assertEquals("노래 듣기", other().text.toString()); other().setText("함께 요리") }
        click(activity, "오늘의 질문 답변 저장"); awaitUi { hasText(activity, "기타 · 함께 요리") }
        click(activity, "내 답변 수정"); click(activity, "집에서 쉬기"); click(activity, "오늘의 질문 답변 저장")
        awaitUi { hasText(activity, "가족 답변 2") && views(activity.window.decorView).filterIsInstance<RadioButton>().all { !it.isEnabled } }
        assertEquals("", server.answer!!.getString("other_text"))
    }

    @Test fun activityRecreationRestoresUnsentAnswerAndComment() = withApp { activity, server ->
        click(activity, "오늘의 질문"); awaitUi { hasText(activity, "가족 답변 1") }
        click(activity, "집에서 쉬기")
        test.runOnMainSync {
            editor(activity).setText("저장 전 답변 초안")
            views(activity.window.decorView).filterIsInstance<EditText>().single { it.contentDescription == "댓글 입력" }.setText("저장 전 댓글 초안")
            activity.recreate()
        }
        var replacement: MainActivity? = null
        awaitUi {
            replacement = ActivityLifecycleMonitorRegistry.getInstance().getActivitiesInStage(Stage.RESUMED)
                .filterIsInstance<MainActivity>().firstOrNull { it !== activity }
            replacement?.let { next -> views(next.window.decorView).filterIsInstance<EditText>().any { it.contentDescription == "오늘의 질문 답변 입력" } } == true
        }
        test.runOnMainSync {
            val next = replacement!!
            assertEquals("저장 전 답변 초안", editor(next).text.toString())
            assertEquals("저장 전 댓글 초안", views(next.window.decorView).filterIsInstance<EditText>().single { it.contentDescription == "댓글 입력" }.text.toString())
            assertTrue(views(next.window.decorView).filterIsInstance<RadioButton>().single { it.text == "집에서 쉬기" }.isChecked)
        }
        assertNull(server.answer)
    }
}
