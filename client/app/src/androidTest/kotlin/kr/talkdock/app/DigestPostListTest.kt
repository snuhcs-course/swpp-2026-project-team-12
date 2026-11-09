package kr.talkdock.app

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Rect
import android.os.SystemClock
import android.view.MotionEvent
import android.view.View
import android.widget.HorizontalScrollView
import android.widget.ImageView
import android.widget.TextView
import androidx.test.ext.junit.runners.AndroidJUnit4
import kr.talkdock.app.ui.PhotoCarousel
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.ByteArrayOutputStream

/** Every digest source stays reachable through the portrait cover slider in both text sizes. */
@RunWith(AndroidJUnit4::class)
class DigestPostListTest {
    private val names = listOf("정아", "아빠", "엄마", "준하", "경자", "가족")
    private var fixtureOrigin = ""
    private fun post(id: Int) = JSONObject().put("id", id).put("author_id", id)
        .put("author_name", names[id - 1]).put("relationship", "가족")
        .put("caption", "가족이 남긴 $id 번째 소식입니다. " + "오래 기억하고 싶은 하루예요. ".repeat(id))
        .put("created_at", "2026-10-30T09:00:00+09:00").put("comment_count", 0)
        .put("comments", JSONArray()).put("images", JSONArray().apply {
            if (id < 6) put(JSONObject().put("url", "$fixtureOrigin/api/photos/$id.png"))
        })
    private fun server(): MockApi {
        val context = androidx.test.platform.app.InstrumentationRegistry.getInstrumentation().targetContext
        val family = BitmapFactory.decodeResource(context.resources, R.drawable.family)
        val photos = (1..5).associateWith { id ->
            val width = family.width / 3
            val crop = Bitmap.createBitmap(family, (id - 1) % 3 * width, 0, width, family.height)
            ByteArrayOutputStream().use { output ->
                crop.compress(Bitmap.CompressFormat.PNG, 100, output); crop.recycle(); output.toByteArray()
            }
        }
        family.recycle()
        val api = MockApi { request -> when {
            request.path == "/api/families/current/" -> jsonReply(room(77, "우리 가족"))
            request.path == "/api/posts/" -> emptyFeed()
            request.path.startsWith("/api/digests/?") -> jsonReply(JSONObject().put("status", "ready")
                .put("text", "[딸 - 정아] 가족과 함께 산책하며 즐거운 하루를 보냈어요.\n\n[아들 - 준하] 맛있는 저녁을 준비하고, 서로의 안부를 나눴어요.")
                .put("posts", JSONArray((1..6).map { post(it) })))
            request.path.matches(Regex("/api/posts/[1-6]/")) -> jsonReply(post(request.path.split('/')[3].toInt()))
            request.path.matches(Regex("/api/photos/[1-5]\\.png")) -> Reply(photos.getValue(request.path.substringAfterLast('/').substringBefore('.').toInt()), type = "image/png")
            else -> jsonReply(JSONObject())
        } }
        fixtureOrigin = api.base.removeSuffix("/api/")
        return api
    }
    private fun slider(ui: UiHarness) = ui.all().single { it.tag == "digest-post-strip" } as HorizontalScrollView
    private fun swipeLeft(ui: UiHarness, view: View) {
        val bounds = Rect()
        ui.test.runOnMainSync { assertTrue(view.getGlobalVisibleRect(bounds)) }
        val down = SystemClock.uptimeMillis()
        for (step in 0..12) {
            val action = when (step) { 0 -> MotionEvent.ACTION_DOWN; 12 -> MotionEvent.ACTION_UP; else -> MotionEvent.ACTION_MOVE }
            val event = MotionEvent.obtain(down, SystemClock.uptimeMillis(), action,
                bounds.left + bounds.width() * (.85f - step / 12f * .7f), bounds.exactCenterY(), 0)
            ui.test.uiAutomation.injectInputEvent(event, true); event.recycle(); Thread.sleep(20)
        }
    }
    @Test fun everyJournalSourceOpensFromTheSliderWithoutExtraButtons() {
        for (large in listOf(false, true)) server().use { api -> UiHarness(api, room(77, "우리 가족"), large).use { ui ->
            ui.await { ui.has("첫 소식을 기다리고 있어요") }; ui.openDaily()
            ui.await { ui.has("이날의 소식 6개") }
            ui.await { ui.all(slider(ui)).filterIsInstance<ImageView>().take(3).all { it.drawable != null } }
            ui.test.runOnMainSync {
                val strip = slider(ui)
                assertTrue(ui.has("오늘도, 함께")); assertTrue(ui.all().none { it is PhotoCarousel })
                assertTrue(strip.canScrollHorizontally(1))
                assertEquals(((if (large) 190 else 170) * ui.activity.resources.displayMetrics.density).toInt(), strip.height)
                ui.all(strip).filterIsInstance<ImageView>().forEach { assertEquals(ImageView.ScaleType.CENTER_CROP, it.scaleType) }
                assertTrue(ui.all().filterIsInstance<TextView>().none { it.text.toString().endsWith("의 소식 보기") })
            }
            ui.screenshot(if (large) "digest-slider-large-start.png" else "digest-slider-start.png")
            swipeLeft(ui, slider(ui))
            ui.await { slider(ui).scrollX > 0 }
            ui.test.runOnMainSync { slider(ui).fullScroll(View.FOCUS_RIGHT) }
            ui.await { !slider(ui).canScrollHorizontally(1) && ui.all(slider(ui)).filterIsInstance<ImageView>().takeLast(2).all { it.drawable != null } }
            ui.screenshot(if (large) "digest-slider-large-end.png" else "digest-slider-end.png")
            for (id in listOf(6, 3, 1, 4, 2, 5)) {
                val label = names[id - 1] + "의 소식 보기"
                ui.test.runOnMainSync {
                    val tile = ui.all(slider(ui)).first { it.contentDescription == label }
                    tile.requestRectangleOnScreen(Rect(0, 0, tile.width, tile.height), true)
                }
                ui.test.runOnMainSync { ui.all(slider(ui)).first { it.contentDescription == label }.performClick() }
                ui.await { ui.hasPostDetail() }
                val request = synchronized(api.requests) { api.requests.last { it.path.matches(Regex("/api/posts/[1-6]/")) } }
                assertEquals("/api/posts/$id/", request.path); assertEquals("77", request.room)
                ui.test.runOnMainSync { assertTrue(ui.has(post(id).getString("caption"))) }
                ui.openDaily(); ui.await { ui.has("이날의 소식 6개") }
            }
            assertTrue("Text-only covers have no image request", api.paths().none { it == "/api/photos/6.png" })
        } }
    }
}
