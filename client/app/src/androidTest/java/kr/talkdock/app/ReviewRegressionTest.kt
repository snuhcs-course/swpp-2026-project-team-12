package kr.talkdock.app

import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.os.Debug
import android.os.SystemClock
import android.view.View
import android.view.ViewGroup
import android.widget.EditText
import android.widget.Button
import android.widget.ImageView
import android.widget.TextView
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.ByteArrayOutputStream
import java.net.ServerSocket
import java.net.SocketException
import java.util.Collections

private data class Request(val method: String, val path: String, val body: String)
private data class Reply(val body: ByteArray, val status: Int = 200, val type: String = "application/json")
private fun jsonReply(value: JSONObject, status: Int = 200) = Reply(value.toString().toByteArray(), status)

private class MockApi(private val respond: (Request) -> Reply) : AutoCloseable {
    private val socket = ServerSocket(0)
    val base = "http://127.0.0.1:${socket.localPort}/api/"
    val requests = Collections.synchronizedList(mutableListOf<Request>())
    private val worker = Thread {
        while (!socket.isClosed) {
            try {
                socket.accept().use { client ->
                    client.soTimeout = 10000
                    val input = client.getInputStream().buffered()
                    val header = ByteArrayOutputStream()
                    while (header.size() < 65536) {
                        val next = input.read()
                        if (next < 0) return@use
                        header.write(next)
                        val bytes = header.toByteArray()
                        if (bytes.size >= 4 && bytes.takeLast(4) == listOf(13.toByte(),10.toByte(),13.toByte(),10.toByte())) break
                    }
                    val lines = header.toString("UTF-8").split("\r\n")
                    val first = lines.first().split(" ")
                    val size = lines.firstOrNull { it.startsWith("Content-Length:", true) }?.substringAfter(":")?.trim()?.toInt() ?: 0
                    val bytes = ByteArray(size)
                    var offset = 0
                    while (offset < size) {
                        val count = input.read(bytes, offset, size-offset)
                        if (count < 0) break
                        offset += count
                    }
                    val request = Request(first[0], first[1], String(bytes, Charsets.UTF_8))
                    requests.add(request)
                    val reply = respond(request)
                    client.getOutputStream().apply {
                        write("HTTP/1.1 ${reply.status} Test\r\nContent-Type: ${reply.type}\r\nContent-Length: ${reply.body.size}\r\nConnection: close\r\n\r\n".toByteArray())
                        write(reply.body); flush()
                    }
                }
            } catch (_: SocketException) { if (socket.isClosed) break }
        }
    }.apply { isDaemon = true; start() }
    fun paths(): List<String> = synchronized(requests) { requests.map { it.path } }
    override fun close() { socket.close(); worker.join(1000) }
}

private class UiHarness(private val api: MockApi, room: JSONObject?) : AutoCloseable {
    val test = InstrumentationRegistry.getInstrumentation()
    private val prefs = test.targetContext.getSharedPreferences("talkdock-session", Context.MODE_PRIVATE)
    private val savedPreferences = prefs.all.toMap()
    val activity: MainActivity
    init {
        val user = JSONObject().put("user_id",999).put("username","review-user").put("token","mock-review-token")
            .put("name","테스트 사용자").put("large",false)
        if (room != null) user.put("room",room)
        prefs.edit().clear().putString("current",user.toString()).putString("server",api.base).commit()
        activity=test.startActivitySync(Intent(test.targetContext,MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)) as MainActivity
    }
    fun all(view: View = activity.window.decorView): List<View> = listOf(view) +
        if(view is ViewGroup) (0 until view.childCount).flatMap { all(view.getChildAt(it)) } else emptyList()
    fun has(text: String) = all().filterIsInstance<TextView>().any { it.text.toString()==text }
    fun await(timeout: Long=6000, condition: () -> Boolean) {
        val end=SystemClock.uptimeMillis()+timeout
        while(SystemClock.uptimeMillis()<end) {
            var ready=false
            test.runOnMainSync { ready=condition() }
            if(ready) return
            Thread.sleep(40)
        }
        fail("UI condition timed out")
    }
    fun click(text: String) {
        test.runOnMainSync {
            val matches=all().filterIsInstance<TextView>().filter { it.text.toString()==text }
            var view: View=matches.firstOrNull { it is Button } ?: matches.first()
            while(!view.isClickable && view.parent is View) view=view.parent as View
            assertTrue("Clickable view for $text",view.performClick())
        }
    }
    fun screenshot(name: String) {
        val image=test.uiAutomation.takeScreenshot()
        java.io.File(test.targetContext.cacheDir,name).outputStream().use { image.compress(Bitmap.CompressFormat.PNG,100,it) }
        image.recycle()
    }
    override fun close() {
        test.runOnMainSync { activity.finish() }; test.waitForIdleSync()
        val edit = prefs.edit().clear()
        savedPreferences.forEach { (key, value) -> when(value) {
            is String -> edit.putString(key,value)
            is Boolean -> edit.putBoolean(key,value)
            is Int -> edit.putInt(key,value)
            is Long -> edit.putLong(key,value)
            is Float -> edit.putFloat(key,value)
            is Set<*> -> edit.putStringSet(key,value.filterIsInstance<String>().toSet())
        } }
        edit.commit()
    }
}

