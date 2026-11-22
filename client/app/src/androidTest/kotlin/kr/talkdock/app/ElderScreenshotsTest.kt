package kr.talkdock.app

import android.view.View
import android.view.ViewGroup
import androidx.core.view.ViewCompat
import androidx.test.ext.junit.runners.AndroidJUnit4
import kr.talkdock.app.ui.FeedPostCard
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Test
import org.junit.runner.RunWith
import java.time.LocalDate
import java.time.ZoneId

/**
 * Captures the elderly screens for review. Waits are lenient: a step that does not reach its
 * state is still captured, so the images show what is actually on screen. Run with
 * -Pandroid.injected.androidTest.leaveApksInstalledAfterRun=true and pull `cache/shot-*.png`.
 */
@RunWith(AndroidJUnit4::class)
class ElderScreenshotsTest {
    private val date = LocalDate.now(ZoneId.of("Asia/Seoul")).toString()
    private val family = JSONObject().put("id", 77).put("name", "우리 가족")
        .put("members", JSONArray()).put("digest_time", "21:00").put("invite_code", "TEST77")
    private val captions = mapOf(
        1 to "할머니, 오늘 공원에서 단풍을 봤어요! 노랗고 빨간 잎이 정말 예뻤어요.",
        2 to "오늘 저녁은 된장찌개를 끓였어요. 다음에 같이 먹어요.",
        3 to "주말에 피아노 발표회가 있어요. 열심히 연습하고 있어요!")
    private val names = mapOf(1 to "지우", 2 to "민서", 3 to "준하")
    private fun post(id: Int) = JSONObject().put("id", id).put("author_id", 40 + id).put("author_name", names[id])
        .put("relationship", if (id == 2) "며느리" else "손녀").put("caption", captions[id])
        .put("created_at", "${date}T1$id:00:00+09:00").put("images", JSONArray()).put("comment_count", 1)
    private fun audio(): Reply {
        val samples = 16000 * 3
        val bytes = java.nio.ByteBuffer.allocate(44 + samples * 2).order(java.nio.ByteOrder.LITTLE_ENDIAN)
        bytes.put("RIFF".toByteArray()).putInt(36 + samples * 2).put("WAVEfmt ".toByteArray())
            .putInt(16).putShort(1).putShort(1).putInt(16000).putInt(32000).putShort(2).putShort(16)
            .put("data".toByteArray()).putInt(samples * 2)
        repeat(samples) { bytes.putShort(0) }
        return Reply(bytes.array(), type = "audio/wav")
    }
    private fun server() = MockApi { r -> when {
        r.path == "/api/families/current/" -> jsonReply(family)
        r.path == "/api/posts/" -> jsonReply(JSONObject().put("posts", JSONArray((1..3).map { post(it) })))
        r.path.matches(Regex("/api/posts/\\d+/")) -> jsonReply(post(r.path.split('/')[3].toInt()).put("comments", JSONArray().put(
            JSONObject().put("id", 5).put("author_name", "할머니").put("relationship", "할머니").put("text", "정말 예쁘구나! 감기 조심하렴."))))
        r.path.endsWith("/message/") -> jsonReply(JSONObject().put("status", "ready").put("text", "지우가 공원에서 노랗고 빨간 단풍을 보고 예쁘다고 했어요."))
        r.path == "/api/speech/" -> audio()
        r.path == "/api/digests/history/" -> jsonReply(JSONObject().put("dates", JSONArray().put(date)))
        r.path.startsWith("/api/digests/") -> jsonReply(JSONObject().put("status", "ready").put("date", date)
            .put("text", "오늘 지우는 공원에서 단풍을 봤고, 민서는 된장찌개를 끓였어요. 준하는 피아노 발표회를 준비하고 있어요.")
            .put("posts", JSONArray((1..3).map { post(it) })))
        r.path == "/api/searching/history/" -> jsonReply(JSONObject().put("text", "지난 명절에는 다 같이 모여 송편을 빚고, 저녁에는 윷놀이를 했어요.")
            .put("posts", JSONArray()))
        r.path.endsWith("/questions/") -> jsonReply(JSONObject().put("text", "지우가 다녀온 곳은 집 근처 공원이에요."))
        else -> jsonReply(JSONObject())
    } }

