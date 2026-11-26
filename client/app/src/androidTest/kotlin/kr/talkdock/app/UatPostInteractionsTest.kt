package kr.talkdock.app

import android.Manifest
import android.graphics.Rect
import android.view.View
import android.view.inputmethod.InputMethodManager
import android.content.Context
import android.widget.ScrollView
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.test.ext.junit.runners.AndroidJUnit4
import kr.talkdock.app.ui.CommentComposer
import kr.talkdock.app.ui.FeedPostCard
import kr.talkdock.app.ui.InlinePostAudio
import kr.talkdock.app.ui.TodakWaitingView
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

@RunWith(AndroidJUnit4::class)
class UatPostInteractionsTest {
    private fun post(id: Int = 1) = JSONObject().put("id", id).put("author_id", 1)
        .put("author_name", "준하").put("relationship", "손자")
        .put("caption", "산책하고 집에 왔어요. ".repeat(16)).put("created_at", "2026-11-17T10:00:00+09:00")
        .put("images", JSONArray()).put("comment_count", 25)
    private fun detail() = post().put("comments", JSONArray().apply { repeat(25) {
        put(JSONObject().put("id", it + 1).put("author_name", "정순").put("relationship", "할머니").put("text", "가족의 댓글 $it")
            .put("created_at", "2026-11-17T10:00:00+09:00"))
    } })
    private fun server(extra: (Request) -> Reply? = { null }) = MockApi { r -> extra(r) ?: when {
        r.path == "/api/families/current/" -> jsonReply(room(1, "우리 가족"))
        r.path == "/api/posts/" -> jsonReply(JSONObject().put("posts", JSONArray().apply { (1..6).forEach { put(post(it)) } }))
        r.path.matches(Regex("/api/posts/\\d+/")) -> jsonReply(detail())
        r.path.endsWith("/comments/") -> jsonReply(JSONObject().put("error", "보내지 못했어요. 다시 시도해 주세요."), 400)
        r.path.endsWith("/message/") -> jsonReply(JSONObject().put("status", "ready").put("text", "준하가 산책하고 집에 왔어요."))
        r.path == "/api/speech/voices/" -> jsonReply(JSONObject().put("voices", JSONArray()))
        else -> emptyFeed()
    } }
    private fun tap(ui: UiHarness, label: String) = ui.test.runOnMainSync {
        ui.all().first { it.contentDescription == label && it.isShown }.performClick()
    }

    @Test fun cachedFeedReturnsBeforeRefreshAndPreservesReadingPosition() {
        val reads = AtomicInteger(); val gate = CountDownLatch(1)
        server { r -> if (r.path == "/api/posts/" && reads.incrementAndGet() > 1) {
            gate.await(8, TimeUnit.SECONDS); null
        } else null }.use { api -> UiHarness(api, room(1, "우리 가족")).use { ui ->
            ui.await { ui.all().filterIsInstance<FeedPostCard>().size == 6 }
            var position = 0
            ui.test.runOnMainSync {
                ui.all().filterIsInstance<ScrollView>().first().apply { scrollTo(0, 350); position = scrollY }
                MainActivity::class.java.getDeclaredMethod("composer").apply { isAccessible = true }.invoke(ui.activity)
            }
            ui.await { ui.has("소식 쓰기") }
            ui.test.runOnMainSync { ui.activity.onBackPressedDispatcher.onBackPressed() }
            ui.await { ui.all().filterIsInstance<FeedPostCard>().size == 6 }
            ui.test.runOnMainSync {
                assertFalse(ui.all().any { it is TodakWaitingView })
                assertEquals(position, ui.all().filterIsInstance<ScrollView>().first().scrollY)
            }
            gate.countDown()
            ui.screenshot("uat-cached-feed.png")
        } }
    }