private fun room(id: Int, name: String) = JSONObject().put("id",id).put("name",name)
    .put("invite_code","REVIEW").put("owner_name","테스트 사용자").put("digest_time","21:00")
    .put("members",JSONArray().put(JSONObject().put("id",999).put("name","테스트 사용자")
        .put("is_owner",true).put("relationship","나").put("slot","owner")))
private fun emptyFeed() = jsonReply(JSONObject().put("posts",JSONArray()))

@RunWith(AndroidJUnit4::class)
class ReviewRoomUiTest {
    @Test fun existingMemberCannotSeeAdditionalRoomActions() {
        MockApi { request -> if(request.path=="/api/families/current/") jsonReply(room(1,"검증 가족 A")) else emptyFeed() }.use { api -> UiHarness(api,room(1,"검증 가족 A")).use { ui ->
            ui.await { ui.has("첫 소식을 기다리고 있어요") }
            ui.click("가족방")
            ui.await { ui.has("가족 소식 보기") }
            ui.test.runOnMainSync {
                assertFalse(ui.has("새 가족방 만들기")); assertFalse(ui.has("초대 코드로 참여하기"))
            }
            ui.screenshot("review-existing-room.png")
        } }
    }
    @Test fun accountWithoutRoomCanStillCreateOrJoin() {
        MockApi { request -> if(request.path=="/api/families/current/") jsonReply(JSONObject().put("error","가족방 없음"),403) else emptyFeed() }.use { api -> UiHarness(api,null).use { ui ->
            ui.await { ui.has("새 가족방 만들기") }
            ui.test.runOnMainSync { assertTrue(ui.has("초대 코드로 참여하기")) }
            ui.screenshot("review-no-room.png")
        } }
    }
    @Test fun loginRefreshesRoomFromServer() {
        var loggedIn = false
        MockApi { request -> when(request.path) {
            "/api/accounts/login/" -> {
                loggedIn = true
                jsonReply(JSONObject().put("user_id",999).put("username","review-user").put("name","테스트 사용자").put("token","mock-review-token"))
            }
            "/api/families/current/" -> if(loggedIn) jsonReply(room(1,"서버 가족 A")) else jsonReply(JSONObject().put("error","가족방 없음"),403)
            else -> emptyFeed()
        } }.use { api -> UiHarness(api,null).use { ui ->
            ui.await { ui.has("다른 계정으로 로그인") }; ui.click("다른 계정으로 로그인")
            ui.test.runOnMainSync {
                val fields=ui.all().filterIsInstance<EditText>()
                fields[0].setText("review-user"); fields[1].setText("Valid-Review-12345")
            }
            ui.click("로그인"); ui.await { ui.has("서버 가족 A") && ui.has("첫 소식을 기다리고 있어요") }
            assertTrue(api.paths().contains("/api/families/current/"))
            ui.screenshot("review-login-canonical-room.png")
        } }
    }
    @Test fun restartReconcilesStaleCachedRoomWithServer() {
        MockApi { request -> if(request.path=="/api/families/current/") jsonReply(room(1,"서버 가족 A")) else emptyFeed() }
            .use { api -> UiHarness(api,room(2,"기기에 저장된 가족 B")).use { ui ->
                ui.await { ui.has("첫 소식을 기다리고 있어요") }
                ui.screenshot("review-stale-room.png")
                println("REVIEW_STARTUP_REQUESTS="+api.paths())
                assertTrue("Restart must resolve families/current before trusting cached room B",api.paths().contains("/api/families/current/"))
                ui.test.runOnMainSync { assertTrue(ui.has("서버 가족 A")); assertFalse(ui.has("기기에 저장된 가족 B")) }
            } }
    }
    @Test fun createResponseIsCheckedAgainstCanonicalRoom() {
        var createdRoom = false
        MockApi { request -> when(request.path) {
            "/api/families/create/" -> { createdRoom = true; jsonReply(JSONObject().put("room",room(2,"생성 응답 가족 B")),201) }
            "/api/families/current/" -> if(createdRoom) jsonReply(room(1,"서버 가족 A")) else jsonReply(JSONObject().put("error","가족방 없음"),403)
            else -> emptyFeed()
        } }.use { api -> UiHarness(api,null).use { ui ->
            ui.await { ui.has("새 가족방 만들기") }; ui.click("새 가족방 만들기")
            ui.test.runOnMainSync {
                val fields=ui.all().filterIsInstance<EditText>()
                fields[0].setText("생성 응답 가족 B"); fields[1].setText("Review-Room-12345")
            }
            ui.click("가족 방 만들기"); ui.await { ui.has("서버 가족 A") && ui.has("첫 소식을 기다리고 있어요") }
            ui.screenshot("review-created-room-mismatch.png")
            val paths=api.paths(); println("REVIEW_CREATE_REQUESTS="+paths)
            val created=paths.indexOf("/api/families/create/")
            assertTrue("Creation must verify its returned room against families/current",paths.drop(created+1).contains("/api/families/current/"))
        } }
    }
    @Test fun matchingCreateResponseOpensTheConfirmedRoom() {
        var created = false
        MockApi { request -> when(request.path) {
            "/api/families/create/" -> { created = true; jsonReply(JSONObject().put("room",room(2,"확인된 가족 B")),201) }
            "/api/families/current/" -> if(created) jsonReply(room(2,"확인된 가족 B")) else jsonReply(JSONObject().put("error","가족방 없음"),403)
            else -> emptyFeed()
        } }.use { api -> UiHarness(api,null).use { ui ->
            ui.await { ui.has("새 가족방 만들기") }; ui.click("새 가족방 만들기")
            ui.test.runOnMainSync {
                val fields=ui.all().filterIsInstance<EditText>()
                fields[0].setText("확인된 가족 B"); fields[1].setText("Review-Room-12345")
            }
            ui.click("가족 방 만들기"); ui.await { ui.has("가족 방이 준비됐어요.") && ui.has("확인된 가족 B") }
            val paths=api.paths();val createdIndex=paths.indexOf("/api/families/create/")
            assertTrue(paths.drop(createdIndex+1).contains("/api/families/current/"))
        } }
    }
    @Test fun membershipAddedElsewherePreventsCreateRequest() {
        var joinedElsewhere = false
        MockApi { request -> when(request.path) {
            "/api/families/current/" -> if(joinedElsewhere) jsonReply(room(1,"이미 가입한 가족 A")) else jsonReply(JSONObject().put("error","가족방 없음"),403)
            else -> emptyFeed()
        } }.use { api -> UiHarness(api,null).use { ui ->
            ui.await { ui.has("새 가족방 만들기") }; ui.click("새 가족방 만들기")
            joinedElsewhere = true
            ui.test.runOnMainSync {
                val fields=ui.all().filterIsInstance<EditText>()
                fields[0].setText("새 가족 B"); fields[1].setText("Review-Room-12345")
            }
            ui.click("가족 방 만들기"); ui.await { ui.has("이미 가입한 가족 A") && ui.has("가족 소식 보기") }
            assertFalse(api.paths().contains("/api/families/create/"))
        } }
    }
    @Test fun failedStartupCheckDoesNotOpenCachedRoomOrFetchPosts() {
        MockApi { request -> if(request.path=="/api/families/current/") jsonReply(JSONObject().put("error","테스트 서버 확인 실패"),503) else emptyFeed() }
            .use { api -> UiHarness(api,room(2,"확인되지 않은 가족 B")).use { ui ->
                ui.await { api.paths().contains("/api/families/current/") }
                Thread.sleep(300)
                ui.test.runOnMainSync { assertFalse(ui.has("확인되지 않은 가족 B")); assertFalse(ui.has("첫 소식 쓰기")) }
                assertFalse(api.paths().contains("/api/posts/"))
            } }
    }
}

