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
            lateinit var success: TodakSuccessView
            lateinit var boy: TodakJoyView
            fun frame(): Bitmap {
                lateinit var image: Bitmap
                ui.test.runOnMainSync {
                    image = Bitmap.createBitmap(host.width, host.height, Bitmap.Config.ARGB_8888)
                    host.draw(Canvas(image))
                }
                return image
            }
            ui.test.runOnMainSync {
                host = ui.activity.findViewById(android.R.id.content)
                success = TodakSuccessView(ui.activity, "댓글을 달았어요!") {}
                host.addView(success, ViewGroup.LayoutParams(-1, -1))
                boy = (0 until success.childCount).map { success.getChildAt(it) }.filterIsInstance<TodakJoyView>().single()
            }
            ui.test.waitForIdleSync()
            val resting = frame()
            Thread.sleep(500)
            val celebrating = frame()
            try {
                assertFalse("The new boy must visibly move on success", resting.sameAs(celebrating))
                ui.screenshot("boy-posting-success.png")
                ui.test.runOnMainSync {
                    assertTrue(kotlin.math.abs(boy.translationY) > .1f || kotlin.math.abs(boy.rotation) > .1f)
                    host.removeView(success)
                    assertFalse(boy.isAttachedToWindow)
                    assertEquals(0f, boy.translationY, .001f)
                    assertEquals(0f, boy.rotation, .001f)
                }
            } finally {
                resting.recycle(); celebrating.recycle()
                ui.test.runOnMainSync { host.removeView(success) }
            }
        } }
    }
}