    @Test fun failedRefreshKeepsCachedPostsAndNextVisitLoadsChanges() {
        val reads = AtomicInteger()
        server { r -> if (r.path == "/api/posts/") when (reads.incrementAndGet()) {
            1 -> null
            2 -> jsonReply(JSONObject().put("error", "연결을 다시 확인해 주세요."), 400)
            else -> jsonReply(JSONObject().put("posts", JSONArray().put(post().put("caption", "새로 도착한 소식"))))
        } else null }.use { api -> UiHarness(api, room(1, "우리 가족"), tutorialSeen = true).use { ui ->
            ui.await { ui.all().filterIsInstance<FeedPostCard>().size == 6 }
            repeat(2) { attempt ->
                ui.test.runOnMainSync { MainActivity::class.java.getDeclaredMethod("composer").apply { isAccessible = true }.invoke(ui.activity) }
                ui.await { ui.has("소식 쓰기") }
                ui.test.runOnMainSync { ui.activity.onBackPressedDispatcher.onBackPressed() }
                ui.await { reads.get() >= attempt + 2 }
                if (attempt == 0) ui.test.runOnMainSync { assertEquals(6, ui.all().filterIsInstance<FeedPostCard>().size) }
                else ui.await { ui.has("새로 도착한 소식") }
            }
        } }
    }

    @Test fun switchingFamilyCannotShowThePreviousFamilysSnapshot() {
        val gate = CountDownLatch(1)
        server { r -> if (r.path == "/api/posts/" && r.room == "2") {
            gate.await(8, TimeUnit.SECONDS)
            jsonReply(JSONObject().put("posts", JSONArray().put(post().put("caption", "두 번째 가족의 소식"))))
        } else null }.use { api -> UiHarness(api, room(1, "우리 가족"), tutorialSeen = true).use { ui ->
            ui.await { ui.all().any { it is FeedPostCard } }
            ui.test.runOnMainSync {
                val account = JSONObject().put("user_id", 999).put("username", "review-user").put("name", "테스트 사용자")
                    .put("token", "mock-review-token").put("room", room(2, "두 번째 가족"))
                MainActivity::class.java.getDeclaredMethod("saveSession", JSONObject::class.java, Boolean::class.javaPrimitiveType)
                    .apply { isAccessible = true }.invoke(ui.activity, account, false)
                MainActivity::class.java.getDeclaredMethod("home", androidx.swiperefreshlayout.widget.SwipeRefreshLayout::class.java)
                    .apply { isAccessible = true }.invoke(ui.activity, null)
                assertFalse(ui.all().any { it is FeedPostCard })
                assertTrue(ui.all().any { it is TodakWaitingView })
            }
            gate.countDown(); ui.await { ui.has("두 번째 가족의 소식") }
        } }
    }

    @Test fun bothCommentRoutesKeepComposerAboveKeyboardAndRetainFailedDraft() {
        // First-use guidance is covered separately; keep it from competing for focus here.
        for (large in listOf(false, true)) server().use { api -> UiHarness(api, room(1, "우리 가족"), large, tutorialSeen = true).use { ui ->
            ui.await { ui.all().any { it is FeedPostCard } }
            // The elderly detail screen keeps its composer outside the history; 댓글 달기 itself replies in the card.
            if (large) ui.openCurrentPost() else tap(ui, "댓글 25")
            ui.await { ui.all().any { it is CommentComposer } }
            val composer = ui.all().filterIsInstance<CommentComposer>().single()
            ui.await { composer.hasWindowFocus() && composer.input.width > 0 && !composer.isLayoutRequested }
            val keyboard = ui.activity.getSystemService(Context.INPUT_METHOD_SERVICE) as InputMethodManager
            ui.test.runOnMainSync {
                composer.input.setText("수정 없이 남아야 하는 댓글"); composer.input.requestFocus()
            }
            // Window focus can arrive before the IME has attached to this editor,
            // especially when the regular-mode dialog is opened on the CI emulator.
            ui.await { composer.input.hasFocus() && keyboard.isActive(composer.input) }
            ui.test.runOnMainSync {
                ViewCompat.getWindowInsetsController(composer.input)?.show(WindowInsetsCompat.Type.ime())
            }
            ui.await(timeout = 15000) { ViewCompat.getRootWindowInsets(composer)?.isVisible(WindowInsetsCompat.Type.ime()) == true }
            ui.screenshot(if (large) "uat-elder-keyboard.png" else "uat-sheet-keyboard.png")
            Thread.sleep(400)
            ui.test.runOnMainSync {
                val visible = Rect(); composer.getWindowVisibleDisplayFrame(visible)
                val location = IntArray(2); composer.sendButton.getLocationOnScreen(location)
                assertTrue("Send must be entirely above keyboard", location[1] + composer.sendButton.height <= visible.bottom)
                val list = ui.all().filterIsInstance<ScrollView>().last()
                val listLocation = IntArray(2); list.getLocationOnScreen(listLocation)
                val composerLocation = IntArray(2); composer.getLocationOnScreen(composerLocation)
                assertTrue("History must not overlap reply controls", listLocation[1] + list.height <= composerLocation[1])
                composer.sendButton.performClick()
            }
            ui.await { ui.has("보내지 못했어요. 다시 시도해 주세요.") }
            ui.test.runOnMainSync { assertEquals("수정 없이 남아야 하는 댓글", composer.input.text.toString()); assertTrue(composer.sendButton.isEnabled) }
            ui.screenshot(if (large) "uat-elder-comment-keyboard.png" else "uat-comment-sheet-keyboard.png")
        } }
    }