@RunWith(AndroidJUnit4::class)
class ReviewPhotoMemoryTest {
    @Test fun openingFeedDoesNotDownloadEveryOffscreenPhoto() {
        val bitmap=Bitmap.createBitmap(1600,1600,Bitmap.Config.ARGB_8888)
        bitmap.eraseColor(android.graphics.Color.rgb(190,220,230))
        val output=ByteArrayOutputStream(); bitmap.compress(Bitmap.CompressFormat.JPEG,90,output); bitmap.recycle()
        val jpeg=output.toByteArray()
        lateinit var api: MockApi
        api=MockApi { request ->
            if(request.path=="/api/families/current/") jsonReply(room(1,"사진 메모리 검증 가족"))
            else if(request.path.startsWith("/api/photo/")) Reply(jpeg,type="image/jpeg") else {
                val posts=JSONArray()
                for(index in 1..30) {
                    val photos=JSONArray()
                    for(photo in 1..5) photos.put(JSONObject().put("id",photo).put("url",api.base+"photo/$index/$photo/"))
                    posts.put(JSONObject().put("id",index).put("author_id",999).put("author_name","검증 사용자")
                        .put("relationship","나").put("caption","메모리 검증 소식 $index").put("created_at","2026-10-18T20:00:00+09:00")
                        .put("comment_count",0).put("image_count",5).put("images",photos).put("image_url",api.base+"photo/$index/1/"))
                }
                jsonReply(JSONObject().put("posts",posts))
            }
        }
        api.use { server -> UiHarness(server,room(1,"사진 메모리 검증 가족")).use { ui ->
            ui.await(timeout=15000) { ui.has("메모리 검증 소식 30") }
            val deadline=SystemClock.uptimeMillis()+60000
            var previous=-1; var stable=0
            while(SystemClock.uptimeMillis()<deadline) {
                val size=server.paths().count { it.startsWith("/api/photo/") }
                stable=if(size==previous) stable+1 else 0
                previous=size
                if(stable>=8 && size>0) break
                Thread.sleep(500)
            }
            val memory=Debug.MemoryInfo();Debug.getMemoryInfo(memory)
            var views=0;var allocated=0L
            ui.test.runOnMainSync {
                for(view in ui.all().filterIsInstance<ImageView>()) {
                    val drawable=view.drawable as? android.graphics.drawable.BitmapDrawable ?: continue
                    views++;allocated+=drawable.bitmap.allocationByteCount
                }
            }
            val photoPaths=server.paths().filter { it.startsWith("/api/photo/") }
            val metrics=JSONObject().put("photo_requests",photoPaths.size).put("distinct_photo_urls",photoPaths.toSet().size)
                .put("pss_kib",memory.totalPss).put("native_heap_bytes",Debug.getNativeHeapAllocatedSize())
                .put("image_views_with_bitmaps",views).put("sum_view_bitmap_bytes",allocated)
            java.io.File(ui.test.targetContext.cacheDir,"review-photo-memory.json").writeText(metrics.toString(2))
            println("REVIEW_PHOTO_MEMORY="+metrics)
            ui.screenshot("review-photo-memory.png")
            assertFalse("The final offscreen post must not be downloaded before scrolling",photoPaths.any { it.startsWith("/api/photo/30/") })
            assertEquals("A page and thumbnail must share their download",photoPaths.toSet().size,photoPaths.size)
            ui.test.runOnMainSync {
                for(view in ui.all().filterIsInstance<ImageView>().filter { it.scaleType==ImageView.ScaleType.CENTER_CROP }) {
                    val drawable=view.drawable as? android.graphics.drawable.BitmapDrawable ?: continue
                    assertTrue("Thumbnails must be decoded near their display size",drawable.bitmap.width <= view.width*2)
                }
                ui.all().filterIsInstance<android.widget.ScrollView>().first().fullScroll(View.FOCUS_DOWN)
            }
            ui.await(timeout=15000) { server.paths().any { it.startsWith("/api/photo/30/") } }
            Thread.sleep(1200)
            var retainedOffscreen=0
            ui.test.runOnMainSync {
                for(view in ui.all().filterIsInstance<ImageView>()) {
                    if(view is kr.talkdock.app.ui.TodakArtView) continue // Small shared brand artwork is not a downloaded feed photo.
                    if(view.drawable !is android.graphics.drawable.BitmapDrawable) continue
                    var anchor: View=view
                    if(view.scaleType!=ImageView.ScaleType.CENTER_CROP) {
                        var parent=view.parent
                        while(parent is View) {
                            if(parent is kr.talkdock.app.ui.PhotoCarousel) { anchor=parent; break }
                            parent=parent.parent
                        }
                    }
                    if(!anchor.getGlobalVisibleRect(android.graphics.Rect())) retainedOffscreen++
                }
            }
            val afterScroll = Debug.MemoryInfo(); Debug.getMemoryInfo(afterScroll)
            metrics.put("after_scroll_pss_kib",afterScroll.totalPss).put("offscreen_downloaded_bitmaps",retainedOffscreen)
            java.io.File(ui.test.targetContext.cacheDir,"review-photo-memory.json").writeText(metrics.toString(2))
            assertEquals("Scrolling must release offscreen bitmap references",0,retainedOffscreen)
        } }
    }
}
