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
import androidx.test.runner.lifecycle.ActivityLifecycleMonitorRegistry
import androidx.test.runner.lifecycle.Stage
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.ByteArrayOutputStream
import java.net.ServerSocket
import java.net.SocketException
import java.util.Collections
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/** [room] is the request's X-Family-Room header and [token] its bearer token. */
internal data class Request(val method: String, val path: String, val body: String, val room: String? = null, val token: String? = null)
internal data class Reply(val body: ByteArray, val status: Int = 200, val type: String = "application/json")
internal fun jsonReply(value: JSONObject, status: Int = 200) = Reply(value.toString().toByteArray(), status)

/**
 * Unless [rooms] answers `/api/families/`, the room list is derived from the test's
 * `/api/families/current/` reply: that room on 200, no rooms on 403, the same error otherwise.
 */
internal class MockApi(private val rooms: ((Request) -> Reply)? = null, private val respond: (Request) -> Reply) : AutoCloseable {
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
                    val room = lines.firstOrNull { it.startsWith("X-Family-Room:", true) }?.substringAfter(":")?.trim()
                    val token = lines.firstOrNull { it.startsWith("Authorization:", true) }?.substringAfter("Bearer ", "")?.trim()
                    val request = Request(first[0], first[1], String(bytes, Charsets.UTF_8), room, token)
                    requests.add(request)
                    val reply = if (request.path == "/api/families/") rooms?.invoke(request) ?: roomsFromCurrent(request) else respond(request)
                    client.getOutputStream().apply {
                        write("HTTP/1.1 ${reply.status} Test\r\nContent-Type: ${reply.type}\r\nContent-Length: ${reply.body.size}\r\nConnection: close\r\n\r\n".toByteArray())
                        write(reply.body); flush()
                    }
                }
            } catch (_: SocketException) { if (socket.isClosed) break }
        }
    }.apply { isDaemon = true; start() }
    private fun roomsFromCurrent(request: Request): Reply {
        val current = respond(request.copy(path = "/api/families/current/"))
        if (current.status == 403) return jsonReply(JSONObject().put("rooms", JSONArray()))
        if (current.status != 200) return current
        val room = JSONObject(String(current.body, Charsets.UTF_8))
        return jsonReply(JSONObject().put("rooms", JSONArray().put(roomSummary(room.getInt("id"), room.getString("name")))))
    }
    fun paths(): List<String> = synchronized(requests) { requests.map { it.path } }
    override fun close() { socket.close(); worker.join(1000) }
}

internal fun roomSummary(id: Int, name: String) =
    JSONObject().put("id", id).put("name", name).put("is_owner", true).put("member_count", 1)

