@file:Suppress("DEPRECATION")

package kr.talkdock.app

import android.graphics.Bitmap
import android.graphics.Canvas
import android.view.View
import android.widget.ProgressBar
import android.widget.TextView
import android.view.ViewGroup
import android.animation.ValueAnimator
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import kr.talkdock.app.ui.TodakArtView
import kr.talkdock.app.ui.TodakJoyView
import kr.talkdock.app.ui.TodakWaitingView
import kr.talkdock.app.ui.TodakSuccessView
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

/** Checks local posting feedback without sending anything to a deployed server. */
@RunWith(AndroidJUnit4::class)
class PostingFeedbackTest {
    @Test fun successShowsJoyAndMessageWithoutWaitingSpinnerOrOverlappingText() {
        val test = InstrumentationRegistry.getInstrumentation()
        test.runOnMainSync {
            val context = test.targetContext
            val ordinary = TodakWaitingView(context, "불러오고 있어요.")
            val success = TodakSuccessView(context, "글 업로드가 완료됐어요") {}
            assertTrue(ordinary.getChildAt(0) is TodakArtView)
            val width = (360 * context.resources.displayMetrics.density).toInt()
            val height = (640 * context.resources.displayMetrics.density).toInt()
            success.measure(View.MeasureSpec.makeMeasureSpec(width, View.MeasureSpec.EXACTLY),
                View.MeasureSpec.makeMeasureSpec(height, View.MeasureSpec.EXACTLY))
            success.layout(0, 0, width, height)
            val children = (0 until success.childCount).map { success.getChildAt(it) }
            val character = children.filterIsInstance<TodakJoyView>().single()
            val message = children.filterIsInstance<TextView>().single()
            assertEquals("글 업로드가 완료됐어요", message.text.toString())
            assertTrue(children.none { it is ProgressBar })
            assertTrue("The success text must sit below the character", character.bottom < message.top)
            assertTrue("The success message must fit on screen", message.bottom <= height)
            val preview = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
            try {
                success.draw(Canvas(preview))
                java.io.File(context.cacheDir, "posting-success-preview.png").outputStream().use {
                    preview.compress(Bitmap.CompressFormat.PNG, 100, it)
                }
            } finally { preview.recycle() }
        }
    }

    @Test fun boySuccessMovesAndStopsWhenRemoved() {
        org.junit.Assume.assumeTrue(ValueAnimator.areAnimatorsEnabled())
        MockApi { request -> if (request.path == "/api/families/current/")
            jsonReply(room(1, "완료 화면 테스트")) else emptyFeed()
        }.use { api -> UiHarness(api, room(1, "완료 화면 테스트")).use { ui ->
            ui.await { ui.has("첫 소식을 기다리고 있어요") }
            lateinit var host: ViewGroup
            fun frame(): Bitmap {
                val image = Bitmap.createBitmap(host.width, host.height, Bitmap.Config.ARGB_8888)
                host.draw(Canvas(image))
                return image
            }
            fun moving(boy: TodakJoyView) = kotlin.math.abs(boy.translationY) > .5f || kotlin.math.abs(boy.rotation) > .1f
            // A clearly lifted or tilted pose (the animation peaks at 10 dp and 3 degrees), so the frame differs visibly.
            val lift = 2f * ui.activity.resources.displayMetrics.density
            fun posed(boy: TodakJoyView) = kotlin.math.abs(boy.translationY) > lift || kotlin.math.abs(boy.rotation) > 1f
            // The celebration is one 1.8 s animation that starts and ends at rest. A slow software-rendered
            // emulator can finish it before a fixed sleep wakes up, so poll its state on the main thread and
            // draw the frame in the same main-thread turn the state was read in.
            fun <T : Any> awaitOnMain(timeoutMs: Long, read: () -> T?): T? {
                val deadline = System.currentTimeMillis() + timeoutMs
                while (System.currentTimeMillis() < deadline) {
                    var value: T? = null
                    ui.test.runOnMainSync { value = read() }
                    value?.let { return it }
                    Thread.sleep(16)
                }
                return null
            }
            fun show(): Pair<TodakSuccessView, TodakJoyView> {
                lateinit var shown: Pair<TodakSuccessView, TodakJoyView>
                ui.test.runOnMainSync {
                    host = ui.activity.findViewById(android.R.id.content)
                    val success = TodakSuccessView(ui.activity, "댓글을 달았어요!") {}
                    host.addView(success, ViewGroup.LayoutParams(-1, -1))
                    shown = success to (0 until success.childCount).map { success.getChildAt(it) }
                        .filterIsInstance<TodakJoyView>().single()
                }
                return shown
            }

            val (success, boy) = show()
            var celebrating: Bitmap? = null
            var resting: Bitmap? = null
            try {
                // The animation cannot end before its first frame, so a long wait here only absorbs a slow start.
                celebrating = awaitOnMain(5000) { if (posed(boy)) frame() else null }
                assertNotNull("The new boy must start moving on success", celebrating)
                ui.screenshot("boy-posting-success.png")
                resting = awaitOnMain(5000) { if (!moving(boy)) frame() else null }
                assertNotNull("The success motion must settle back to rest", resting)
                assertFalse("The new boy must visibly move on success", resting!!.sameAs(celebrating))
            } finally {
                celebrating?.recycle(); resting?.recycle()
                ui.test.runOnMainSync { host.removeView(success) }
            }

            // Removing the view mid-celebration must stop the motion and reset the pose.
            val (again, nextBoy) = show()
            try {
                assertNotNull("The new boy must move again when shown again",
                    awaitOnMain(5000) { if (posed(nextBoy)) true else null })
                ui.test.runOnMainSync {
                    host.removeView(again)
                    assertFalse(nextBoy.isAttachedToWindow)
                    assertEquals(0f, nextBoy.translationY, .001f)
                    assertEquals(0f, nextBoy.rotation, .001f)
                }
            } finally {
                ui.test.runOnMainSync { host.removeView(again) }
            }
        } }
    }
}
