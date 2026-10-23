@file:Suppress("DEPRECATION")

package kr.talkdock.app

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Movie
import android.view.View
import android.widget.ProgressBar
import android.widget.TextView
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import kr.talkdock.app.ui.TodakArtView
import kr.talkdock.app.ui.TodakJoyView
import kr.talkdock.app.ui.TodakWaitingView
import kr.talkdock.app.ui.TodakSuccessView
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

/** Checks the supplied GIF on Android's decoder without sending anything to the server. */
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

    @Test fun suppliedJoyPreviewRendersDifferentPosesOnAndroid() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val movie = context.assets.open("todak/todak_joy.gif").use { Movie.decodeStream(it) }
        assertNotNull(movie)
        assertTrue(movie.duration() >= 2500)
        fun frame(time: Int): Bitmap {
            val bitmap = Bitmap.createBitmap(movie.width(), movie.height(), Bitmap.Config.ARGB_8888)
            movie.setTime(time)
            movie.draw(Canvas(bitmap), 0f, 0f)
            return bitmap
        }
        val resting = frame(0)
        val jumping = frame(600)
        try {
            assertFalse("The preview must animate rather than remain a still image", resting.sameAs(jumping))
        } finally {
            resting.recycle(); jumping.recycle()
        }
    }
}