/** Starts MainActivity signed in as user 999, or signed out; [others] are extra accounts saved on the phone. */
internal class UiHarness(private val api: MockApi, room: JSONObject?, large: Boolean = false,
                         signedIn: Boolean = true, others: List<JSONObject> = emptyList()) : AutoCloseable {
    val test = InstrumentationRegistry.getInstrumentation()
    private val prefs = test.targetContext.getSharedPreferences("talkdock-session", Context.MODE_PRIVATE)
    private val savedPreferences = prefs.all.toMap()
    val activity: MainActivity
    init {
        val user = JSONObject().put("user_id",999).put("username","review-user").put("token","mock-review-token")
            .put("name","테스트 사용자").put("large",large)
        if (room != null) user.put("room",room)
        val edit = prefs.edit().clear().putString("server",api.base)
        if (signedIn) edit.putString("current",user.toString()).putString("accounts",JSONArray(listOf(user) + others).toString())
        edit.commit()
        activity=test.startActivitySync(Intent(test.targetContext,MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)) as MainActivity
    }
    fun all(view: View = activity.window.decorView): List<View> {
        fun children(root: View): List<View> = listOf(root) + if (root is ViewGroup)
            (0 until root.childCount).flatMap { children(root.getChildAt(it)) } else emptyList()
        val result = children(view).toMutableList()
        if (view === activity.window.decorView) for (name in listOf("profileMenuDialog", "assistantDialog")) {
            val field = activity.javaClass.getDeclaredField(name).apply { isAccessible = true }
            val dialog = field.get(activity) as? android.app.Dialog
            if (dialog?.isShowing == true) dialog.window?.decorView?.let { result.addAll(children(it)) }
        }
        return result
    }
    fun openProfile() {
        if (all().none { it.contentDescription == "프로필 메뉴" }) {
            test.runOnMainSync { activity.onBackPressedDispatcher.onBackPressed() }
            await { all().any { it.contentDescription == "프로필 메뉴" } && all().none { it is kr.talkdock.app.ui.TodakWaitingView } }
        }
        test.runOnMainSync { all().first { it.contentDescription == "프로필 메뉴" }.performClick() }
        await { has("가족방 바꾸기") }
    }
    fun openSettings() { openProfile(); click("설정") }
    fun openRooms() { openProfile(); click("가족방 바꾸기") }
    fun openDaily() {
        if (!has("하루")) { test.runOnMainSync { activity.onBackPressedDispatcher.onBackPressed() }; await { has("하루") && all().none { it is kr.talkdock.app.ui.TodakWaitingView } } }
        click("하루")
    }
    fun openCurrentPost() {
        if (hasPostDetail()) return
        await { all().any { it is kr.talkdock.app.ui.PhotoLetterDeck } }
        test.runOnMainSync {
            val deck = all().filterIsInstance<kr.talkdock.app.ui.PhotoLetterDeck>().single()
            all(deck.currentCard).first { it.contentDescription == "소식과 댓글 자세히 보기" }.performClick()
        }
        await { hasPostDetail() }
    }
    fun hasPostDetail() = has("가족의 소식") && all().any { it is kr.talkdock.app.ui.CommentComposer }
    fun selectLetter(id: Int) {
        await { all().any { it is kr.talkdock.app.ui.PhotoLetterDeck } }
        test.runOnMainSync {
            val deck = all().filterIsInstance<kr.talkdock.app.ui.PhotoLetterDeck>().single()
            for (index in 0 until deck.letterCount) { deck.show(index); if (deck.currentPost.optInt("id") == id) break }
            assertEquals(id, deck.currentPost.optInt("id"))
        }
    }
    fun hasRoom(name: String) = has(name) || all().any { androidx.core.view.ViewCompat.getStateDescription(it)?.toString() == "현재 가족방: $name" }
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
    fun openAssistantOption(label: String) {
        await { all().any { it is kr.talkdock.app.ui.FloatingAssistantView } }
        test.runOnMainSync {
            assertTrue(all().filterIsInstance<kr.talkdock.app.ui.FloatingAssistantView>().single().performClick())
        }
        await { has(label) }
        click(label)
    }
    fun background() {
        test.runOnMainSync {
            activity.startActivity(Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        }
        await { ActivityLifecycleMonitorRegistry.getInstance().getLifecycleStageOf(activity) in listOf(Stage.PAUSED, Stage.STOPPED) }
    }
    fun screenshot(name: String) {
        test.waitForIdleSync(); Thread.sleep(250)
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

internal fun room(id: Int, name: String) = JSONObject().put("id",id).put("name",name)
    .put("invite_code","REVIEW").put("owner_name","테스트 사용자").put("digest_time","21:00")
    .put("members",JSONArray().put(JSONObject().put("id",999).put("name","테스트 사용자")
        .put("is_owner",true).put("relationship","나")))
internal fun emptyFeed() = jsonReply(JSONObject().put("posts",JSONArray()))

@RunWith(AndroidJUnit4::class)
class ReviewRoomUiTest {
    @Test fun existingMemberCanStillCreateOrJoinAnotherRoom() {
        MockApi { request -> if(request.path=="/api/families/current/") jsonReply(room(1,"검증 가족 A")) else emptyFeed() }.use { api -> UiHarness(api,room(1,"검증 가족 A")).use { ui ->
            ui.await { ui.has("첫 소식을 기다리고 있어요") }
            ui.openRooms()
            ui.await { ui.has("지금 보는 가족방") && ui.has("검증 가족 A") }
            ui.test.runOnMainSync {
                assertTrue(ui.has("새 가족방 만들기")); assertTrue(ui.has("초대 코드로 참여하기"))
            }
            ui.screenshot("review-existing-room.png")
        } }
    }
    @Test fun severalRoomsWithoutSavedChoiceOpenThePicker() {
        MockApi(rooms = { jsonReply(JSONObject().put("rooms", JSONArray().put(roomSummary(1,"가족 A")).put(roomSummary(2,"가족 B")))) }) { request -> when(request.path) {
            "/api/families/current/" -> jsonReply(if(request.room=="2") room(2,"가족 B") else room(1,"가족 A"))
            else -> emptyFeed()
        } }.use { api -> UiHarness(api,null).use { ui ->
            ui.await { ui.has("들어갈 가족방을 골라 주세요.") && ui.has("가족 A") && ui.has("가족 B") }
            ui.screenshot("review-room-picker.png")
            ui.click("가족 B"); ui.await { ui.has("첫 소식을 기다리고 있어요") }
            val feeds = synchronized(api.requests) { api.requests.filter { it.path == "/api/posts/" }.map { it.room } }
            assertEquals("The feed must be requested for the chosen room", "2", feeds.last())
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
            ui.click("로그인"); ui.await { ui.hasRoom("서버 가족 A") && ui.has("첫 소식을 기다리고 있어요") }
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
                ui.test.runOnMainSync { assertTrue(ui.hasRoom("서버 가족 A")); assertFalse(ui.hasRoom("기기에 저장된 가족 B")) }
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
            ui.click("가족 방 만들기"); ui.await { ui.hasRoom("서버 가족 A") && ui.has("첫 소식을 기다리고 있어요") }
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
    @Test fun memberCanCreateAnotherRoomAndSwitchesToIt() {
        var created = false
        MockApi(rooms = { jsonReply(JSONObject().put("rooms", JSONArray().put(roomSummary(1,"가족 A"))
                .apply { if(created) put(roomSummary(2,"새 가족 B")) })) }) { request -> when(request.path) {
            "/api/families/create/" -> { created = true; jsonReply(JSONObject().put("room",room(2,"새 가족 B")),201) }
            "/api/families/current/" -> jsonReply(if(request.room=="2") room(2,"새 가족 B") else room(1,"가족 A"))
            else -> emptyFeed()
        } }.use { api -> UiHarness(api,room(1,"가족 A")).use { ui ->
            ui.await { ui.has("첫 소식을 기다리고 있어요") }
            ui.openRooms(); ui.await { ui.has("새 가족방 만들기") }; ui.click("새 가족방 만들기")
            ui.test.runOnMainSync {
                val fields=ui.all().filterIsInstance<EditText>()
                fields[0].setText("새 가족 B"); fields[1].setText("Review-Room-12345")
            }
            ui.click("가족 방 만들기"); ui.await { ui.has("가족 방이 준비됐어요.") && ui.hasRoom("새 가족 B") }
            ui.click("가족 소식으로 가기"); ui.await { ui.has("첫 소식을 기다리고 있어요") }
            val feeds = synchronized(api.requests) { api.requests.filter { it.path == "/api/posts/" }.map { it.room } }
            assertEquals("The feed after creation must be requested for the new room", "2", feeds.last())
        } }
    }
    @Test fun failedStartupCheckDoesNotOpenCachedRoomOrFetchPosts() {
        MockApi { request -> if(request.path=="/api/families/current/") jsonReply(JSONObject().put("error","테스트 서버 확인 실패"),503) else emptyFeed() }
            .use { api -> UiHarness(api,room(2,"확인되지 않은 가족 B")).use { ui ->
                ui.await { api.paths().contains("/api/families/") }
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
            assertFalse("The final offscreen post must not be downloaded before scrolling",photoPaths.any { it.startsWith("/api/photo/1/") })
            assertEquals("A page and thumbnail must share their download",photoPaths.toSet().size,photoPaths.size)
            ui.test.runOnMainSync {
                for(view in ui.all().filterIsInstance<ImageView>().filter { it.scaleType==ImageView.ScaleType.CENTER_CROP }) {
                    val drawable=view.drawable as? android.graphics.drawable.BitmapDrawable ?: continue
                    assertTrue("Thumbnails must be decoded near their display size",drawable.bitmap.width <= view.width*2)
                }
                ui.all().filterIsInstance<kr.talkdock.app.ui.PhotoLetterDeck>().single().show(29)
            }
            ui.await(timeout=15000) { server.paths().any { it.startsWith("/api/photo/1/") } }
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

@RunWith(AndroidJUnit4::class)
class PhotoLoaderRegressionTest {
    @Test fun carouselCanJumpToTheLastPhotoAndReturn() {
        val colors = listOf(android.graphics.Color.RED, android.graphics.Color.GREEN,
            android.graphics.Color.BLUE, android.graphics.Color.YELLOW, android.graphics.Color.MAGENTA)
        val photos = colors.map { color ->
            val source = Bitmap.createBitmap(400, 400, Bitmap.Config.ARGB_8888)
            source.eraseColor(color)
            ByteArrayOutputStream().also { source.compress(Bitmap.CompressFormat.JPEG, 90, it); source.recycle() }.toByteArray()
        }
        lateinit var api: MockApi
        fun sourcePost() = JSONObject().put("id", 1).put("author_name", "검증 사용자").put("relationship", "나")
            .put("caption", "사진 넘기기 검증").put("created_at", "2026-10-19T09:00:00+09:00").put("comment_count", 0)
            .put("comments", JSONArray()).put("images", JSONArray().apply { repeat(5) { put(JSONObject().put("url", api.base + "photo/$it/")) } })
        api = MockApi { request -> when {
            request.path == "/api/families/current/" -> jsonReply(room(1, "사진 넘기기 검증"))
            request.path.startsWith("/api/photo/") -> Reply(photos[request.path.trimEnd('/').substringAfterLast('/').toInt()], type = "image/jpeg")
            request.path == "/api/posts/1/" -> jsonReply(sourcePost())
            else -> jsonReply(JSONObject().put("posts", JSONArray().put(sourcePost())))
        } }
        api.use { server -> UiHarness(server, room(1, "사진 넘기기 검증")).use { ui ->
            ui.await { ui.has("사진 넘기기 검증") }; ui.openCurrentPost()
            ui.await { ui.all().any { it is kr.talkdock.app.ui.PhotoCarousel } }
            // The loader only fetches photos on screen; on small screens the post starts below the fold.
            ui.test.runOnMainSync {
                val carousel = ui.all().filterIsInstance<kr.talkdock.app.ui.PhotoCarousel>().single()
                carousel.requestRectangleOnScreen(android.graphics.Rect(0, 0, carousel.width, carousel.height), true)
            }
            for (index in listOf(4, 2, 0)) {
                ui.test.runOnMainSync {
                    ui.all().first { it.contentDescription == "${index + 1}번째 사진으로 이동" }.performClick()
                }
                ui.await {
                    val carousel = ui.all().filterIsInstance<kr.talkdock.app.ui.PhotoCarousel>().single()
                    val image = ui.all(carousel).filterIsInstance<ImageView>()
                        .filter { it.scaleType == ImageView.ScaleType.FIT_CENTER }[index]
                    val bitmap = (image.drawable as? android.graphics.drawable.BitmapDrawable)?.bitmap
                    val pixel = bitmap?.getPixel(bitmap.width / 2, bitmap.height / 2)
                    carousel.currentIndex == index && pixel != null &&
                        kotlin.math.abs(android.graphics.Color.red(pixel) - android.graphics.Color.red(colors[index])) <= 4 &&
                        kotlin.math.abs(android.graphics.Color.green(pixel) - android.graphics.Color.green(colors[index])) <= 4 &&
                        kotlin.math.abs(android.graphics.Color.blue(pixel) - android.graphics.Color.blue(colors[index])) <= 4
                }
            }
        } }
    }

    @Test fun portraitFitsBothViewDimensions() = checkDecodedSize(400, 4000, false)
    @Test fun landscapeFitsBothViewDimensions() = checkDecodedSize(4000, 400, false)
    @Test fun tallThumbnailOnlyRetainsItsVisibleCrop() = checkDecodedSize(400, 4000, true)

    private fun checkDecodedSize(sourceWidth: Int, sourceHeight: Int, thumbnail: Boolean) {
        val source = Bitmap.createBitmap(sourceWidth, sourceHeight, Bitmap.Config.ARGB_8888)
        source.eraseColor(android.graphics.Color.CYAN)
        val jpeg = ByteArrayOutputStream().also { source.compress(Bitmap.CompressFormat.JPEG, 90, it) }.toByteArray()
        source.recycle()
        MockApi { request -> when {
            request.path == "/api/families/current/" -> jsonReply(room(1, "사진 크기 검증"))
            request.path.contains("/photo/") -> Reply(jpeg, type = "image/jpeg")
            else -> emptyFeed()
        } }.use { api -> UiHarness(api, room(1, "사진 크기 검증")).use { ui ->
            ui.await { ui.has("첫 소식을 기다리고 있어요") }
            lateinit var image: ImageView
            lateinit var loader: kr.talkdock.app.ui.ViewportPhotoLoader
            ui.test.runOnMainSync {
                val container = android.widget.FrameLayout(ui.activity)
                image = ImageView(ui.activity).apply {
                    scaleType = if (thumbnail) ImageView.ScaleType.CENTER_CROP else ImageView.ScaleType.FIT_CENTER
                }
                container.addView(image, android.widget.FrameLayout.LayoutParams(200, 200))
                ui.activity.setContentView(container)
                loader = kr.talkdock.app.ui.ViewportPhotoLoader(container)
                loader.bind(image, kr.talkdock.app.data.ApiClient(baseUrl = api.base), api.base + "photo/test/", thumbnail)
            }
            try {
                ui.await { image.drawable is android.graphics.drawable.BitmapDrawable }
                ui.test.runOnMainSync {
                    val bitmap = (image.drawable as android.graphics.drawable.BitmapDrawable).bitmap
                    println("PHOTO_DECODE_SIZE source=${sourceWidth}x$sourceHeight thumbnail=$thumbnail bitmap=${bitmap.width}x${bitmap.height} bytes=${bitmap.allocationByteCount}")
                    assertTrue("Decoded width must fit the view", bitmap.width <= image.width)
                    assertTrue("Decoded height must fit the view", bitmap.height <= image.height)
                    if (thumbnail) assertEquals("Crop must fill the square thumbnail", bitmap.width, bitmap.height)
                    else assertEquals("Keep the photo's aspect ratio", sourceWidth.toDouble() / sourceHeight, bitmap.width.toDouble() / bitmap.height, 0.01)
                }
            } finally { ui.test.runOnMainSync { loader.close() } }
        } }
    }

    @Test fun releasedViewsDoNotKeepQueuedDownloads() {
        val source = Bitmap.createBitmap(40, 40, Bitmap.Config.ARGB_8888)
        val jpeg = ByteArrayOutputStream().also { source.compress(Bitmap.CompressFormat.JPEG, 90, it) }.toByteArray()
        source.recycle()
        val gate = java.util.concurrent.CountDownLatch(1)
        MockApi { request -> when {
            request.path == "/api/families/current/" -> jsonReply(room(1, "사진 대기열 검증"))
            request.path.contains("/photo/") -> {
                if (!request.path.contains("sentinel")) gate.await(10, java.util.concurrent.TimeUnit.SECONDS)
                Reply(jpeg, type = "image/jpeg")
            }
            else -> emptyFeed()
        } }.use { api -> UiHarness(api, room(1, "사진 대기열 검증")).use { ui ->
            ui.await { ui.has("첫 소식을 기다리고 있어요") }
            lateinit var container: android.widget.FrameLayout
            lateinit var loader: kr.talkdock.app.ui.ViewportPhotoLoader
            val images = mutableListOf<ImageView>()
            ui.test.runOnMainSync {
                container = android.widget.FrameLayout(ui.activity)
                ui.activity.setContentView(container)
                loader = kr.talkdock.app.ui.ViewportPhotoLoader(container)
                repeat(40) { index ->
                    val image = ImageView(ui.activity)
                    images.add(image)
                    container.addView(image, android.widget.FrameLayout.LayoutParams(100, 100))
                    loader.bind(image, kr.talkdock.app.data.ApiClient(baseUrl = api.base), api.base + "photo/$index/")
                }
            }
            try {
                ui.await { api.paths().any { it.contains("/photo/") } }
                lateinit var sentinel: ImageView
                ui.test.runOnMainSync {
                    loader.clearViews()
                    container.removeAllViews()
                    sentinel = ImageView(ui.activity)
                    container.addView(sentinel, android.widget.FrameLayout.LayoutParams(100, 100))
                    loader.bind(sentinel, kr.talkdock.app.data.ApiClient(baseUrl = api.base), api.base + "photo/sentinel/")
                }
                gate.countDown()
                ui.await { sentinel.drawable is android.graphics.drawable.BitmapDrawable }
                val stale = api.paths().count { it.contains("/photo/") && !it.contains("sentinel") }
                println("PHOTO_RELEASED_DOWNLOADS=$stale")
                assertTrue("Only the two running downloads may finish after views are released; queued work must be cancelled", stale <= 2)
            } finally {
                gate.countDown()
                ui.test.runOnMainSync { loader.close() }
            }
        } }
    }
}

/** These tests use local JSON and generated audio; no paid AI/TTS calls. */
@RunWith(AndroidJUnit4::class)
class InlinePostAudioTest {
    private fun post(id: Int) = JSONObject().put("id", id).put("author_name", "가족 $id")
        .put("relationship", "자녀").put("caption", "오늘의 소식 $id").put("created_at", "2026-10-19T10:00:00+09:00")
        .put("comment_count", 0).put("images", JSONArray()).put("comments", JSONArray())
    private fun ready(text: String = "사진과 글을 설명한 AI 요약") = jsonReply(JSONObject().put("status", "ready").put("text", text))
    private fun audio(milliseconds: Int = 8000): Reply {
        val samples = milliseconds * 16
        val bytes = java.nio.ByteBuffer.allocate(44 + samples * 2).order(java.nio.ByteOrder.LITTLE_ENDIAN)
        bytes.put("RIFF".toByteArray()).putInt(36 + samples * 2).put("WAVEfmt ".toByteArray())
            .putInt(16).putShort(1).putShort(1).putInt(16000).putInt(32000).putShort(2).putShort(16)
            .put("data".toByteArray()).putInt(samples * 2)
        repeat(samples) { bytes.putShort(0) }
        return Reply(bytes.array(), type = "audio/wav")
    }
    private fun server(custom: (Request) -> Reply? = { null }): MockApi = MockApi { request ->
        custom(request) ?: when {
            request.path == "/api/families/current/" -> jsonReply(room(1, "재생 검증 가족"))
            request.path == "/api/posts/" -> jsonReply(JSONObject().put("posts", JSONArray().put(post(1)).put(post(2))))
            request.path.endsWith("/message/") -> ready()
            request.path == "/api/speech/" -> audio()
            request.path.startsWith("/api/digests/?") -> jsonReply(JSONObject().put("status", "ready")
                .put("text", "하루 요약").put("posts", JSONArray().put(post(1))))
            request.path.matches(Regex("/api/posts/[12]/")) -> jsonReply(post(request.path.split('/')[3].toInt()))
            else -> jsonReply(JSONObject())
        }
    }
    private fun panels(ui: UiHarness) = ui.all().filterIsInstance<kr.talkdock.app.ui.InlinePostAudio>()
    private fun tap(ui: UiHarness) {
        var active = false
        ui.test.runOnMainSync { active = panels(ui).single().isPlaying }
        ui.openAssistantOption(if (active) "듣기 중지" else "음성으로 듣기")
    }
    private fun playing(ui: UiHarness): Boolean {
        val speaker = MainActivity::class.java.getDeclaredField("speaker").apply { isAccessible = true }.get(ui.activity)
        val player = speaker.javaClass.getDeclaredField("player").apply { isAccessible = true }.get(speaker) as? android.media.MediaPlayer
        return player?.isPlaying == true
    }
    private fun open(ui: UiHarness) { ui.await { ui.has("오늘의 소식 2") }; ui.openCurrentPost() }

    private fun readSummary(ui: UiHarness, index: Int = 0) {
        if (index == 1) {
            ui.test.runOnMainSync { ui.activity.onBackPressedDispatcher.onBackPressed() }
            ui.selectLetter(1); ui.openCurrentPost()
        }
        ui.openAssistantOption("AI 요약 보기")
    }
    @Test fun feedBotActionsOpenTheSelectedPostAndSummaryDoesNotStartSpeech() {
        for (large in listOf(false, true)) server().use { api -> UiHarness(api, room(1, "재생"), large).use { ui ->
            ui.selectLetter(1)
            ui.openAssistantOption("AI 요약 보기")
            ui.await { ui.hasPostDetail() && ui.has("사진과 글을 설명한 AI 요약") }
            assertTrue(api.paths().contains("/api/posts/1/message/"))
            assertFalse(api.paths().contains("/api/speech/"))
            ui.test.runOnMainSync { assertTrue(ui.has("오늘의 소식 1")); assertFalse(playing(ui)) }
            ui.test.runOnMainSync { ui.activity.onBackPressedDispatcher.onBackPressed() }
            ui.selectLetter(2)
            ui.openAssistantOption("음성으로 듣기")
            ui.await { ui.hasPostDetail() && playing(ui) }
            assertTrue(api.paths().contains("/api/posts/2/message/"))
            ui.test.runOnMainSync { assertTrue(ui.has("오늘의 소식 2")) }
            tap(ui); ui.await { !playing(ui) && !panels(ui).single().isPlaying }
        } }
    }
    @Test fun summaryAndSpeechShowTheirOwnPreparationUntilReadyInBothSizes() {
        for (large in listOf(false, true)) {
            val releaseSummary = CountDownLatch(1)
            val releaseSpeech = CountDownLatch(1)
            try {
                server { request -> when {
                    request.path.endsWith("/message/") -> { releaseSummary.await(15, TimeUnit.SECONDS); ready() }
                    request.path == "/api/speech/" -> { releaseSpeech.await(15, TimeUnit.SECONDS); audio() }
                    else -> null
                } }.use { api -> UiHarness(api, room(1, "재생"), large).use { ui ->
                    open(ui); readSummary(ui)
                    ui.await { ui.has("가족 소식 준비중") }
                    ui.test.runOnMainSync {
                        assertTrue(ui.all().single { it.tag == "summary-loading" }.isShown)
                        assertFalse(ui.has("목소리 생성중")); assertFalse(playing(ui))
                    }
                    assertFalse(api.paths().contains("/api/speech/"))
                    releaseSummary.countDown()
                    ui.await { ui.has("사진과 글을 설명한 AI 요약") && !ui.has("가족 소식 준비중") }
                    tap(ui)
                    ui.await { ui.has("목소리 생성중") }
                    ui.test.runOnMainSync {
                        assertTrue(ui.all().single { it.tag == "speech-loading" }.isShown)
                        assertTrue(ui.has("사진과 글을 설명한 AI 요약"))
                        assertFalse(ui.has("가족 소식 준비중")); assertFalse(playing(ui))
                    }
                    releaseSpeech.countDown()
                    ui.await { playing(ui) && !ui.has("목소리 생성중") }
                    assertEquals(1, api.paths().count { it.endsWith("/message/") })
                    assertEquals(1, api.paths().count { it == "/api/speech/" })
                    tap(ui)
                } }
            } finally { releaseSummary.countDown(); releaseSpeech.countDown() }
        }
    }
    @Test fun summaryCanBeReadWithoutSpeechAndListeningReusesItInBothSizes() {
        for (large in listOf(false, true)) server().use { api -> UiHarness(api, room(1, "재생"), large).use { ui ->
            open(ui)
            ui.test.runOnMainSync {
                assertFalse(ui.has("말로 답장")); assertFalse(ui.has("목소리로 댓글 남기기"))
                assertFalse(ui.has("궁금한 점을 물어보세요"))
                assertFalse(ui.has("음성으로 듣기")); assertFalse(ui.has("AI 요약 보기"))
                assertFalse(ui.has("댓글은 이 가족방에만 보여요."))
            }
            ui.test.waitForIdleSync(); SystemClock.sleep(400)
            ui.screenshot(if (large) "post-actions-large.png" else "post-actions-default.png")
            readSummary(ui)
            ui.await { ui.has("사진과 글을 설명한 AI 요약") }
            ui.test.runOnMainSync { assertFalse(playing(ui)); assertFalse(panels(ui)[0].isPlaying) }
            assertFalse(api.paths().contains("/api/speech/"))
            readSummary(ui)
            assertEquals(1, api.paths().count { it.endsWith("/message/") })
            tap(ui); ui.await { playing(ui) }
            assertEquals(1, api.paths().count { it.endsWith("/message/") })
            assertEquals("사진과 글을 설명한 AI 요약", JSONObject(api.requests.single { it.path == "/api/speech/" }.body).getString("text"))
            tap(ui)
            ui.openCurrentPost()
            ui.await { ui.hasPostDetail() }
            readSummary(ui); ui.await { ui.has("사진과 글을 설명한 AI 요약") }
            assertEquals(1, api.paths().count { it == "/api/speech/" })
            ui.screenshot("post-readable-summary.png")
        } }
    }

    @Test fun listeningDuringTextSummaryLoadReusesPendingRequest() {
        server { request -> if (request.path.endsWith("/message/")) { Thread.sleep(500); ready() } else null }
            .use { api -> UiHarness(api, room(1, "재생")).use { ui ->
                open(ui); readSummary(ui)
                ui.await { api.paths().any { it.endsWith("/message/") } }
                readSummary(ui); tap(ui)
                ui.await { playing(ui) }
                assertEquals(1, api.paths().count { it.endsWith("/message/") })
                assertEquals(1, api.paths().count { it == "/api/speech/" })
            } }
    }

    @Test fun textSummaryFailureRetriesWithoutStartingSpeech() {
        var requests = 0
        server { request -> if (request.path.endsWith("/message/")) {
            if (++requests == 1) jsonReply(JSONObject().put("error", "요약 테스트 오류"), 503) else ready()
        } else null }.use { api -> UiHarness(api, room(1, "재생")).use { ui ->
            open(ui); readSummary(ui); ui.await { ui.has("요약 테스트 오류") }
            ui.click("설명 다시 준비하기"); ui.await { ui.has("사진과 글을 설명한 AI 요약") }
            assertEquals(listOf("GET", "POST"), api.requests.filter { it.path.endsWith("/message/") }.map { it.method })
            assertFalse(api.paths().contains("/api/speech/"))
            ui.test.runOnMainSync { assertFalse(playing(ui)); assertFalse(panels(ui)[0].isPlaying) }
        } }
    }

    @Test fun openingAnotherLetterStopsPreviousAudioAndCanReadItsSummary() {
        server().use { api -> UiHarness(api, room(1, "재생")).use { ui ->
            open(ui); tap(ui); ui.await { playing(ui) }
            readSummary(ui, 1)
            ui.await { ui.has("사진과 글을 설명한 AI 요약") }
            ui.test.runOnMainSync { assertFalse(playing(ui)); assertFalse(panels(ui).single().isPlaying) }
            assertEquals(1, api.paths().count { it == "/api/speech/" })
        } }
    }
    @Test fun leavingPendingTextSummaryDoesNotRenderOnAnotherPage() {
        server { request -> if (request.path.endsWith("/message/")) { Thread.sleep(500); ready() } else null }
            .use { api -> UiHarness(api, room(1, "재생")).use { ui ->
                open(ui); readSummary(ui); ui.await { api.paths().any { it.endsWith("/message/") } }
                ui.test.runOnMainSync { ui.activity.onBackPressedDispatcher.onBackPressed() }
                ui.await { ui.all().any { it is kr.talkdock.app.ui.PhotoLetterDeck } }
                Thread.sleep(700)
                ui.test.runOnMainSync { assertFalse(ui.has("사진과 글을 설명한 AI 요약")); assertFalse(playing(ui)) }
                assertFalse(api.paths().contains("/api/speech/"))
            } }
    }

    @Test fun detailAutoPlaysWithoutNavigationAndSecondTapStops() {
        server().use { api -> UiHarness(api, room(1, "재생" )).use { ui ->
            open(ui)
            assertFalse(api.paths().any { it.endsWith("/message/") })
            tap(ui)
            ui.await { ui.has("사진과 글을 설명한 AI 요약") && playing(ui) }
            ui.test.runOnMainSync {
                assertTrue(ui.has("가족의 소식")); assertFalse(ui.has("가족 소식 듣기"))
                assertTrue(panels(ui)[0].isPlaying)
                assertFalse(ui.has("소식을 재생하고 있어요. 다시 누르면 중지돼요."))
                assertFalse(ui.all().any { it is kr.talkdock.app.ui.TodakWaitingView })
            }
            ui.test.runOnMainSync {
                val panel = panels(ui)[0]
                panel.requestRectangleOnScreen(android.graphics.Rect(0, 0, panel.width, panel.height), true)
            }
            ui.screenshot("inline-post-audio.png")
            tap(ui)
            ui.await { !playing(ui) && !panels(ui)[0].isPlaying }
            assertEquals(1, api.paths().count { it == "/api/speech/" })
            tap(ui)
            ui.await { playing(ui) }
            assertEquals(1, api.paths().count { it.endsWith("/message/") })
        } }
    }
    @Test fun stopDuringSummaryIgnoresLateResult() {
        server { request -> if (request.path.endsWith("/message/")) { Thread.sleep(500); ready() } else null }
            .use { api -> UiHarness(api, room(1, "재생")).use { ui ->
                open(ui); tap(ui)
                ui.await { api.paths().any { it.endsWith("/message/") } }
                tap(ui)
                Thread.sleep(800)
                ui.test.runOnMainSync { assertFalse(playing(ui)); assertFalse(panels(ui)[0].isPlaying) }
                assertFalse(api.paths().contains("/api/speech/"))
            } }
    }
    @Test fun stopDuringSpeechRequestDoesNotStartLateAudio() {
        server { request -> if (request.path == "/api/speech/") { Thread.sleep(500); audio() } else null }
            .use { api -> UiHarness(api, room(1, "재생")).use { ui ->
                open(ui); tap(ui); ui.await { api.paths().contains("/api/speech/") }
                tap(ui); Thread.sleep(800)
                ui.test.runOnMainSync { assertFalse(playing(ui)); assertFalse(panels(ui)[0].isPlaying) }
                assertTrue(java.io.File(ui.activity.cacheDir, ".").listFiles().orEmpty().none { it.name.startsWith("post-listen-") })
            } }
    }
    @Test fun decoderFailureIsInlineAndCanRetry() {
        var attempts = 0
        server { request -> if (request.path == "/api/speech/" && ++attempts == 1)
            Reply("invalid audio".toByteArray(), type = "audio/mpeg") else null }
            .use { api -> UiHarness(api, room(1, "재생")).use { ui ->
                open(ui); tap(ui); ui.await { ui.has("음성 다시 준비하기") }
                ui.test.runOnMainSync { assertFalse(panels(ui)[0].isPlaying) }
                ui.click("음성 다시 준비하기"); ui.await { playing(ui) }
            } }
    }
    @Test fun switchingPostsDuringSpeechRequestDoesNotPlayOldPost() {
        server { request -> when {
            request.path == "/api/posts/2/message/" -> ready("첫 글 요약")
            request.path == "/api/posts/1/message/" -> ready("둘째 글 요약")
            request.path == "/api/speech/" && request.body.contains("첫 글 요약") -> { Thread.sleep(500); audio() }
            else -> null
        } }.use { api -> UiHarness(api, room(1, "재생")).use { ui ->
            open(ui); tap(ui); ui.await { api.paths().contains("/api/speech/") }
            ui.test.runOnMainSync { ui.activity.onBackPressedDispatcher.onBackPressed() }
            ui.selectLetter(1); ui.openCurrentPost(); tap(ui)
            ui.await { playing(ui) && panels(ui).single().isPlaying }
            assertEquals(2, api.paths().count { it == "/api/speech/" })
            val files = java.io.File(ui.activity.cacheDir, ".").listFiles().orEmpty().filter { it.name.startsWith("post-listen-") }
            assertEquals("Stale response audio must be deleted", 1, files.size)
        } }
    }
    @Test fun processingCanBeCheckedAgainAndFailureCanRegenerate() {
        var gets = 0
        server { request -> if (request.path.endsWith("/message/")) {
            if (request.method == "POST") ready()
            else if (++gets == 1) jsonReply(JSONObject().put("status", "processing"))
            else jsonReply(JSONObject().put("status", "failed"))
        } else null }.use { api -> UiHarness(api, room(1, "재생")).use { ui ->
            open(ui); tap(ui); ui.await { ui.has("다시 확인하기") }
            assertFalse(api.paths().contains("/api/speech/"))
            ui.click("다시 확인하기"); ui.await { ui.has("설명 다시 준비하기") }
            ui.click("설명 다시 준비하기"); ui.await { playing(ui) }
            assertEquals(listOf("GET", "GET", "POST"), api.requests.filter { it.path.endsWith("/message/") }.map { it.method })
        } }
    }
    @Test fun summaryFailureOffersOriginalCaptionAndSpeechFailureCanRetry() {
        var speeches = 0
        server { request -> when {
            request.path.endsWith("/message/") -> jsonReply(JSONObject().put("error", "요약 서버 오류"), 503)
            request.path == "/api/speech/" && ++speeches == 1 -> jsonReply(JSONObject().put("error", "음성 서버 오류"), 503)
            else -> null
        } }.use { api -> UiHarness(api, room(1, "재생")).use { ui ->
            open(ui); tap(ui); ui.await { ui.has("요약 서버 오류") }
            ui.click("가족이 쓴 글 듣기"); ui.await { ui.has("음성 서버 오류") && ui.has("음성 다시 준비하기") }
            ui.click("음성 다시 준비하기"); ui.await { playing(ui) }
            assertTrue(api.requests.filter { it.path == "/api/speech/" }.all { JSONObject(it.body).getString("text") == "오늘의 소식 2" })
        } }
    }
    @Test fun unauthorizedSummaryShowsLoginRecovery() {
        server { request -> if (request.path.endsWith("/message/")) jsonReply(JSONObject().put("error", "만료"), 401) else null }
            .use { api -> UiHarness(api, room(1, "재생")).use { ui ->
                open(ui); tap(ui); ui.await { ui.has("다시 로그인") }
                assertFalse(api.paths().contains("/api/speech/"))
                ui.test.runOnMainSync { assertFalse(panels(ui)[0].isPlaying) }
            } }
    }
    @Test fun completionRestoresListeningMenuAction() {
        server { request -> if (request.path == "/api/speech/") audio(400) else null }
            .use { api -> UiHarness(api, room(1, "재생")).use { ui ->
                open(ui); tap(ui)
                ui.await { api.paths().contains("/api/speech/") && !panels(ui)[0].isPlaying }
                ui.test.runOnMainSync {
                    assertFalse(ui.has("재생을 마쳤어요."))
                    assertFalse(ui.has("소식을 재생하고 있어요. 다시 누르면 중지돼요."))
                    assertTrue(ui.has("사진과 글을 설명한 AI 요약"))
                }
                ui.test.runOnMainSync { assertFalse(playing(ui)); assertFalse(panels(ui)[0].isPlaying) }
                ui.test.runOnMainSync { ui.all().filterIsInstance<kr.talkdock.app.ui.FloatingAssistantView>().single().performClick() }
                ui.await { ui.has("음성으로 듣기") }
                ui.test.runOnMainSync { assertFalse(ui.has("듣기 중지")) }
            } }
    }
    @Test fun voiceNavigationCancelsPendingSpeechAndVoiceCancelReturnsToPost() {
        server { request -> if (request.path == "/api/speech/") { Thread.sleep(500); audio() } else null }
            .use { api -> UiHarness(api, room(1, "재생")).use { ui ->
                open(ui); tap(ui); ui.await { api.paths().contains("/api/speech/") }
                ui.test.runOnMainSync { ui.all().first { it.contentDescription == "말로 댓글 쓰기" }.performClick() }
                ui.await { ui.has("말로 답장") }
                ui.test.runOnMainSync { assertFalse(playing(ui)); ui.activity.onBackPressedDispatcher.onBackPressed() }
                ui.await { ui.hasPostDetail() }
            } }
    }
    @Test fun backgroundingCancelsLateSpeech() {
        server { request -> if (request.path == "/api/speech/") { Thread.sleep(500); audio() } else null }
            .use { api -> UiHarness(api, room(1, "재생")).use { ui ->
                open(ui); tap(ui); ui.await { api.paths().contains("/api/speech/") }
                ui.background()
                Thread.sleep(900)
                ui.test.runOnMainSync { assertFalse(playing(ui)); assertFalse(panels(ui)[0].isPlaying) }
            } }
    }
    private fun review(ui: UiHarness) {
        val draft = JSONObject().put("id", 55).put("recognized", "잘 먹었어").put("converted", "오늘 저녁을 맛있게 먹었어요.")
        ui.test.runOnMainSync {
            MainActivity::class.java.getDeclaredMethod("review", JSONObject::class.java, JSONObject::class.java)
                .apply { isAccessible = true }.invoke(ui.activity, post(1), draft)
        }
        ui.await { ui.has("답장 확인") }
    }
    @Test fun replyReviewUsesHeadingIconForPlaybackAndKeepsSendAndRerecord() {
        for (large in listOf(false, true)) server().use { api -> UiHarness(api, room(1, "재생"), large).use { ui ->
            open(ui); review(ui)
            ui.test.runOnMainSync {
                assertTrue(ui.has("가족에게 전할 댓글")); assertTrue(ui.has("가족에게 보내기")); assertTrue(ui.has("다시 말하기"))
                assertFalse(ui.has("취소하기")); assertFalse(ui.has("댓글 소리로 확인하기")); assertFalse(ui.has("듣기 중지"))
                val icon = ui.all().filterIsInstance<kr.talkdock.app.ui.ReplyAudioButton>().single()
                val heading = icon.parent as ViewGroup
                assertTrue(ui.all(heading).filterIsInstance<TextView>().any { it.text.toString() == "가족에게 전할 댓글" })
                icon.performClick()
            }
            ui.await { playing(ui) }
            ui.test.runOnMainSync { ui.all().filterIsInstance<kr.talkdock.app.ui.ReplyAudioButton>().single().performClick(); assertFalse(playing(ui)) }
            ui.screenshot("reply-review-icons.png")
            assertEquals("오늘 저녁을 맛있게 먹었어요.", JSONObject(api.requests.last { it.path == "/api/speech/" }.body).getString("text"))
            ui.click("다시 말하기"); ui.await { ui.has("말로 답장") }
        } }
    }
    @Test fun replyPreviewIgnoresLateSpeechAfterStopOrNavigation() {
        val releaseSpeech = List(3) { CountDownLatch(1) }
        var speechRequests = 0
        try {
            server { request -> if (request.path == "/api/speech/") {
                releaseSpeech[speechRequests++].await(15, TimeUnit.SECONDS)
                audio()
            } else null }.use { api -> UiHarness(api, room(1, "재생")).use { ui ->
                    open(ui); review(ui)
                    ui.test.runOnMainSync { ui.all().filterIsInstance<kr.talkdock.app.ui.ReplyAudioButton>().single().performClick() }
                    ui.await { api.paths().contains("/api/speech/") }
                    ui.test.runOnMainSync { ui.all().filterIsInstance<kr.talkdock.app.ui.ReplyAudioButton>().single().performClick() }
                    releaseSpeech[0].countDown()
                    Thread.sleep(750)
                    ui.test.runOnMainSync { assertFalse(playing(ui)) }
                    ui.test.runOnMainSync { ui.all().filterIsInstance<kr.talkdock.app.ui.ReplyAudioButton>().single().performClick() }
                    ui.await { api.paths().count { it == "/api/speech/" } == 2 }
                    ui.click("다시 말하기"); ui.await { ui.has("말로 답장") }
                    releaseSpeech[1].countDown()
                    Thread.sleep(750)
                    ui.test.runOnMainSync { assertFalse(playing(ui)) }
                    review(ui)
                    ui.test.runOnMainSync { ui.all().filterIsInstance<kr.talkdock.app.ui.ReplyAudioButton>().single().performClick() }
                    ui.await { api.paths().count { it == "/api/speech/" } == 3 }
                    ui.background()
                    releaseSpeech[2].countDown()
                    Thread.sleep(750)
                    ui.test.runOnMainSync { assertFalse(playing(ui)) }
                } }
        } finally { releaseSpeech.forEach { it.countDown() } }
    }
    @Test fun largeTextModeAndDigestOpenPostWithoutListeningScreen() {
        server().use { api -> UiHarness(api, room(1, "재생"), large = true).use { ui ->
            open(ui); tap(ui); ui.await { playing(ui) && panels(ui).single().isPlaying }
            tap(ui)
            ui.openDaily(); ui.await { ui.has("이날의 소식 1개") }
            ui.test.runOnMainSync { ui.all().first { it.contentDescription == "가족 1의 소식 보기" }.performClick() }; ui.await { ui.hasPostDetail() }
            ui.test.runOnMainSync { assertFalse(ui.has("가족 소식 듣기")) }
            tap(ui); ui.await { playing(ui) && panels(ui).single().isPlaying }
        } }
    }
}

@RunWith(AndroidJUnit4::class)
class CommentComposerTest {
    private fun post(comments: JSONArray = JSONArray()) = JSONObject().put("id", 1).put("author_name", "가족")
        .put("relationship", "자녀").put("caption", "댓글 테스트 소식").put("created_at", "2026-10-19T10:00:00+09:00")
        .put("comment_count", comments.length()).put("images", JSONArray()).put("comments", comments)
    private fun server(reply: (Request) -> Reply? = { null }): MockApi = MockApi { request ->
        reply(request) ?: when (request.path) {
            "/api/families/current/" -> jsonReply(room(1, "댓글 검증 가족"))
            "/api/posts/" -> jsonReply(JSONObject().put("posts", JSONArray().put(post())))
            "/api/posts/1/" -> jsonReply(post())
            else -> jsonReply(JSONObject())
        }
    }
    private fun composer(ui: UiHarness) = ui.all().filterIsInstance<kr.talkdock.app.ui.CommentComposer>()
        .single { it.input.contentDescription == "댓글 입력" }
    private fun open(ui: UiHarness, large: Boolean = false) {
        ui.await { ui.has("댓글 테스트 소식") }
        ui.click("댓글 테스트 소식")
        ui.await { ui.all().any { it is kr.talkdock.app.ui.CommentComposer } }
    }

    @Test fun sendIsInsideBottomRightAndBlankInputIsDisabledInBothSizes() {
        for (large in listOf(false, true)) server().use { api -> UiHarness(api, room(1, "댓글"), large).use { ui ->
            open(ui, large)
            ui.test.runOnMainSync {
                val c = composer(ui)
                assertFalse(ui.has("글로 댓글 보내기"))
                assertTrue(ui.all().any { it.contentDescription == "말로 댓글 쓰기" })
                assertEquals("댓글 보내기", c.sendButton.contentDescription)
                assertFalse(c.sendButton.isEnabled)
                c.input.setText("  \n  "); assertFalse(c.sendButton.isEnabled)
                c.input.setText("첫 줄\n둘째 줄"); assertTrue(c.sendButton.isEnabled)
                assertTrue(c.input.inputType and android.text.InputType.TYPE_TEXT_FLAG_MULTI_LINE != 0)
            }
            ui.await { composer(ui).sendButton.width > 0 && composer(ui).sendButton.left > 0 }
            ui.test.runOnMainSync {
                val c = composer(ui)
                val field = c.sendButton.parent as View
                assertTrue("Button stays inside the input container", c.sendButton.right < field.width && c.sendButton.bottom < field.height)
                assertTrue("Button is on the right half", c.sendButton.left > field.width / 2)
                assertTrue("Editor reserves space beside the button", c.input.right <= c.sendButton.left)
                assertTrue("Accessible touch target", c.sendButton.width >= (48 * c.resources.displayMetrics.density).toInt())
            }
        } }
    }

    @Test fun sendRemainsVisibleAboveKeyboard() {
        for (large in listOf(false, true)) server().use { api -> UiHarness(api, room(1, "댓글"), large).use { ui ->
            open(ui, large)
            ui.test.runOnMainSync {
                val c = composer(ui)
                c.input.setText("키보드 위에서도 보낼 수 있어요.")
                c.input.requestFocus()
                (ui.activity.getSystemService(Context.INPUT_METHOD_SERVICE) as android.view.inputmethod.InputMethodManager)
                    .showSoftInput(c.input, android.view.inputmethod.InputMethodManager.SHOW_IMPLICIT)
            }
            ui.await {
                val insets = androidx.core.view.ViewCompat.getRootWindowInsets(composer(ui))
                insets?.isVisible(androidx.core.view.WindowInsetsCompat.Type.ime()) == true
            }
            Thread.sleep(350)
            ui.screenshot("comment-keyboard.png")
            ui.test.runOnMainSync {
                val button = composer(ui).sendButton
                val visible = android.graphics.Rect()
                assertTrue("Send must remain visible with the keyboard open", button.getGlobalVisibleRect(visible))
                assertEquals("The full send touch target must be reachable", button.height, visible.height())
            }
            ui.screenshot("comment-keyboard.png")
        } }
    }
    @Test fun failedSendKeepsExactDraftAndRetryPublishesItOnce() {
        val draft = "  오늘도 고마워요!\n내일 또 만나요 😊  "
        var attempts = 0
        val comments = JSONArray()
        server { request -> when {
            request.path == "/api/posts/1/comments/" -> {
                Thread.sleep(400)
                if (++attempts == 1) jsonReply(JSONObject().put("error", "테스트 전송 실패"), 503)
                else {
                    comments.put(JSONObject().put("id", 1).put("author_name", "나").put("relationship", "나")
                        .put("text", JSONObject(request.body).getString("text")))
                    jsonReply(JSONObject().put("id", 1), 201)
                }
            }
            request.path == "/api/posts/1/" -> jsonReply(post(comments))
            else -> null
        } }.use { api -> UiHarness(api, room(1, "댓글")).use { ui ->
            open(ui)
            ui.test.runOnMainSync { composer(ui).input.setText(draft); composer(ui).sendButton.performClick() }
            ui.await { api.paths().contains("/api/posts/1/comments/") }
            ui.test.runOnMainSync {
                val c = composer(ui)
                assertFalse(c.sendButton.isEnabled); assertFalse(c.input.isEnabled)
                assertTrue(ui.all().filterIsInstance<android.widget.ProgressBar>().any { it.visibility == View.VISIBLE })
                assertFalse(ui.all().any { it is kr.talkdock.app.ui.TodakWaitingView })
                c.sendButton.performClick() // Even a forced second click cannot enqueue another POST.
            }
            ui.await { ui.has("테스트 전송 실패") }
            ui.test.runOnMainSync {
                val c = composer(ui)
                assertEquals(draft, c.input.text.toString())
                assertTrue(c.input.isEnabled); assertTrue(c.sendButton.isEnabled)
                c.requestRectangleOnScreen(android.graphics.Rect(0, 0, c.width, c.height), true)
            }
            ui.screenshot("comment-send-failure.png")
            assertEquals(1, api.paths().count { it == "/api/posts/1/comments/" })
            ui.test.runOnMainSync { composer(ui).sendButton.performClick() }
            ui.await { ui.has("댓글을 달았어요!") }
            ui.test.runOnMainSync { assertEquals("", composer(ui).input.text.toString()) }
            ui.await { ui.has(draft) && ui.has("댓글 1") }
            ui.test.runOnMainSync { assertEquals("", composer(ui).input.text.toString()); assertFalse(composer(ui).sendButton.isEnabled) }
            val sends = api.requests.filter { it.path == "/api/posts/1/comments/" }
            assertEquals(2, sends.size)
            assertTrue(sends.all { JSONObject(it.body).getString("text") == draft })
        } }
    }

    @Test fun validationAndExpiredLoginFailuresAlsoKeepDraftEditable() {
        for (code in listOf(400, 401)) server { request ->
            if (request.path == "/api/posts/1/comments/") jsonReply(JSONObject().put("error", "서버에서 거절했어요"), code) else null
        }.use { api -> UiHarness(api, room(1, "댓글")).use { ui ->
            open(ui)
            ui.test.runOnMainSync { composer(ui).input.setText("보존할 댓글"); composer(ui).sendButton.performClick() }
            ui.await { ui.has(if (code == 401) "로그인이 만료되었어요. 작성한 댓글은 유지돼요. 다시 로그인해 주세요." else "서버에서 거절했어요") }
            ui.test.runOnMainSync {
                assertEquals("보존할 댓글", composer(ui).input.text.toString())
                assertTrue(composer(ui).input.isEnabled); assertTrue(composer(ui).sendButton.isEnabled)
                composer(ui).input.append(" 수정"); assertEquals("보존할 댓글 수정", composer(ui).input.text.toString())
            }
        } }
    }
}

@RunWith(AndroidJUnit4::class)
class PostQuestionUiTest {
    private fun post(id: Int, created: String = "2026-10-19T${if (id == 1) "10" else "11"}:00:00+09:00") = JSONObject()
        .put("id", id).put("author_name", "가족 $id").put("relationship", "자녀").put("caption", "질문 테스트 소식 $id")
        .put("created_at", created).put("comment_count", 0).put("images", JSONArray()).put("comments", JSONArray())
    private fun server(custom: (Request) -> Reply? = { null }): MockApi = MockApi { request ->
        custom(request) ?: when (request.path) {
            "/api/families/current/" -> jsonReply(room(1, "질문 검증 가족"))
            "/api/posts/" -> jsonReply(JSONObject().put("posts", JSONArray().put(post(1)).put(post(2))))
            "/api/posts/1/" -> jsonReply(post(1))
            "/api/posts/2/" -> jsonReply(post(2))
            "/api/posts/1/questions/", "/api/posts/2/questions/" -> jsonReply(JSONObject().put("text", "가족 기록으로 확인한 답변이에요."))
            else -> jsonReply(JSONObject())
        }
    }
    private fun panel(ui: UiHarness) = ui.all().filterIsInstance<kr.talkdock.app.ui.PostQuestionPanel>().single()
    private fun open(ui: UiHarness, id: Int = 2) {
        if (ui.all().any { it is kr.talkdock.app.ui.PostQuestionPanel }) {
            ui.test.runOnMainSync { ui.activity.onBackPressedDispatcher.onBackPressed() }
            ui.await { ui.all().none { it is kr.talkdock.app.ui.PostQuestionPanel } }
        }
        ui.selectLetter(id); ui.openAssistantOption("이 소식 물어보기")
        ui.await { ui.all().filterIsInstance<kr.talkdock.app.ui.PostQuestionPanel>().singleOrNull()?.composer?.isShown == true }
    }
    private fun ask(ui: UiHarness, text: String) = ui.test.runOnMainSync {
        panel(ui).composer.input.setText(text); panel(ui).composer.sendButton.performClick()
    }

    @Test fun feedIsNewestFirstWithTimezonesAndTimestampTiesInBothSizes() {
        for (large in listOf(false, true)) server { request -> if (request.path == "/api/posts/") {
            val items = JSONArray().put(post(100, "2026-10-19T10:00:00+09:00"))
                .put(post(1, "2026-10-19T02:00:00Z")).put(post(999, "unknown"))
                .put(post(3, "2026-10-19T10:30:00+09:00")).put(post(2, "2026-10-19T11:00:00+09:00"))
            jsonReply(JSONObject().put("posts", items))
        } else null }.use { api -> UiHarness(api, room(1, "질문"), large).use { ui ->
            ui.await { ui.all().any { it is kr.talkdock.app.ui.PhotoLetterDeck } }
            ui.test.runOnMainSync {
                val deck = ui.all().filterIsInstance<kr.talkdock.app.ui.PhotoLetterDeck>().single()
                val ids = (0 until deck.letterCount).map { index -> deck.show(index); deck.currentPost.getInt("id") }
                assertEquals(listOf(2, 1, 3, 100, 999), ids)
            }
        } }
    }

    @Test fun feedEntryAsksTheCorrectPostAndShowsAnswerWithoutPostingAComment() {
        for (large in listOf(false, true)) server().use { api -> UiHarness(api, room(1, "질문"), large).use { ui ->
            open(ui)
            ui.test.runOnMainSync { assertFalse(panel(ui).composer.sendButton.isEnabled) }
            ask(ui, "모모는 누구예요?")
            ui.await { ui.has("가족 기록으로 확인한 답변이에요.") }
            ui.test.runOnMainSync {
                assertEquals("", panel(ui).composer.input.text.toString())
                assertTrue(ui.all().any { it.contentDescription == "도우미 닫기" }); assertFalse(ui.has("추가 질문 닫기"))
                assertTrue(ui.has("모모는 누구예요?")); assertTrue(ui.has("가족 기록으로 확인한 답변이에요."))
                assertTrue(ui.has("말로 답장하기"))
                assertEquals(1000, panel(ui).composer.input.filters.filterIsInstance<android.text.InputFilter.LengthFilter>().single().max)
                panel(ui).requestRectangleOnScreen(android.graphics.Rect(0, 0, panel(ui).width, panel(ui).height), true)
            }
            ui.screenshot("post-question-answer.png")
            ui.click("닫기")
            ui.test.runOnMainSync { assertFalse(panel(ui).composer.isShown); assertTrue(ui.has("궁금한 점을 물어보세요")) }
            val request = api.requests.single { it.path.endsWith("/questions/") }
            assertEquals("/api/posts/2/questions/", request.path); assertEquals("POST", request.method)
            val body = JSONObject(request.body)
            assertEquals("모모는 누구예요?", body.getString("question")); assertEquals(0, body.getJSONArray("prior_dialogue").length())
            assertFalse(api.paths().any { it.endsWith("/comments/") })
        } }
    }

    @Test fun followupsSendOnlyTheLatestTenBoundedMessages() {
        val longAnswer = "긴 답변" + "가".repeat(1100)
        server { request -> if (request.path.endsWith("/questions/")) {
            val q = JSONObject(request.body).getString("question")
            jsonReply(JSONObject().put("text", if (q == "질문0") longAnswer else "답변:$q"))
        } else null }.use { api -> UiHarness(api, room(1, "질문")).use { ui ->
            open(ui)
            for (index in 0..6) {
                ask(ui, "질문$index")
                ui.await { ui.has(if (index == 0) longAnswer else "답변:질문$index") && panel(ui).composer.input.isEnabled }
            }
            val requests = api.requests.filter { it.path.endsWith("/questions/") }.map { JSONObject(it.body) }
            assertEquals(7, requests.size)
            assertEquals(1000, requests[1].getJSONArray("prior_dialogue").getJSONObject(1).getString("text").length)
            val prior = requests.last().getJSONArray("prior_dialogue")
            assertEquals(10, prior.length())
            for (index in 0 until 5) {
                assertEquals("user", prior.getJSONObject(index * 2).getString("role"))
                assertEquals("질문${index + 1}", prior.getJSONObject(index * 2).getString("text"))
                assertEquals("assistant", prior.getJSONObject(index * 2 + 1).getString("role"))
            }
        } }
    }

    @Test fun failedQuestionKeepsDraftAndCanRetryWithoutDuplicatesOrFailedHistory() {
        var count = 0
        server { request -> if (request.path.endsWith("/questions/")) {
            Thread.sleep(400)
            if (++count == 1) jsonReply(JSONObject().put("error", "질문 테스트 오류"), 503)
            else jsonReply(JSONObject().put("text", "다시 확인한 답변"))
        } else null }.use { api -> UiHarness(api, room(1, "질문")).use { ui ->
            open(ui); ask(ui, "그 카페는 어디예요?")
            ui.await { api.paths().any { it.endsWith("/questions/") } }
            ui.test.runOnMainSync {
                assertFalse(panel(ui).composer.sendButton.isEnabled)
                assertFalse(ui.all().any { it is kr.talkdock.app.ui.TodakWaitingView })
                assertTrue("AI requests must not add a page-wide wait overlay", ui.all().none { it is kr.talkdock.app.ui.TodakWaitingView })
                panel(ui).composer.sendButton.performClick()
            }
            ui.await { ui.has("질문 테스트 오류") }
            ui.test.runOnMainSync { assertEquals("그 카페는 어디예요?", panel(ui).composer.input.text.toString()) }
            ask(ui, "그 카페는 어디예요?"); ui.await { ui.has("다시 확인한 답변") }
            val requests = api.requests.filter { it.path.endsWith("/questions/") }
            assertEquals(2, requests.size)
            assertTrue(requests.all { JSONObject(it.body).getJSONArray("prior_dialogue").length() == 0 })
        } }
    }

    @Test fun leavingPendingQuestionDoesNotShowLateAnswerOrLeakConversationToAnotherPost() {
        server { request -> if (request.path == "/api/posts/2/questions/") {
            Thread.sleep(600); jsonReply(JSONObject().put("text", "이전 글에만 해당하는 답변"))
        } else null }.use { api -> UiHarness(api, room(1, "질문")).use { ui ->
            open(ui); ask(ui, "누구예요?")
            ui.await { api.paths().contains("/api/posts/2/questions/") }
            ui.test.runOnMainSync { ui.activity.onBackPressedDispatcher.onBackPressed() }
            ui.await { ui.all().none { it is kr.talkdock.app.ui.PostQuestionPanel } }
            open(ui, 1)
            ui.test.runOnMainSync { assertFalse(ui.has("이전 글에만 해당하는 답변")) }
            ask(ui, "여기는 어디예요?"); ui.await { ui.has("가족 기록으로 확인한 답변이에요.") }
            val request = api.requests.last { it.path == "/api/posts/1/questions/" }
            assertEquals(0, JSONObject(request.body).getJSONArray("prior_dialogue").length())
        } }
    }
}
