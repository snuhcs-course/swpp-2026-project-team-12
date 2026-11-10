package kr.talkdock.app

import android.app.Dialog
import android.view.View
import android.view.ViewGroup
import android.widget.ScrollView
import android.widget.TextView
import androidx.test.ext.junit.runners.AndroidJUnit4
import kr.talkdock.app.ui.FeedPostCard
import kr.talkdock.app.ui.FeedCalendarSheet
import kr.talkdock.app.ui.FloatingAssistantView
import kr.talkdock.app.ui.GuidedHelpView
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
    private fun post(id: Int) = JSONObject().put("id", id).put("author_id", id).put("author_name", "가족$id")
        .put("relationship", "손자").put("created_at", "${date}T08:00:00+09:00")
        .put("caption", "커피와 빵으로 아침을 먹었어요. ".repeat(20)).put("images", JSONArray()).put("comment_count", 1)
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
    private fun dialog(ui: UiHarness, name: String): Dialog? = ui.activity.javaClass.getDeclaredField(name).let {
        it.isAccessible = true; it.get(ui.activity) as? Dialog
    }
    private fun descendants(root: View): List<View> = listOf(root) + if (root is ViewGroup)
        (0 until root.childCount).flatMap { descendants(root.getChildAt(it)) } else emptyList()

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
        ui.await { dialog(ui, "helpDialog")?.isShowing == true }
        ui.test.runOnMainSync { dialog(ui, "helpDialog")!!.dismiss() }
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
        assertTrue(api.requests.none { it.method == "POST" })
    } }

    @Test fun practiceDismissalKeepsFeedAndNeverPublishes() = server().use { api -> UiHarness(api, family, large = true).use { ui ->
        ui.await { dialog(ui, "helpDialog")?.isShowing == true }
        val writes = api.requests.count { it.method != "GET" }
        ui.test.runOnMainSync {
            val guide = dialog(ui, "helpDialog")!!
            assertTrue(descendants(guide.window!!.decorView).any { it is GuidedHelpView })
            guide.dismiss()
            val scroll = ui.all().filterIsInstance<ScrollView>().first(); scroll.scrollTo(0, 200)
            ui.activity.javaClass.getDeclaredMethod("showHelp").apply { isAccessible = true }.invoke(ui.activity)
        }
        ui.await { dialog(ui, "helpDialog")?.isShowing == true }
        ui.test.runOnMainSync { dialog(ui, "helpDialog")!!.dismiss() }
        ui.await { ui.all().filterIsInstance<FeedPostCard>().size == 3 }
        ui.test.runOnMainSync { assertEquals(200, ui.all().filterIsInstance<ScrollView>().first().scrollY) }
        assertEquals(writes, api.requests.count { it.method != "GET" })
    } }

    @Test fun writeAndReplyPracticeStayLocal() = server().use { api -> UiHarness(api, family, large = true).use { ui ->
        fun views() = descendants(dialog(ui, "helpDialog")!!.window!!.decorView)
        fun step(number: Int) = ui.await { dialog(ui, "helpDialog")?.isShowing == true && views().any { it.tag == "help-step:$number" } }
        fun tap(label: String) = ui.test.runOnMainSync {
            views().filterIsInstance<android.widget.Button>().first { it.text.toString() == label }.performClick()
        }
        step(1); tap("다음"); step(2)
        ui.test.runOnMainSync {
            val scroll = views().filterIsInstance<ScrollView>().first()
            val unit = ui.activity.resources.displayMetrics.density
            scroll.scrollTo(0, (unit * 140).toInt()); scroll.scrollTo(0, (unit * 60).toInt())
        }
        step(3); tap("소식 쓰기"); tap("연습 사진 추가"); tap("가족에게 전하기")
        tap("다음"); step(4); tap("토닥 도우미"); tap("음성으로 듣기"); tap("다음")
        step(5); tap("토닥 도우미"); tap("오늘 가족의 하루"); tap("다음")
        step(6); tap("댓글 달기"); tap("말로 댓글 남기기")
        ui.test.runOnMainSync { assertEquals("좋은 하루 보내세요!", views().filterIsInstance<android.widget.EditText>().single().text.toString()) }
        tap("댓글 남기기"); tap("다음"); step(7); tap("가족 소식으로 돌아가기")
        ui.await { dialog(ui, "helpDialog") == null }
        assertTrue(api.requests.none { it.method != "GET" })
    } }

    @Test fun replyPracticeWaitsForAnotherAuthorAndIsShownOnce() {
        val available = java.util.concurrent.atomic.AtomicReference(emptyList<JSONObject>())
        server { available.get() }.use { api -> UiHarness(api, family, large = true).use { ui ->
            fun refresh() = ui.test.runOnMainSync { ui.activity.javaClass
                .getDeclaredMethod("home", androidx.swiperefreshlayout.widget.SwipeRefreshLayout::class.java)
                .apply { isAccessible = true }.invoke(ui.activity, null) }
            ui.await { ui.has("사용 안내 1 / 6") }
            ui.test.runOnMainSync { dialog(ui, "helpDialog")!!.dismiss() }
            available.set(listOf(post(999)))
            refresh()
            ui.await { ui.all().filterIsInstance<FeedPostCard>().size == 1 }
            assertNull(dialog(ui, "helpDialog"))
            available.set(listOf(post(999), post(42)))
            // Wait for the visible feed's normal first-post check, without manual refresh.
            ui.await(35000) { ui.has("가족 소식에 답장해 봐요.") && ui.has("가족42님의 소식") }
            ui.test.runOnMainSync { dialog(ui, "helpDialog")!!.dismiss() }
            refresh()
            ui.await { ui.all().filterIsInstance<FeedPostCard>().size == 2 }
            assertNull(dialog(ui, "helpDialog"))
            assertTrue(api.requests.none { it.method != "GET" })
        } }
    }

    @Test fun returningFromElderlyCommentsKeepsTheSamePostPosition() = server().use { api -> UiHarness(api, family, large = true).use { ui ->
        ui.await { dialog(ui, "helpDialog")?.isShowing == true }
        ui.test.runOnMainSync { dialog(ui, "helpDialog")!!.dismiss() }
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
        ui.await { dialog(ui, "helpDialog")?.isShowing == true }
        ui.test.runOnMainSync { dialog(ui, "helpDialog")!!.dismiss() }
        ui.await { ui.has("댓글을 불러오지 못했어요.") && ui.has("댓글 다시 불러오기") }
        assertTrue(api.requests.none { it.method != "GET" })
    } }
}
