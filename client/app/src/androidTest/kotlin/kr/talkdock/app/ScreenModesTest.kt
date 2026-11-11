package kr.talkdock.app

import android.view.View
import android.view.ViewGroup
import android.widget.ScrollView
import android.widget.TextView
import androidx.test.ext.junit.runners.AndroidJUnit4
import kr.talkdock.app.ui.FeedPostCard
import kr.talkdock.app.ui.FeedCalendarSheet
import kr.talkdock.app.ui.FloatingAssistantView
import androidx.core.view.ViewCompat
import android.widget.EditText
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.time.LocalDate
import java.time.ZoneId

/** Local mock API: no real account, family database, speech provider or AI key. */
@RunWith(AndroidJUnit4::class)
class ScreenModesTest {
    private val date = LocalDate.now(ZoneId.of("Asia/Seoul")).toString()
    private val family = JSONObject().put("id", 77).put("name", "화면 테스트 가족")
        .put("members", JSONArray()).put("digest_time", "09:00").put("invite_code", "TEST77")
    private fun post(id: Int) = JSONObject().put("id", id).put("author_id", id).put("author_name", when (id) { 42 -> "지우"; 999 -> "나"; else -> "가족$id" })
        .put("relationship", "손자").put("created_at", "${date}T08:00:00+09:00")
        .put("caption", when (id) {
            42 -> "할머니, 오늘 공원에서 단풍을 봤어요!"
            999 -> "오늘은 창가에서 차 한 잔 마셨어요."
            else -> "커피와 빵으로 아침을 먹었어요. ".repeat(20)
        }).put("images", JSONArray()).put("comment_count", 1)
    private fun server(posts: () -> List<JSONObject> = { (1..3).map { post(it) } }) = MockApi { request -> jsonReply(when {
        request.path == "/api/families/current/" -> family
        request.path == "/api/posts/" -> JSONObject().put("posts", JSONArray(posts()))
        request.path == "/api/digests/history/" -> JSONObject().put("dates", JSONArray().put(date))
        request.path.startsWith("/api/digests/") -> JSONObject().put("status", "ready").put("date", date)
            .put("text", "[손자 - 가족1] 커피와 빵으로 아침을 드셨어요.").put("posts", JSONArray().put(post(1)))
        request.path.matches(Regex("/api/posts/\\d+/")) -> post(request.path.split('/')[3].toInt()).put("comments", JSONArray().put(
            JSONObject().put("id", 5).put("author_name", "할머니").put("relationship", "할머니").put("text", "좋은 하루 보내렴!")))
        else -> JSONObject().put("text", "연습용 응답")
    }) }
    private fun descendants(root: View): List<View> = listOf(root) + if (root is ViewGroup)
        (0 until root.childCount).flatMap { descendants(root.getChildAt(it)) } else emptyList()

    private fun UiHarness.guideVisible() = all().any { it.tag == "guide-close" && it.isShown }
    private fun UiHarness.cue(label: String) = all().any { ViewCompat.getStateDescription(it)?.toString() == label }
    private fun UiHarness.editor() = all().filterIsInstance<EditText>().single()

