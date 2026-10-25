package kr.talkdock.app

import android.Manifest
import android.content.ContentValues
import android.graphics.Bitmap
import android.graphics.Color
import android.graphics.Rect
import android.graphics.drawable.BitmapDrawable
import android.net.Uri
import android.os.Build
import android.provider.MediaStore
import android.view.View
import android.view.ViewGroup
import android.view.inspector.WindowInspector
import android.widget.Button
import android.widget.EditText
import android.widget.GridView
import android.widget.ImageView
import android.widget.TextView
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.filters.SdkSuppress
import kr.talkdock.app.data.ApiException
import kr.talkdock.app.ui.PhotoCarousel
import kr.talkdock.app.ui.PhotoPickerActivity
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.ByteArrayOutputStream
import java.io.File
import java.lang.reflect.InvocationTargetException

/** Writing a post: text, attached photos, the gallery picker, and the full-screen photo viewer. */
@RunWith(AndroidJUnit4::class)
@SdkSuppress(minSdkVersion = 29)  // WindowInspector and MediaStore.VOLUME_EXTERNAL_PRIMARY
class PostComposerTest {
    private val uploaded = JSONObject().put("id", 1).put("caption", "").put("images", JSONArray())

    private fun feedApi() = MockApi { request -> when {
        request.path == "/api/families/current/" -> jsonReply(room(1, "글쓰기 가족"))
        request.method == "POST" && request.path == "/api/posts/" -> jsonReply(uploaded)
        else -> emptyFeed()
    } }
    private fun MockApi.uploads() = synchronized(requests) { requests.filter { it.method == "POST" && it.path == "/api/posts/" } }

    private fun UiHarness.clickDescription(description: String) = test.runOnMainSync {
        val target = all().firstOrNull { it.contentDescription?.toString() == description }
            ?: fail("\"$description\" not found among ${all().mapNotNull { it.contentDescription?.toString() }}")
        assertTrue(description, (target as View).performClick())
    }
    private fun UiHarness.openComposer() {
        await { has("첫 소식을 기다리고 있어요") }
        clickDescription("가족 소식 작성하기"); await { has("가족에게 전하기") }
    }
    private fun UiHarness.back() = test.runOnMainSync { activity.onBackPressedDispatcher.onBackPressed() }

    // Dialogs live in their own windows; WindowInspector lists every window of this process. Call on the main thread.
    private fun windowViews(): List<View> {
        fun walk(view: View): List<View> = listOf(view) +
            if (view is ViewGroup) (0 until view.childCount).flatMap { walk(view.getChildAt(it)) } else emptyList()
        return WindowInspector.getGlobalWindowViews().filter { it.isShown }.flatMap { walk(it) }
    }
    private fun windowText(text: String) = windowViews().filterIsInstance<TextView>().firstOrNull { it.text.toString() == text }
    private fun UiHarness.awaitText(text: String) = await { windowText(text) != null }
    private fun UiHarness.tapText(text: String) {
        awaitText(text)
        test.runOnMainSync { assertTrue(text, windowText(text)!!.performClick()) }
    }

