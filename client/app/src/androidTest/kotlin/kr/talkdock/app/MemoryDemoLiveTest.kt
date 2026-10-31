package kr.talkdock.app

import android.content.Intent
import android.graphics.Bitmap
import android.os.SystemClock
import android.view.View
import android.view.ViewGroup
import android.widget.ScrollView
import android.widget.TextView
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import kr.talkdock.app.ui.FamilyMemoryPanel
import kr.talkdock.app.ui.FloatingAssistantView
import kr.talkdock.app.ui.PhotoLetterDeck
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.json.JSONObject
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/** Opt in only for the isolated synthetic demo; the normal CI suite skips it. */
@RunWith(AndroidJUnit4::class)
class MemoryDemoLiveTest {
    @Test fun realGraphitiAnswerRendersTheOriginalV2LetterAndRetainsItOnReturn() {
        assumeTrue(InstrumentationRegistry.getArguments().getString("liveMemoryDemo") == "true")
        val test = InstrumentationRegistry.getInstrumentation()
        assumeTrue(test.targetContext.packageName.endsWith(".memorydemo"))
        val prefs = test.targetContext.getSharedPreferences("talkdock-session", android.content.Context.MODE_PRIVATE)
        assumeTrue(prefs.getString("server", "") == "http://10.0.2.2:8001/api/")
        assumeTrue(JSONObject(prefs.getString("current", "{}")!!).optJSONObject("room")?.optInt("id") == 961031)
        val activity = test.startActivitySync(Intent(test.targetContext, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)) as MainActivity
        fun views(view: View = activity.window.decorView): List<View> = listOf(view) +
            if (view is ViewGroup) (0 until view.childCount).flatMap { views(view.getChildAt(it)) } else emptyList()
        fun waitFor(timeout: Long = 15000, condition: () -> Boolean) {
            val deadline = SystemClock.uptimeMillis() + timeout
            while (SystemClock.uptimeMillis() < deadline) {
                var ready = false
                test.runOnMainSync { ready = condition() }
                if (ready) return
                Thread.sleep(50)
            }
            fail("Live demo condition timed out")
        }
        waitFor { views().any { it is PhotoLetterDeck } }
        test.runOnMainSync { views().filterIsInstance<FloatingAssistantView>().single().performClick() }
        waitFor { views().filterIsInstance<TextView>().any { it.text.toString() == "가족 추억 찾기" } }
        test.runOnMainSync {
            var action: View = views().filterIsInstance<TextView>().first { it.text.toString() == "가족 추억 찾기" }
            while (!action.isClickable && action.parent is View) action = action.parent as View
            action.performClick()
        }
        waitFor { views().any { it is FamilyMemoryPanel } }
        test.runOnMainSync {
            val panel = views().filterIsInstance<FamilyMemoryPanel>().single()
            panel.input.setText("지난 가족 여행은 어디로 갔고 뭘 먹었어?")
            panel.searchButton.performClick()
        }
        waitFor(180000) { views().any { it is PhotoLetterDeck } }
        test.runOnMainSync {
            val letters = views().filterIsInstance<PhotoLetterDeck>()
            assertTrue(letters.isNotEmpty())
            assertTrue(letters.any { it.currentPost.optString("caption").contains("부산") })
            assertTrue(views().filterIsInstance<TextView>().any { it.text.contains("돼지국밥") })
            val heading = views().filterIsInstance<TextView>().first { it.text.toString() == "토닥이 찾은 이야기" }
            val scroll = views().filterIsInstance<ScrollView>().first()
            val titlePosition = IntArray(2); val viewportPosition = IntArray(2)
            heading.getLocationOnScreen(titlePosition); scroll.getLocationOnScreen(viewportPosition)
            scroll.scrollTo(0, scroll.scrollY + titlePosition[1] - viewportPosition[1])
        }
        waitFor {
            views().filterIsInstance<PhotoLetterDeck>().any { letter ->
                views(letter).filterIsInstance<android.widget.ImageView>().any {
                    it.drawable is android.graphics.drawable.BitmapDrawable
                }
            }
        }
        val frames = CountDownLatch(1)
        test.runOnMainSync { activity.window.decorView.postOnAnimation {
            activity.window.decorView.postOnAnimation { frames.countDown() }
        } }
        assertTrue(frames.await(3, TimeUnit.SECONDS))
        test.uiAutomation.takeScreenshot().let { bitmap ->
            File(test.targetContext.cacheDir, "memory-demo-live.png").outputStream().use {
                bitmap.compress(Bitmap.CompressFormat.PNG, 100, it)
            }
            bitmap.recycle()
        }
        test.runOnMainSync {
            views().first { it.contentDescription == "소식과 댓글 자세히 보기" }.performClick()
        }
        waitFor { views().filterIsInstance<TextView>().any { it.text.toString() == "댓글 0" } }
        test.runOnMainSync { activity.onBackPressedDispatcher.onBackPressed() }
        waitFor { views().any { it is FamilyMemoryPanel } && views().any { it is PhotoLetterDeck } }
        test.runOnMainSync {
            assertEquals("지난 가족 여행은 어디로 갔고 뭘 먹었어?",
                views().filterIsInstance<FamilyMemoryPanel>().single().input.text.toString())
        }
    }
}
