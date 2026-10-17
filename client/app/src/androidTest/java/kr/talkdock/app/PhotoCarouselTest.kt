package kr.talkdock.app

import android.graphics.Bitmap
import android.graphics.RectF
import android.view.View
import android.widget.HorizontalScrollView
import android.widget.ImageView
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import kr.talkdock.app.ui.PhotoCarousel
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class PhotoCarouselTest {
    private fun layout(carousel: PhotoCarousel) {
        carousel.measure(View.MeasureSpec.makeMeasureSpec(360, View.MeasureSpec.EXACTLY),
            View.MeasureSpec.makeMeasureSpec(0, View.MeasureSpec.UNSPECIFIED))
        carousel.layout(0, 0, 360, carousel.measuredHeight)
    }

    private fun assertFillsWithoutCropping(image: ImageView, expectedHeight: Int) {
        val displayed = RectF(image.drawable.bounds)
        image.imageMatrix.mapRect(displayed)
        assertEquals(0f, displayed.left, 1f)
        assertEquals(0f, displayed.top, 1f)
        assertEquals(360f, displayed.right, 1f)
        assertEquals(expectedHeight.toFloat(), displayed.bottom, 1f)
    }

    @Test fun portraitLandscapeAndSquareFillTheirOriginalAspectRatio() {
        val test = InstrumentationRegistry.getInstrumentation()
        test.runOnMainSync {
            for ((width, height) in listOf(200 to 300, 300 to 200, 200 to 200)) {
                val bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
                lateinit var image: ImageView
                val carousel = PhotoCarousel(test.targetContext, 1, false,
                    load = { view, _ -> image = view; view.setImageBitmap(bitmap) })
                layout(carousel)
                val expectedHeight = 360 * height / width
                assertEquals(expectedHeight, carousel.getChildAt(0).height)
                assertFillsWithoutCropping(image, expectedHeight)
                bitmap.recycle()
            }
        }
    }

    @Test fun downloadedPhotoReplacesSquarePlaceholderWithItsOwnRatio() {
        val test = InstrumentationRegistry.getInstrumentation()
        test.runOnMainSync {
            lateinit var image: ImageView
            val carousel = PhotoCarousel(test.targetContext, 1, false, load = { view, _ -> image = view })
            layout(carousel)
            val bitmap = Bitmap.createBitmap(200, 300, Bitmap.Config.ARGB_8888)
            image.setImageBitmap(bitmap)
            assertTrue(carousel.getChildAt(0).isLayoutRequested)
            layout(carousel)
            assertEquals(540, carousel.getChildAt(0).height)
            assertFillsWithoutCropping(image, 540)
            bitmap.recycle()
        }
    }

    @Test fun pagingBetweenDifferentRatiosResizesThePhotoArea() {
        val test = InstrumentationRegistry.getInstrumentation()
        test.runOnMainSync {
            val photos = listOf(Bitmap.createBitmap(200, 300, Bitmap.Config.ARGB_8888),
                Bitmap.createBitmap(300, 200, Bitmap.Config.ARGB_8888))
            val views = mutableListOf<ImageView>()
            val carousel = PhotoCarousel(test.targetContext, 2, false,
                load = { view, index -> view.setImageBitmap(photos[index]); views.add(view) })
            layout(carousel)
            val pager = carousel.getChildAt(0) as HorizontalScrollView
            assertEquals(540, pager.height)
            pager.scrollTo(360, 0)
            layout(carousel)
            assertEquals(1, carousel.currentIndex)
            assertEquals(240, pager.height)
            assertEquals(360, pager.scrollX)
            assertFillsWithoutCropping(views[1], 240)
            photos.forEach { it.recycle() }
        }
    }
}