    private fun jpeg(color: Int, width: Int = 120, height: Int = 80): ByteArray {
        val bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888).apply { eraseColor(color) }
        return ByteArrayOutputStream().also { bitmap.compress(Bitmap.CompressFormat.JPEG, 90, it); bitmap.recycle() }.toByteArray()
    }
    private fun UiHarness.draftFile(name: String, bytes: ByteArray) =
        File(File(activity.filesDir, "camera").apply { mkdirs() }, name).apply { writeBytes(bytes) }

    /** Puts files in the composer draft as if they had been picked, then opens the composer. */
    private fun UiHarness.attach(files: List<File>) = test.runOnMainSync {
        MainActivity::class.java.getDeclaredField("photo").apply { isAccessible = true }.set(activity, files.firstOrNull())
        @Suppress("UNCHECKED_CAST")
        val extra = MainActivity::class.java.getDeclaredField("extraPhotos").apply { isAccessible = true }.get(activity) as MutableList<File>
        extra.clear(); extra.addAll(files.drop(1))
        MainActivity::class.java.getDeclaredMethod("composer").apply { isAccessible = true }.invoke(activity)
    }

    @Test fun textOnlyPostIsUploadedToTheCurrentRoomAndEmptyPostsAreBlocked() {
        feedApi().use { api -> UiHarness(api, room(1, "글쓰기 가족")).use { ui ->
            ui.openComposer()
            ui.test.runOnMainSync { assertTrue(ui.has("사진 0 / 5장 · 한 장당 10MB · 전체 30MB")); assertTrue(ui.has("사진 추가")) }
            ui.click("가족에게 전하기")
            assertTrue("An empty post must not be sent", api.uploads().isEmpty())
            ui.test.runOnMainSync { ui.all().filterIsInstance<EditText>().single().setText("  오늘은 공원을 산책했어요  ") }
            ui.click("가족에게 전하기"); ui.await(12000) { ui.has("첫 소식을 기다리고 있어요") }
            val upload = api.uploads().single()
            assertEquals("1", upload.room)
            assertTrue("The caption is trimmed", upload.body.contains("\r\n\r\n오늘은 공원을 산책했어요\r\n"))
        } }
    }

    @Test fun leavingAWrittenDraftAsksBeforeDiscarding() {
        feedApi().use { api -> UiHarness(api, room(1, "글쓰기 가족")).use { ui ->
            ui.openComposer()
            ui.back(); ui.await { ui.has("첫 소식을 기다리고 있어요") }  // an empty draft leaves at once
            ui.clickDescription("가족 소식 작성하기"); ui.await { ui.has("가족에게 전하기") }
            ui.test.runOnMainSync { ui.all().filterIsInstance<EditText>().single().setText("아직 쓰는 중") }
            ui.back(); ui.awaitText("소식 작성을 그만할까요?"); ui.tapText("계속 쓰기")
            ui.test.runOnMainSync { assertEquals("아직 쓰는 중", ui.all().filterIsInstance<EditText>().single().text.toString()) }
            ui.back(); ui.tapText("그만하기"); ui.await { ui.has("첫 소식을 기다리고 있어요") }
            ui.clickDescription("가족 소식 작성하기"); ui.await { ui.has("가족에게 전하기") }
            ui.test.runOnMainSync { assertEquals("", ui.all().filterIsInstance<EditText>().single().text.toString()) }
            assertTrue(api.uploads().isEmpty())
        } }
    }

    @Test fun attachedPhotosShowUprightPreviewsCanBeRemovedAndAreUploaded() {
        feedApi().use { api -> UiHarness(api, room(1, "글쓰기 가족")).use { ui ->
            ui.await { ui.has("첫 소식을 기다리고 있어요") }
            val first = ui.draftFile("draft-red.jpg", jpeg(Color.RED))
            val rotated = ui.draftFile("draft-blue.jpg", jpeg(Color.BLUE)).also {
                android.media.ExifInterface(it.absolutePath).apply {
                    setAttribute(android.media.ExifInterface.TAG_ORIENTATION, "6"); saveAttributes()
                }
            }
            ui.attach(listOf(first, rotated)); ui.await { ui.has("사진 2 / 5장 · 한 장당 10MB · 전체 30MB") }
            ui.test.runOnMainSync {
                assertTrue(ui.has("다시 선택"))
                val preview = ui.all().first { it.contentDescription?.toString() == "첨부 사진 2" } as ImageView
                val bitmap = (preview.drawable as BitmapDrawable).bitmap
                assertTrue("EXIF orientation 6 must be shown upright", bitmap.height > bitmap.width)
            }
            ui.clickDescription("1번째 사진 빼기"); ui.await { ui.has("사진 1 / 5장 · 한 장당 10MB · 전체 30MB") }
            assertFalse("A removed photo is deleted from the draft folder", first.exists())
            ui.click("가족에게 전하기"); ui.await(12000) { ui.has("첫 소식을 기다리고 있어요") }
            val body = api.uploads().single().body
            assertEquals(1, Regex("filename=\"photo-\\d+\\.jpg\"").findAll(body).count())
            assertFalse("Uploaded drafts are cleaned up", rotated.exists())
        } }
    }

    @Test fun largeTextStripRemovesPhotosAndUnreadablePhotosBlockSending() {
        feedApi().use { api -> UiHarness(api, room(1, "글쓰기 가족"), large = true).use { ui ->
            ui.await { ui.has("첫 소식을 기다리고 있어요") }
            val good = ui.draftFile("draft-good.jpg", jpeg(Color.GREEN))
            val broken = ui.draftFile("draft-broken.jpg", "not-an-image".toByteArray())
            ui.attach(listOf(good, broken)); ui.await { ui.has("읽을 수 없는 사진이 있어요. 빼거나 다시 선택해 주세요.") }
            ui.click("가족에게 전하기")
            assertTrue("An unreadable photo must block sending", api.uploads().isEmpty())
            ui.test.runOnMainSync {
                val removes = ui.all().filterIsInstance<Button>().filter { it.text.toString() == "이 사진 빼기" }
                assertEquals(2, removes.size)
                removes[1].performClick()
            }
            ui.await { ui.has("사진 1 / 5장 · 한 장당 10MB · 전체 30MB") && !ui.has("읽을 수 없는 사진이 있어요. 빼거나 다시 선택해 주세요.") }
            assertTrue(good.exists()); assertFalse(broken.exists())
        } }
    }

    @Test fun copyingGalleryPhotosRejectsOversizedAndUnreadableFiles() {
        feedApi().use { api -> UiHarness(api, room(1, "글쓰기 가족")).use { ui ->
            ui.await { ui.has("첫 소식을 기다리고 있어요") }
            val copy = MainActivity::class.java.getDeclaredMethod("copyGalleryPhotos", List::class.java).apply { isAccessible = true }
            fun copyError(bytes: ByteArray): String {
                val source = File(ui.activity.cacheDir, "gallery-source.jpg").apply { writeBytes(bytes) }
                return try { copy.invoke(ui.activity, listOf(Uri.fromFile(source))); "" }
                catch (error: InvocationTargetException) { (error.cause as ApiException).message.orEmpty() }
                finally { source.delete() }
            }
            val camera = File(ui.activity.filesDir, "camera")
            camera.listFiles()?.forEach { it.delete() }
            assertTrue(copyError(ByteArray(10 * 1024 * 1024 + 1)).contains("10MB"))
            assertEquals("읽을 수 없거나 너무 큰 사진이에요. 다른 사진을 선택해 주세요.", copyError("not-an-image".toByteArray()))
            assertTrue("Failed copies leave no files behind", camera.listFiles().isNullOrEmpty())
            val source = File(ui.activity.cacheDir, "gallery-ok.jpg").apply { writeBytes(jpeg(Color.YELLOW)) }
            @Suppress("UNCHECKED_CAST")
            val copied = copy.invoke(ui.activity, listOf(Uri.fromFile(source))) as List<File>
            assertArrayEquals(source.readBytes(), copied.single().readBytes())
            copied.forEach { it.delete() }; source.delete()
        } }
    }

    @Test fun galleryPickerReturnsUpToFivePhotosInTapOrder() {
        val test = androidx.test.platform.app.InstrumentationRegistry.getInstrumentation()
        val resolver = test.targetContext.contentResolver
        test.uiAutomation.grantRuntimePermission(test.targetContext.packageName,
            if (Build.VERSION.SDK_INT >= 33) Manifest.permission.READ_MEDIA_IMAGES else Manifest.permission.READ_EXTERNAL_STORAGE)
        val collection = MediaStore.Images.Media.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)
        val inserted = (0 until 6).map { index ->
            val values = ContentValues().apply {
                put(MediaStore.Images.Media.DISPLAY_NAME, "talkdock-picker-$index.jpg")
                put(MediaStore.Images.Media.MIME_TYPE, "image/jpeg")
                put(MediaStore.Images.Media.RELATIVE_PATH, "Pictures/TalkDockTest")
            }
            resolver.insert(collection, values)!!.also { uri ->
                resolver.openOutputStream(uri)!!.use { it.write(jpeg(Color.rgb(index * 40, 100, 200 - index * 30))) }
            }
        }
        try {
            feedApi().use { api -> UiHarness(api, room(1, "글쓰기 가족")).use { ui ->
                ui.openComposer()
                val monitor = test.addMonitor(PhotoPickerActivity::class.java.name, null, false)
                ui.clickDescription("사진 추가하기")
                val picker = test.waitForMonitorWithTimeout(monitor, 10000) as PhotoPickerActivity
                test.removeMonitor(monitor)
                fun views(view: View = picker.window.decorView): List<View> = listOf(view) +
                    if (view is ViewGroup) (0 until view.childCount).flatMap { views(view.getChildAt(it)) } else emptyList()
                fun pickerText(text: String) = views().filterIsInstance<TextView>().any { it.text.toString() == text }
                lateinit var grid: GridView
                ui.await(10000) {
                    grid = views().filterIsInstance<GridView>().single()
                    grid.adapter.count >= 6 && pickerText("다음")
                }
                fun uriAt(position: Int) = grid.adapter.getItem(position).let { item ->
                    item.javaClass.getDeclaredField("uri").apply { isAccessible = true }.get(item) as String
                }
                fun tap(position: Int) = test.runOnMainSync { grid.performItemClick(grid, position, grid.adapter.getItemId(position)) }
                test.runOnMainSync { views().filterIsInstance<Button>().first { it.text.toString() == "선택" }.performClick() }
                ui.await { pickerText("1 / 5") && pickerText("취소") }
                (1..4).forEach { tap(it) }
                ui.await { pickerText("5 / 5") && pickerText("다음 (5)") }
                tap(5)
                ui.await { pickerText("5 / 5") }  // a sixth photo is rejected
                tap(2)
                ui.await { pickerText("4 / 5") }
                val expected = listOf(0, 1, 3, 4).map { uriAt(it) }
                test.runOnMainSync { views().filterIsInstance<Button>().first { it.text.toString() == "다음 (4)" }.performClick() }
                ui.await(10000) { ui.has("사진 4 / 5장 · 한 장당 10MB · 전체 30MB") }
                @Suppress("UNCHECKED_CAST")
                val drafts = listOf(MainActivity::class.java.getDeclaredField("photo").apply { isAccessible = true }.get(ui.activity) as File) +
                    (MainActivity::class.java.getDeclaredField("extraPhotos").apply { isAccessible = true }.get(ui.activity) as List<File>)
                assertEquals("Photos keep the tap order", expected.map { uri -> resolver.openInputStream(Uri.parse(uri))!!.use { it.readBytes() }.toList() },
                    drafts.map { it.readBytes().toList() })
            } }
        } finally {
            inserted.forEach { resolver.delete(it, null, null) }
        }
    }

    @Test fun fullScreenViewerPagesThroughPhotosAndCloses() {
        val photos = listOf(Color.RED, Color.GREEN, Color.BLUE).map { jpeg(it, 400, 300) }
        lateinit var api: MockApi
        api = MockApi { request -> when {
            request.path == "/api/families/current/" -> jsonReply(room(1, "사진 보기 가족"))
            request.path.startsWith("/api/photo/") -> Reply(photos[request.path.trimEnd('/').substringAfterLast('/').toInt()], type = "image/jpeg")
            else -> jsonReply(JSONObject().put("posts", JSONArray().put(JSONObject().put("id", 1)
                .put("author_name", "사진 가족").put("relationship", "나").put("caption", "사진 세 장")
                .put("created_at", "2026-10-19T09:00:00+09:00").put("comment_count", 0)
                .put("images", JSONArray().apply { repeat(3) { put(JSONObject().put("url", api.base + "photo/$it/")) } }))))
        } }
        api.use { server -> UiHarness(server, room(1, "사진 보기 가족")).use { ui ->
            ui.await { ui.has("사진 세 장") && ui.all().any { it is PhotoCarousel } }
            ui.test.runOnMainSync {
                val carousel = ui.all().filterIsInstance<PhotoCarousel>().single()
                carousel.requestRectangleOnScreen(Rect(0, 0, carousel.width, carousel.height), true)
            }
            // Open whichever photo the carousel shows; the viewer starts on that photo.
            var opened = 0
            ui.test.runOnMainSync {
                val photo = ui.all().first { it.contentDescription?.toString()?.endsWith(", 누르면 크게 보기") == true }
                opened = Regex("사진 (\\d) / 3").find(photo.contentDescription.toString())!!.groupValues[1].toInt()
                assertTrue(photo.performClick())
            }
            ui.awaitText("사진 $opened / 3")
            while (opened > 1) { ui.tapText("이전 사진"); opened--; ui.awaitText("사진 $opened / 3") }
            ui.test.runOnMainSync { assertFalse("The first photo has no previous photo", windowText("이전 사진")!!.isEnabled) }
            ui.tapText("다음 사진"); ui.awaitText("사진 2 / 3")
            ui.tapText("다음 사진"); ui.awaitText("사진 3 / 3")
            ui.test.runOnMainSync { assertFalse("The last photo has no next photo", windowText("다음 사진")!!.isEnabled) }
            ui.tapText("이전 사진"); ui.awaitText("사진 2 / 3")
            ui.tapText("닫기")
            ui.await { windowText("사진 2 / 3") == null }
        } }
    }
}