    private fun UiHarness.captureMotion(name: String) {
        if (androidx.test.platform.app.InstrumentationRegistry.getArguments().getString("captureMotion") != "true") return
        val dir = java.io.File(test.targetContext.cacheDir, "motion/$name").apply { mkdirs() }
        repeat(20) { i ->
            val start = android.os.SystemClock.uptimeMillis()
            val screen = test.uiAutomation.takeScreenshot()
            val frame = android.graphics.Bitmap.createScaledBitmap(screen, 384, screen.height * 384 / screen.width, true)
            java.io.File(dir, "$i.png").outputStream().use { frame.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, it) }
            frame.recycle()
            screen.recycle()
            android.os.SystemClock.sleep((145 - (android.os.SystemClock.uptimeMillis() - start)).coerceAtLeast(0))
        }
    }

    @Test fun standardFeedExpandsAndDayUsesCalendar() = server().use { api -> UiHarness(api, family).use { ui ->
        ui.await { ui.all().filterIsInstance<FeedPostCard>().size == 3 }
        ui.test.runOnMainSync {
            assertEquals(3, ui.all().count { it.tag?.toString()?.startsWith("main-tab:") == true })
            val first = ui.all().filterIsInstance<FeedPostCard>().first()
            val caption = descendants(first).filterIsInstance<TextView>().single { it.tag == "feed-caption" }
            assertEquals(2, caption.maxLines)
            for (name in listOf("댓글 1", "말로 댓글", "소식 듣기")) {
                val action = descendants(first).single { it.contentDescription == name }
                assertTrue(descendants(action).filterIsInstance<TextView>().isEmpty())
                assertTrue(action.minimumHeight >= ui.activity.resources.displayMetrics.density * 48)
            }
            val more = ui.all().filterIsInstance<TextView>().first { it.text.toString() == "더보기" }
            assertTrue(more.performClick()); assertEquals(View.GONE, more.visibility)
            ui.all().single { it.tag == "main-tab:digest" }.performClick()
        }
        ui.await { ui.all().any { it is FeedCalendarSheet } && ui.has("오늘 이야기 보기") }
        ui.click("오늘 이야기 보기")
        ui.await { ui.has("오늘도, 함께") }
        ui.screenshot("standard-day-story.png")
    } }

    @Test fun shortThreeLineCaptionStillOffersMore() = server().use { api -> UiHarness(api, family).use { ui ->
        ui.await { ui.all().filterIsInstance<FeedPostCard>().size == 3 }
        lateinit var caption: TextView
        lateinit var more: TextView
        ui.test.runOnMainSync {
            val card = ui.all().filterIsInstance<FeedPostCard>().first()
            caption = descendants(card).filterIsInstance<TextView>().single { it.tag == "feed-caption" }
            more = descendants(card).filterIsInstance<TextView>().single { it.text == "더보기" }
            caption.text = "첫째 줄\n둘째 줄\n셋째 줄"
        }
        ui.await { more.visibility == View.VISIBLE && caption.maxLines == 2 }
        ui.test.runOnMainSync { caption.text = "짧은 한 줄" }
        ui.await { more.visibility == View.GONE }
        ui.test.runOnMainSync { caption.text = "첫째 줄\n둘째 줄\n셋째 줄" }
        ui.await { more.visibility == View.VISIBLE }
        ui.test.runOnMainSync { more.performClick(); assertEquals(Int.MAX_VALUE, caption.maxLines) }
    } }

    @Test fun elderlyModeHasSingleComposeAndLabeledRightBotWithInlineComments() = server().use { api -> UiHarness(api, family, large = true).use { ui ->
        ui.await { ui.guideVisible() }
        ui.dismissHelp()
        ui.await { ui.all().filterIsInstance<FeedPostCard>().size == 3 }
        ui.await { ui.has("좋은 하루 보내렴!") }
        ui.test.runOnMainSync {
            assertTrue(ui.all().none { it.tag?.toString()?.startsWith("main-tab:") == true })
            assertEquals(1, ui.all().count { it.tag == "elder-compose" })
            val bot = ui.all().filterIsInstance<FloatingAssistantView>().single()
            assertEquals("Bot docks to right", (bot.parent as View).width.toFloat(), bot.x + bot.width, 2f)
            val label = descendants(bot).filterIsInstance<TextView>().single { it.tag == "assistant-label" }
            assertEquals("토닥 도우미", label.text.toString())
            assertTrue(label.top >= bot.getChildAt(0).bottom)
            ui.all().single { it.tag == "elder-compose" }.performClick()
        }
        ui.await { ui.has("가족에게 전하기") }
        assertTrue(api.requests.none { it.method == "POST" && it.path != "/api/speech/" })
    } }

    @Test fun readingAndReplayUseTheRealFeed() = server { listOf(post(42)) }.use { api -> UiHarness(api, family, large = true).use { ui ->
        ui.await { ui.cue("안내: 소식 보기") }
        ui.captureMotion("read")
        ui.screenshot("01-read.png")
        ui.test.runOnMainSync { ui.all().filterIsInstance<FeedPostCard>().single().performClick() }
        ui.await { ui.cue("안내: 소식 목록으로 돌아가기") }
        ui.test.runOnMainSync { ui.all().single { it.contentDescription == "이전 화면" }.performClick() }
        ui.await { ui.cue("안내: 소식 쓰기") }
        ui.openAssistantOption("도움말")
        ui.await { ui.cue("안내: 소식 보기") }
        ui.dismissHelp()
        assertTrue(!ui.guideVisible())
        assertTrue(api.requests.none { it.method == "POST" && it.path != "/api/speech/" })
    } }

    private fun UiHarness.playing(): android.media.MediaPlayer? {
        val narrator = activity.javaClass.getDeclaredField("narrator").apply { isAccessible = true }.get(activity)
        val player = narrator.javaClass.getDeclaredField("player").apply { isAccessible = true }.get(narrator)
            as? android.media.MediaPlayer
        return player?.takeIf { it.isPlaying }
    }

    @Test fun unavailableSpeechFallsBackAndRemembersMute() {
        val context = androidx.test.platform.app.InstrumentationRegistry.getInstrumentation().targetContext
        val settings = context.getSharedPreferences("tutorial-audio", 0)
        val original = settings.all["enabled"] as? Boolean
        settings.edit().putBoolean("enabled", true).commit()
        fun UiHarness.toggle(label: String) = test.runOnMainSync {
            all().single { it.isShown && it.contentDescription == label }.performClick()
        }
        try {
            server { emptyList() }.use { api ->
                UiHarness(api, family, large = true).use { ui ->
                    ui.await { ui.cue("안내: 소식 쓰기") && ui.playing() != null }
                    ui.toggle("튜토리얼 음성 끄기")
                    ui.await { ui.playing() == null && ui.cue("안내: 소식 쓰기") }
                    ui.click("소식 쓰기")
                    ui.await { ui.cue("안내: 소식 입력") && ui.editor().hint == "오늘 있었던 일을 적어보세요" }
                    assertFalse(settings.getBoolean("enabled", true))
                    ui.test.runOnMainSync { assertNull(ui.playing()) }
                }
                UiHarness(api, family, large = true).use { ui ->
                    ui.await { ui.all().any { it.contentDescription == "튜토리얼 음성 켜기" && it.isShown } }
                    ui.toggle("튜토리얼 음성 켜기")
                    ui.await { ui.playing() != null }
                    ui.dismissHelp()
                    ui.await { ui.playing() == null && !ui.guideVisible() }
                }
                assertEquals(2, api.paths().count { it == "/api/speech/" })
            }
        } finally {
            val edit = settings.edit()
            if (original == null) edit.remove("enabled") else edit.putBoolean("enabled", original)
            edit.commit()
        }
    }

    @Test fun guidePlaysTheAuthenticatedResponseAndDropsAMutedRequest() {
        val context = androidx.test.platform.app.InstrumentationRegistry.getInstrumentation().targetContext
        val fixture = R.raw.guide_read_post  // Deliberately different from the COMPOSE fallback.
        val bytes = context.resources.openRawResource(fixture).use { it.readBytes() }
        val probe = android.media.MediaPlayer.create(context, fixture)
        val duration = try { probe.duration } finally { probe.release() }
        val slow = java.util.concurrent.CountDownLatch(1)
        MockApi { request ->
            when (request.path) {
                "/api/families/current/" -> jsonReply(family)
                "/api/posts/" -> jsonReply(JSONObject().put("posts", JSONArray()))
                "/api/speech/" -> {
                    slow.await(5, java.util.concurrent.TimeUnit.SECONDS)
                    Reply(bytes, type = "audio/mp4")
                }
                else -> jsonReply(JSONObject())
            }
        }.use { api -> UiHarness(api, family, large = true).use { ui ->
            fun toggle(label: String) = ui.test.runOnMainSync {
                ui.all().single { it.isShown && it.contentDescription == label }.performClick()
            }
            ui.await { api.paths().contains("/api/speech/") }
            try {
                toggle("튜토리얼 음성 끄기")
            } finally { slow.countDown() }
            ui.test.waitForIdleSync()
            ui.test.runOnMainSync { assertNull(ui.playing()) }
            toggle("튜토리얼 음성 켜기")
            ui.await { ui.playing()?.duration == duration }
            val calls = synchronized(api.requests) { api.requests.filter { it.path == "/api/speech/" } }
            assertEquals(2, calls.size)
            for (call in calls) {
                assertEquals("mock-review-token", call.token)
                assertEquals("77", call.room)
                assertEquals("아래에 있는 소식 쓰기를 눌러 보세요.", JSONObject(call.body).getString("text"))
            }
        } }
    }

    @Test fun listeningToAPostInterruptsTutorialSpeech() = server { listOf(post(42)) }.use { api ->
        UiHarness(api, family, large = true).use { ui ->
            ui.await { ui.playing() != null }
            ui.test.runOnMainSync {
                val post = ui.all().filterIsInstance<FeedPostCard>().single()
                descendants(post).single { it.contentDescription == "소식 듣기" }.performClick()
                assertNull(ui.playing())
            }
            ui.await { api.paths().any { it.startsWith("/api/posts/42/message/") } }
        }
    }

    @Test fun composeGuideKeepsDraftAndUsesRealPublish() = server { emptyList() }.use { api -> UiHarness(api, family, large = true).use { ui ->
        ui.await { ui.cue("안내: 소식 쓰기") }
        ui.screenshot("02-empty-feed.png")
        ui.click("소식 쓰기")
        ui.await { ui.cue("안내: 소식 입력") }
        ui.captureMotion("write")
        ui.await { ui.editor().hint == "오늘 있었던 일을 적어보세요" && ui.editor().text.isEmpty() }
        ui.screenshot("03-write.png")
        val draft = "오늘은 마당에 국화가 피었어요."
        ui.test.runOnMainSync { ui.all().filterIsInstance<android.widget.EditText>().single().setText(draft) }
        ui.await { !ui.cue("안내: 소식 입력") && ui.editor().text.toString() == draft }
        ui.test.runOnMainSync { ui.all().filterIsInstance<ScrollView>().first().fullScroll(View.FOCUS_DOWN) }
        ui.screenshot("04-publish.png")
        ui.dismissHelp()
        assertTrue(ui.has(draft))
        assertTrue(api.requests.none { it.method == "POST" && it.path != "/api/speech/" })
        ui.click("가족에게 전하기")
        ui.await { api.requests.count { it.method == "POST" && it.path == "/api/posts/" } == 1 }
    } }

    @Test fun replyGuideWaitsForAnotherAuthorAndUsesRealComment() {
        val available = java.util.concurrent.atomic.AtomicReference(emptyList<JSONObject>())
        server { available.get() }.use { api -> UiHarness(api, family, large = true).use { ui ->
            fun refresh() = ui.test.runOnMainSync { ui.activity.javaClass
                .getDeclaredMethod("home", androidx.swiperefreshlayout.widget.SwipeRefreshLayout::class.java)
                .apply { isAccessible = true }.invoke(ui.activity, null) }
            ui.await { ui.cue("안내: 소식 쓰기") }
            ui.dismissHelp()
            available.set(listOf(post(999)))
            refresh()
            ui.await { ui.all().filterIsInstance<FeedPostCard>().size == 1 }
            assertTrue(!ui.guideVisible())
            available.set(listOf(post(999), post(42)))
            ui.await(35000) { ui.cue("안내: 가족 글에 답장하기") }
            ui.captureMotion("family")
            ui.screenshot("05-family-reply.png")
            ui.test.runOnMainSync {
                val other = ui.all().filterIsInstance<FeedPostCard>().single { it.post.getInt("id") == 42 }
                assertEquals("안내: 가족 글에 답장하기", ViewCompat.getStateDescription(other))
                other.performClick()
            }
            ui.await { ui.cue("안내: 댓글 입력") }
            ui.captureMotion("comment")
            ui.await { ui.editor().hint == "하고 싶은 말씀을 적어보세요" && ui.editor().text.isEmpty() }
            assertTrue(ui.all().single { it.contentDescription == "댓글 보내기" }.visibility == View.GONE)
            ui.screenshot("06-comment.png")
            val draft = "지우야, 단풍이 참 예쁘네!"
            ui.test.runOnMainSync { ui.all().filterIsInstance<android.widget.EditText>().single().setText(draft) }
            ui.await { ui.cue("안내: 댓글 보내기") }
            ui.captureMotion("send")
            ui.screenshot("07-send-comment.png")
            ui.test.runOnMainSync { ui.editor().setText("") }
            ui.await { ui.cue("안내: 댓글 입력") && !ui.cue("안내: 댓글 보내기") }
            ui.test.runOnMainSync { ui.editor().setText(draft) }
            ui.dismissHelp()
            assertTrue(ui.has(draft))
            assertTrue(api.requests.none { it.method == "POST" && it.path != "/api/speech/" })
            val detailReads = api.paths().count { it == "/api/posts/42/" }
            ui.test.runOnMainSync { ui.all().single { it.contentDescription == "댓글 보내기" }.performClick() }
            ui.await { api.requests.count { it.method == "POST" && it.path == "/api/posts/42/comments/" } == 1 }
            ui.await(10000) { api.paths().count { it == "/api/posts/42/" } > detailReads &&
                ui.hasPostDetail() && ui.all().none { it is kr.talkdock.app.ui.TodakSuccessView } }
            ui.test.runOnMainSync { ui.all().single { it.contentDescription == "이전 화면" }.performClick() }
            ui.await { ui.all().filterIsInstance<FeedPostCard>().size == 2 }
            assertTrue(!ui.guideVisible())
        } }
    }

    @Test fun returningFromElderlyCommentsKeepsTheSamePostPosition() = server().use { api -> UiHarness(api, family, large = true).use { ui ->
        ui.await { ui.guideVisible() }
        ui.dismissHelp()
        ui.await { ui.all().filterIsInstance<FeedPostCard>().size == 3 }
        ui.test.runOnMainSync {
            val card = ui.all().filterIsInstance<FeedPostCard>().single { it.post.getInt("id") == 2 }
            ui.all().filterIsInstance<ScrollView>().first().scrollTo(0, card.top + 80)
        }
        ui.await { ui.all().filterIsInstance<FeedPostCard>().single { it.post.getInt("id") == 2 }.commentsLoaded }
        var offset = 0
        ui.test.runOnMainSync {
            val card = ui.all().filterIsInstance<FeedPostCard>().single { it.post.getInt("id") == 2 }
            val scroll = ui.all().filterIsInstance<ScrollView>().first()
            offset = card.top - scroll.scrollY
            descendants(card).single { it.contentDescription == "댓글 달기" }.performClick()
        }
        ui.await { ui.has("가족의 소식") && ui.has("댓글 1") }
        ui.test.runOnMainSync { ui.all().single { it.contentDescription == "이전 화면" }.performClick() }
        ui.await { ui.all().filterIsInstance<FeedPostCard>().size == 3 }
        ui.await {
            val card = ui.all().filterIsInstance<FeedPostCard>().single { it.post.getInt("id") == 2 }
            kotlin.math.abs(card.top - ui.all().filterIsInstance<ScrollView>().first().scrollY - offset) <= 2
        }
    } }

    @Test fun invalidCommentResponseShowsRetryInsteadOfCrashing() = MockApi { request ->
        jsonReply(when (request.path) {
            "/api/families/current/" -> family
            "/api/posts/" -> JSONObject().put("posts", JSONArray().put(post(1)))
            else -> JSONObject().put("unexpected", true)
        })
    }.use { api -> UiHarness(api, family, large = true).use { ui ->
        ui.await { ui.guideVisible() }
        ui.dismissHelp()
        ui.await { ui.has("댓글을 불러오지 못했어요.") && ui.has("댓글 다시 불러오기") }
        assertTrue(api.requests.none { it.method != "GET" && it.path != "/api/speech/" })
    } }
}