    private fun descendants(root: View): List<View> = listOf(root) + if (root is ViewGroup)
        (0 until root.childCount).flatMap { descendants(root.getChildAt(it)) } else emptyList()
    private fun UiHarness.cue(label: String) = all().any { ViewCompat.getStateDescription(it)?.toString() == label }
    private fun UiHarness.soft(timeout: Long = 8000, condition: () -> Boolean) =
        try { await(timeout, condition); true } catch (_: AssertionError) { false }
    private fun UiHarness.tap(find: (View) -> Boolean) = try {
        test.runOnMainSync { all().first { find(it) && it.isShown }.performClick() }; true
    } catch (_: Throwable) { false }
    private fun UiHarness.card() = all().filterIsInstance<FeedPostCard>().firstOrNull()
    private fun UiHarness.shot(name: String, report: MutableList<String>, reached: Boolean) {
        Thread.sleep(600)
        screenshot("shot-$name.png")
        report.add("$name=${if (reached) "ok" else "not-reached"}")
    }

    @Test fun captureElderlyScreens() = server().use { api -> UiHarness(api, family, large = true).use { ui ->
        val report = mutableListOf<String>()
        // First guide on the real feed: listen, reply, ask, then write.
        ui.shot("01-feed-guide-listen", report, ui.soft { ui.cue("안내: 소식 듣기") })
        ui.tap { it === ui.card()?.listenAction }
        ui.shot("02-guide-comment", report, ui.soft { ui.cue("안내: 댓글 달기") })
        ui.tap { it === ui.card()?.replyAction }
        ui.shot("03-guide-ask", report, ui.soft { ui.cue("안내: 소식 물어보기") })
        ui.tap { it.tag == "post-audio-ask" }
        ui.shot("04-ask-dialog", report, ui.soft { ui.all().any { it is kr.talkdock.app.ui.PostQuestionPanel } })
        ui.tap { it.contentDescription == "도우미 닫기" }
        ui.shot("05-guide-compose", report, ui.soft { ui.cue("안내: 소식 쓰기") })
        ui.dismissHelp()
        ui.test.runOnMainSync { ui.all().filterIsInstance<android.widget.ScrollView>().firstOrNull()?.scrollTo(0, 0) }
        ui.shot("06-feed-tabs", report, ui.soft { ui.all().any { it.tag == "elder-compose" } })
        // Listening, then replying inside the card.
        ui.tap { it === ui.card()?.listenAction }
        ui.shot("07-listen-summary-ask", report, ui.soft { ui.all().any { it.tag == "post-audio-ask" } })
        ui.tap { it === ui.card()?.replyAction }
        ui.shot("08-inline-reply", report, ui.soft { ui.all().any { it is kr.talkdock.app.ui.ElderReplyPanel } })
        ui.tap { it.contentDescription == "답장 닫기" }
        // Day tab tour.
        ui.tap { it.tag == "main-tab:digest" }
        ui.shot("09-day-tour-listen", report, ui.soft { ui.cue("안내: 오늘 하루") })
        ui.tap { it.tag == "elder-day-listen" }
        ui.shot("10-day-tour-previous", report, ui.soft { ui.cue("안내: 지난 날 보기") })
        ui.dismissHelp()
        // Memories tab tour.
        ui.tap { it.tag == "main-tab:memories" }
        ui.shot("11-memory-tour-example", report, ui.soft { ui.cue("안내: 예시로 물어보기") })
        ui.tap { it.tag == "memory-example" }
        ui.shot("12-memory-tour-answer", report, ui.soft(12000) { ui.cue("안내: 답변 듣기") })
        ui.dismissHelp()
        // Detail screen: its own listen and help buttons.
        ui.tap { it.tag == "main-tab:home" }
        ui.soft { ui.card() != null }
        ui.tap { it === ui.card() }
        ui.shot("13-detail-listen-help", report, ui.soft { ui.currentScreen() == "detail" && ui.all().any { it.tag == "elder-help" } })
        android.util.Log.i("ElderScreenshots", report.joinToString())
        java.io.File(ui.test.targetContext.cacheDir, "shot-report.txt").writeText(report.joinToString("\n"))
    } }
}