    @Test fun commentSheetHasOpaqueSurfaceAndKeepsTypedReplyAboveKeyboard() {
        val sample = post().put("author_name", "김대협").put("caption", "따뜻한 커피와 빵으로 아침을 시작했어요.").put("comment_count", 3)
        val comments = JSONArray().apply {
            listOf("할머니" to "맛있겠다! 아침 든든하게 챙겨 먹어서 좋네.",
                "엄마" to "오늘도 좋은 하루 보내렴.",
                "홍정아" to "빵 정말 맛있어 보여요. 다음에는 같이 가요!").forEachIndexed { index, (name, text) ->
                put(JSONObject().put("id", index + 1).put("author_name", name).put("text", text))
            }
        }
        server { request -> when (request.path) {
            "/api/posts/" -> jsonReply(JSONObject().put("posts", JSONArray().put(sample)))
            "/api/posts/1/" -> jsonReply(JSONObject(sample.toString()).put("comments", comments))
            else -> null
        } }.use { api -> UiHarness(api, room(1, "우리 가족"), tutorialSeen = true).use { ui ->
            ui.await { ui.all().any { it is FeedPostCard } }
            tap(ui, "댓글 3")
            ui.await { ui.all().any { it.tag == "sheet-comment" && it.width > 0 && !it.isLayoutRequested } }
            val composer = ui.all().filterIsInstance<CommentComposer>().single()
            // Capture after the dialog's entrance transition; sampling mid-fade measures
            // the window animation's opacity rather than the panel's reading surface.
            ui.screenshot("comment-sheet-readable.png")
            val samplePoints = mutableListOf<Pair<Int, Int>>()
            ui.test.runOnMainSync {
                val panel = ui.all().single { it.tag == "comment-sheet-panel" }
                val header = ui.all().single { it.tag == "comment-sheet-header" }
                val list = ui.all().single { it.tag == "comment-list-scroll" }
                val panelBounds = Rect(); val headerBounds = Rect(); val listBounds = Rect()
                assertTrue(panel.getGlobalVisibleRect(panelBounds))
                assertTrue(header.getGlobalVisibleRect(headerBounds))
                assertTrue(list.getGlobalVisibleRect(listBounds))
                assertTrue("Title must stay inside the reading surface", panelBounds.contains(headerBounds))
                assertTrue("Comments must stay inside the reading surface", panelBounds.contains(listBounds))
                samplePoints.add(headerBounds.centerX() to headerBounds.centerY())
                samplePoints.add((listBounds.left + 4) to listBounds.centerY())
            }
            val screenshot = ui.test.uiAutomation.takeScreenshot()
            try {
                samplePoints.forEach { (x, y) ->
                    assertEquals("The post behind the sheet must not bleed through", android.graphics.Color.WHITE, screenshot.getPixel(x, y))
                }
            } finally { screenshot.recycle() }

            val draft = "맛있겠다! 다음에는 같이 먹어요.\n오늘도 좋은 하루 보내세요."
            val keyboard = ui.activity.getSystemService(Context.INPUT_METHOD_SERVICE) as InputMethodManager
            ui.test.runOnMainSync { composer.input.setText(draft); composer.input.requestFocus() }
            ui.await { composer.input.hasFocus() && keyboard.isActive(composer.input) }
            ui.test.runOnMainSync { ViewCompat.getWindowInsetsController(composer.input)?.show(WindowInsetsCompat.Type.ime()) }
            ui.await(timeout = 15000) { ViewCompat.getRootWindowInsets(composer)?.isVisible(WindowInsetsCompat.Type.ime()) == true }
            ui.await {
                val visible = Rect(); composer.getWindowVisibleDisplayFrame(visible)
                val send = Rect(); val field = Rect(); val list = Rect()
                val header = ui.all().single { it.tag == "comment-sheet-header" }; val title = Rect()
                composer.sendButton.getGlobalVisibleRect(send) && composer.input.getGlobalVisibleRect(field) &&
                    ui.all().single { it.tag == "comment-list-scroll" }.getGlobalVisibleRect(list) &&
                    header.getGlobalVisibleRect(title) && title.height() == header.height && title.top >= visible.top &&
                    send.height() == composer.sendButton.height && send.bottom <= visible.bottom &&
                    field.height() == composer.input.height && list.bottom <= field.top
            }
            ui.screenshot("comment-sheet-typing.png")
            tap(ui, "댓글 닫기")
            ui.await { ui.all().none { it.tag == "sheet-comment" } }
            tap(ui, "댓글 3")
            ui.await { ui.all().filterIsInstance<CommentComposer>().any { it.input.text.toString() == draft } }
            assertFalse("Closing a draft must not send it", api.paths().any { it.endsWith("/comments/") })
        } }
    }

    @Test fun visibleCancelPreventsLateSummaryFromStartingSpeech() {
        val gate = CountDownLatch(1)
        server { r -> if (r.path.endsWith("/message/")) { gate.await(12, TimeUnit.SECONDS); jsonReply(JSONObject().put("status", "ready").put("text", "늦게 도착한 요약")) } else null }
            .use { api -> UiHarness(api, room(1, "우리 가족")).use { ui ->
                ui.openCurrentPost()
                ui.test.runOnMainSync { ui.all().filterIsInstance<InlinePostAudio>().single().togglePlayback() }
                try {
                    // The loading animation can keep instrumentation from ever observing an idle frame.
                    ui.await { api.paths().any { it.endsWith("/message/") } &&
                        ui.all().any { it.tag == "post-audio-stop" && it.isShown } }
                    tap(ui, "음성 준비 취소")
                } finally { gate.countDown() }
                Thread.sleep(500)
                ui.test.runOnMainSync { assertFalse(ui.all().filterIsInstance<InlinePostAudio>().single().isPlaying) }
                assertFalse(api.paths().contains("/api/speech/"))
            } }
    }

    @Test fun detailHelpCanBeReopenedAndClosedWithTheFixedComposer() {
        server().use { api -> UiHarness(api, room(1, "우리 가족"), large = true, tutorialSeen = true).use { ui ->
            // The elderly detail header has its own help button instead of the assistant menu.
            ui.openCurrentPost(); ui.screenshot("elder-13-detail-listen-help.png")
            ui.test.runOnMainSync { ui.all().single { it.tag == "elder-help" }.performClick() }
            ui.await { ui.all().any { ViewCompat.getStateDescription(it) == "안내: 댓글 입력" } }
            ui.dismissHelp()
            ui.test.runOnMainSync {
                assertFalse(ui.all().any { it.tag == "guide-close" && it.isShown })
                assertTrue(ui.all().filterIsInstance<CommentComposer>().single().input.text.isEmpty())
            }
        } }
    }

    @Test fun voiceReplyWaitsForStartAndRerecordReturnsToIdle() {
        server { r -> when {
            r.path.endsWith("/transcribe/") -> jsonReply(JSONObject().put("recognized", "잘 먹었어"))
            r.path.endsWith("/prepare/") -> jsonReply(JSONObject().put("id", 55).put("recognized", "잘 먹었어").put("converted", "잘 먹었어"))
            else -> null
        } }.use { api -> UiHarness(api, room(1, "우리 가족")).use { ui ->
            ui.openCurrentPost(); tap(ui, "말로 댓글 쓰기")
            ui.await { ui.has("버튼을 누르고 말씀해 주세요") }
            ui.test.uiAutomation.grantRuntimePermission(ui.activity.packageName, Manifest.permission.RECORD_AUDIO)
            Thread.sleep(300)
            ui.test.runOnMainSync { assertFalse(ui.has("듣고 있어요")) }
            ui.screenshot("uat-voice-idle.png")
            tap(ui, "말하기 시작"); ui.await { ui.has("듣고 있어요") }; Thread.sleep(900)
            tap(ui, "말하기 마치기")
            ui.await { ui.has("답장 확인") }
            ui.click("다시 말하기"); ui.await { ui.has("버튼을 누르고 말씀해 주세요") }
            assertFalse(api.paths().any { it.endsWith("/send/") })
            ui.test.runOnMainSync { assertFalse(ui.has("듣고 있어요")) }
        } }
    }
}
