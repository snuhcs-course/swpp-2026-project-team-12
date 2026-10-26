package kr.talkdock.app

import android.Manifest
import android.app.Activity
import android.app.AlertDialog
import android.app.Dialog
import android.app.TimePickerDialog
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Color
import android.net.Uri
import android.os.Bundle
import android.provider.MediaStore
import android.view.Gravity
import android.view.View
import android.view.WindowInsets
import android.view.inputmethod.InputMethodManager
import android.widget.*
import androidx.core.content.FileProvider
import androidx.activity.ComponentActivity
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout
import kr.talkdock.app.data.*
import kr.talkdock.app.device.Recorder
import kr.talkdock.app.device.Speaker
import kr.talkdock.app.ui.IconView
import kr.talkdock.app.ui.CommentComposer
import kr.talkdock.app.ui.PostQuestionPanel
import kr.talkdock.app.ui.FamilyMemoryPanel
import kr.talkdock.app.ui.ReplyAudioButton
import kr.talkdock.app.ui.InlinePostAudio
import kr.talkdock.app.ui.Ui
import kr.talkdock.app.ui.FamilyTreeView
import kr.talkdock.app.ui.PhotoPickerActivity
import kr.talkdock.app.ui.PhotoCarousel
import kr.talkdock.app.ui.ViewportPhotoLoader
import kr.talkdock.app.ui.DraftPhotoStrip
import kr.talkdock.app.ui.TodakArtView
import kr.talkdock.app.ui.TodakWaitingView
import kr.talkdock.app.ui.TodakSuccessView
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.time.LocalDate
import java.time.ZoneId
import java.time.OffsetDateTime
import java.time.format.DateTimeFormatter
import java.util.concurrent.Executors

/** One activity owns navigation; all remote work runs away from the UI thread. */
class MainActivity : ComponentActivity() {
    private lateinit var ui: Ui
    private lateinit var sessions: SessionStore
    private lateinit var root: FrameLayout
    private lateinit var page: LinearLayout
    private lateinit var content: LinearLayout
    private lateinit var speaker: Speaker
    private var recorder: Recorder? = null
    private var recording: File? = null
    private val network = Executors.newSingleThreadExecutor()
    // Slow AI explanations must not queue ordinary comment requests behind them.
    private val summaries = Executors.newFixedThreadPool(2)
    private val questions = Executors.newFixedThreadPool(2)
    private var activePostAudio: InlinePostAudio? = null
    private var replyPreview: ReplyAudioButton? = null
    private var memoryPanel: FamilyMemoryPanel? = null
    private lateinit var imageLoader: ViewportPhotoLoader
    private var session: JSONObject? = null
    private var room = JSONObject()
    private var screen = "welcome"
    private var pageNumber = 0
    private var busy = false
    private var foreground = false
    private var selectedPost: JSONObject? = null
    private var photo: File? = null
    private val extraPhotos = mutableListOf<File>()
    private var pendingPhoto: File? = null
    private var caption = ""
    private var captionInput: EditText? = null
    private var draftPhotoIndex = 0
    private var recognized = ""
    private var voiceFromDetail = false
    private var voiceStatus: TextView? = null
    private var voiceText: TextView? = null
    private var voiceButton: Button? = null
    private var joinRoom = JSONObject()
    private var invitation = JSONObject()
    private var treeDraft: FamilyTreeDraft? = null
    private var digestDate = LocalDate.now(ZoneId.of("Asia/Seoul")).toString()
    private var currentBack: (() -> Unit)? = null
    private val large get() = session?.optBoolean("large", false) ?: false
    private val api get() = ApiClient(session?.optString("token", "") ?: "", sessions.serverUrl(),
        room.optInt("id").takeIf { room.has("id") })
    private val cameraCode = 10
    private val microphoneCode = 12
    private val photoPicker = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode != Activity.RESULT_OK) return@registerForActivityResult
        val uris = result.data?.getStringArrayListExtra(PhotoPickerActivity.RESULT_URIS)
            .orEmpty().map { Uri.parse(it) }.distinct()
        if (uris.isEmpty()) return@registerForActivityResult
        // Preserve the gallery's tap order all the way through multipart upload.
        if (uris.size > 5) {
            toast("사진은 한 번에 5장까지 선택해 주세요.")
            return@registerForActivityResult
        }
        async({ copyGalleryPhotos(uris) }, "선택한 사진을 확인하고 있어요.") { files ->
            selectedPhotos().forEach { it.delete() }
            photo = files.first(); extraPhotos.clear(); extraPhotos.addAll(files.drop(1)); draftPhotoIndex = 0; composer()
        }
    }

    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        ui = Ui(this); sessions = SessionStore(this); session = sessions.current()
        session?.optJSONObject("room")?.let { room = it }
        root = FrameLayout(this).apply { setBackgroundColor(ui.milk) }
        setContentView(root)
        imageLoader = ViewportPhotoLoader(root)
        if (android.os.Build.VERSION.SDK_INT >= 30) {
            root.setOnApplyWindowInsetsListener { view, insets ->
                val safe = insets.getInsets(WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout())
                val keyboard = insets.getInsets(WindowInsets.Type.ime())
                view.setPadding(safe.left, safe.top, safe.right, maxOf(safe.bottom, keyboard.bottom))
                insets
            }
        } else {
            root.fitsSystemWindows = true
        }
        speaker = Speaker { toast(it) }
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (busy) { toast("잠시만 기다려 주세요."); return }
                currentBack?.invoke() ?: finish()
            }
        })
        photo = state?.getString("photo")?.let { File(it) }?.takeIf { it.exists() }
        extraPhotos.addAll(state?.getStringArrayList("extraPhotos").orEmpty().map { File(it) }.filter { it.exists() })
        pendingPhoto = state?.getString("pendingPhoto")?.let { File(it) }
        caption = state?.getString("caption", "") ?: ""
        draftPhotoIndex = state?.getInt("draftPhotoIndex") ?: 0
        selectedPost = state?.getString("post")?.let { JSONObject(it) }
        val restoredScreen = state?.getString("screen")
        if (restoredScreen in listOf("tree", "profile") && state?.getString("joinRoom") != null) {
            joinRoom = JSONObject(state.getString("joinRoom")!!)
            invitation = JSONObject(state.getString("invitation")!!)
            treeDraft = FamilyTreeDraft(joinRoom.getJSONObject("tree")).apply {
                state.getString("treeDraft")?.let { restore(JSONObject(it)) }
            }
        }
        fun restoreScreen() {
            if (treeDraft != null) {
                if (restoredScreen == "tree") { tree(); return }
                if (restoredScreen == "profile" && treeDraft?.selectedId != null) { profile(); return }
            }
            if (!room.has("id")) { clearPhotoDraft(); selectedPost = null; roomChoice(); return }
            when {
            restoredScreen == "memories" -> familyMemories(state?.getBundle("memories")?.takeIf {
                it.getInt("userId", -1) == session?.optInt("user_id") &&
                    it.getInt("roomId", -1) == room.optInt("id", -1) && it.getString("server") == sessions.serverUrl()
            })
            restoredScreen == "familyTree" -> familyTree()
            restoredScreen == "post" || restoredScreen == "camera" -> composer()
            restoredScreen == "detail" && selectedPost != null -> detail(selectedPost!!)
            restoredScreen == "senior" && selectedPost != null -> detail(selectedPost!!)
            session != null && session?.optJSONObject("room") != null -> home()
            session != null -> roomChoice()
            else -> welcome()
            }
        }
        val savedAccount = session
        if (savedAccount == null) welcome()
        else {
            val previousRoom = room.optInt("id", -1)
            val big = large
            navigation("가족방 확인", name = "roomSync")
            async({ loadRoom(JSONObject(savedAccount.toString())) }, "가족방을 확인하고 있어요.") { current ->
                saveSession(current, big)
                if (previousRoom != room.optInt("id", -1)) {
                    clearPhotoDraft(); selectedPost = null
                    if (room.has("id")) home() else roomChoice()
                } else restoreScreen()
            }
        }
    }
    override fun onSaveInstanceState(out: Bundle) {
        super.onSaveInstanceState(out)
        out.putString("screen", screen); out.putString("photo", photo?.absolutePath)
        out.putStringArrayList("extraPhotos", ArrayList(extraPhotos.map { it.absolutePath }))
        out.putString("pendingPhoto", pendingPhoto?.absolutePath)
        out.putString("caption", captionInput?.text?.toString() ?: caption)
        out.putInt("draftPhotoIndex", draftPhotoIndex)
        out.putString("post", selectedPost?.toString())
        if (screen == "memories") out.putBundle("memories", memoryPanel?.snapshot()?.apply {
            putInt("userId", session?.optInt("user_id") ?: -1)
            putInt("roomId", room.optInt("id", -1)); putString("server", sessions.serverUrl())
        })
        if (screen in listOf("tree", "profile")) {
            out.putString("joinRoom", joinRoom.toString()); out.putString("invitation", invitation.toString())
            out.putString("treeDraft", treeDraft?.payload()?.toString())
        }
    }
    override fun onResume() { super.onResume(); foreground = true }
    override fun onPause() {
        foreground = false
        if (recorder?.active == true) {
            voiceButton?.text = "말하기 시작"
            voiceStatus?.text = "녹음이 중단됐어요. 다시 말하기 시작을 눌러 주세요."
        }
        super.onPause(); stopPostAudio(); replyPreview?.stop(); speaker.stop(); recorder?.cancel()
    }
    override fun onDestroy() {
        stopPostAudio(); replyPreview?.stop(); summaries.shutdownNow(); questions.shutdownNow()
        speaker.close(); recorder?.close(); recording?.delete(); network.shutdownNow(); imageLoader.close()
        super.onDestroy()
    }
    private fun toast(message: String) = Toast.makeText(this, message, Toast.LENGTH_LONG).show()
    private fun json(vararg pairs: Pair<String, Any>) = JSONObject().apply { pairs.forEach { put(it.first, it.second) } }
    private fun objects(array: JSONArray): List<JSONObject> = (0 until array.length()).map { array.getJSONObject(it) }
    private fun navigation(title: String, back: (() -> Unit)? = null, tab: Int? = null, name: String) {
        stopPostAudio(); replyPreview?.stop(); replyPreview = null
        screen = name; pageNumber++; captionInput = null; currentBack = back
        voiceButton = null
        speaker.stop(); recorder?.close(); recorder = null
        recording?.delete(); recording = null
        (getSystemService(INPUT_METHOD_SERVICE) as InputMethodManager).hideSoftInputFromWindow(root.windowToken, 0)
        imageLoader.clearViews()
        root.removeAllViews()
        memoryPanel = null
        page = ui.column(); root.addView(page, FrameLayout.LayoutParams(-1, -1))
        val header = ui.row().apply { setPadding(ui.dp(16), ui.dp(10), ui.dp(16), ui.dp(10)); minimumHeight = ui.dp(72) }
        if (back != null) header.addView(ui.iconButton("back", "이전 화면") { back() })
        header.addView(ui.text(title, if (back == null) 26f else 20f, true), LinearLayout.LayoutParams(0, -2, 1f))
        if (tab == 0) {
            header.addView(ui.iconButton("refresh", "가족 소식 새로고침") { home() })
            header.addView(ui.iconButton("write", "가족 소식 작성하기") { composer() })
        }
        if (name != "welcome") page.addView(header)
        val scroll = ScrollView(this).apply { isFillViewport = true; clipToPadding = false }
        content = ui.column().apply { setPadding(ui.dp(24), ui.dp(12), ui.dp(24), ui.dp(30)) }
        scroll.addView(content)
        val body = if (name == "home") {
            SwipeRefreshLayout(this).apply {
                setColorSchemeColors(ui.coralDeep)
                setProgressBackgroundColorSchemeColor(ui.milk)
                addView(scroll, FrameLayout.LayoutParams(-1, -1))
                setOnChildScrollUpCallback { _, _ -> busy || scroll.canScrollVertically(-1) }
                setOnRefreshListener { home(this) }
            }
        } else scroll
        page.addView(body, LinearLayout.LayoutParams(-1, 0, 1f))
        if (tab != null) bottomBar(tab)
    }
    private fun bottomBar(selected: Int) {
        ui.line(page)
        val row = ui.row().apply {
            setBackgroundColor(ui.paper); setPadding(ui.dp(12), ui.dp(4), ui.dp(12), ui.dp(8))
        }
        val titles = listOf("소식", "가족방", "설정")
        val symbols = listOf("home", "family", "settings")
        titles.forEachIndexed { i, title ->
            val item = ui.column(8).apply {
                gravity = Gravity.CENTER; minimumHeight = ui.dp(if (large) 80 else 68)
                background = ui.shape(if (selected == i) ui.blush else ui.paper)
                isClickable = true; isFocusable = true; isSelected = selected == i; contentDescription = title
                setOnClickListener { when (i) { 0 -> home(); 1 -> roomChoice(); else -> members() } }
            }
            item.addView(IconView(this, symbols[i], if (selected == i) ui.coralDeep else ui.muted),
                LinearLayout.LayoutParams(ui.dp(24), ui.dp(24)))
            ui.gap(item, 4)
            item.addView(ui.text(title, if (large) 17f else 14f, selected == i,
                if (selected == i) ui.coralDeep else ui.muted).apply { gravity = Gravity.CENTER })
            row.addView(item, LinearLayout.LayoutParams(0, -2, 1f))
        }
        page.addView(row)
    }
    private fun heading(text: String, sub: String? = null) {
        ui.label(content, text, if (large) 30f else 26f, true); ui.gap(content, 12)
        if (sub != null) { ui.label(content, sub, if (large) 21f else 17f, color = ui.muted); ui.gap(content, 24) }
    }
    private fun <T> async(work: () -> T, message: String = "잠시만 기다려 주세요.", refresh: SwipeRefreshLayout? = null, showLoading: Boolean = true, failure: ((Throwable) -> Boolean)? = null, complete: (T) -> Unit) {
        if (busy) { refresh?.isRefreshing = false; return }
        busy = true
        val number = pageNumber
        val cover = if (refresh == null && showLoading) TodakWaitingView(this, message) else null
        if (cover != null) root.addView(cover, FrameLayout.LayoutParams(-1, -1))
        refresh?.isRefreshing = true
        network.execute {
            val result = runCatching { work() }
            runOnUiThread {
                busy = false
                if (cover != null) root.removeView(cover)
                refresh?.isRefreshing = false
                if (isDestroyed || number != pageNumber) return@runOnUiThread
                result.fold({ complete(it) }, { error ->
                    if (failure?.invoke(error) == true) return@runOnUiThread
                    if (error is ApiException && error.status == 401 && screen !in listOf("login", "register")) {
                        val username = session?.optString("username").orEmpty()
                        val userId = session?.optInt("user_id")
                        val big = large
                        sessions.removeCurrent(); session = null; room = JSONObject(); imageLoader.clear()
                        login(username, userId, big)
                        AlertDialog.Builder(this).setTitle("로그인이 만료되었어요")
                            .setMessage("비밀번호를 입력해 다시 로그인해 주세요.")
                            .setPositiveButton("확인", null).show()
                    } else {
                        val message = (error as? ApiException)?.message ?: "서버에 연결하지 못했어요. 인터넷 연결을 확인하고 다시 시도해 주세요."
                        if (screen == "home" && refresh == null) { feedError(message); return@runOnUiThread }
                        if (screen == "roomSync") {
                            content.removeAllViews()
                            ui.art(content, "grandchild_sad", 180); ui.gap(content, 20)
                            heading("잠시 이용이 어려워요", message)
                            ui.button(content, "다시 연결하기") { recreate() }
                            return@runOnUiThread
                        }
                        val title = if (error is ApiException && (error.status in 500..599 || error.cause is java.io.IOException))
                            "잠시 이용이 어려워요" else "다시 확인해 주세요"
                        AlertDialog.Builder(this).setTitle(title).setMessage(message)
                            .setPositiveButton("확인", null).show()
                    }
                })
            }
        }
    }
    private fun postingSuccess(message: String, complete: () -> Unit) {
        busy = true
        val number = pageNumber
        lateinit var cover: TodakSuccessView
        cover = TodakSuccessView(this, message) {
            root.removeView(cover)
            busy = false
            if (!isDestroyed && number == pageNumber) complete()
        }
        root.addView(cover, FrameLayout.LayoutParams(-1, -1))
    }
    private fun listen(parent: LinearLayout, text: String, label: String, height: Int) {
        ui.button(parent, label, height = height) {
            val client = api
            speaker.stop()
            async({ client.speech(text) }, "소리를 준비하고 있어요.") { bytes ->
                if (!foreground) return@async
                val file = File.createTempFile("listen-", ".mp3", cacheDir)
                runCatching { file.writeBytes(bytes); speaker.play(file) }.onFailure { file.delete(); toast("소리를 재생하지 못했어요.") }
            }
        }
        ui.button(parent, "듣기 중지", false, height) { speaker.stop() }
    }
    private fun connectionSettings() {
        val input = EditText(this).apply { setText(sessions.serverUrl()); inputType = android.text.InputType.TYPE_CLASS_TEXT or android.text.InputType.TYPE_TEXT_VARIATION_URI }
        val dialog = AlertDialog.Builder(this).setTitle("테스트 서버 연결")
            .setMessage("팀원이 안내한 주소를 입력해 주세요. 서버를 바꾸면 이 휴대폰에서 다시 로그인해야 해요.")
            .setView(input).setPositiveButton("연결", null).setNegativeButton("취소", null).create()
        dialog.setOnShowListener {
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
                val raw = input.text.toString().trim().trimEnd('/')
                val url = if (raw.endsWith("/api")) raw + "/" else raw + "/api/"
                val parsed = runCatching { java.net.URI(url) }.getOrNull()
                if (parsed == null || parsed.scheme !in listOf("http", "https") || parsed.host.isNullOrBlank() ||
                    parsed.rawUserInfo != null || parsed.rawQuery != null || parsed.rawFragment != null || parsed.path != "/api/") {
                    input.error = "예: http://192.168.0.10:8000/api/"; return@setOnClickListener
                }
                sessions.changeServer(url); session = sessions.current(); room = session?.optJSONObject("room") ?: JSONObject()
                imageLoader.clear(); dialog.dismiss()
                if (session == null) welcome() else if (room.has("id")) members() else roomChoice()
            }
        }
        dialog.show()
    }
    private fun remotePhoto(view: ImageView, post: JSONObject, url: String = post.getString("image_url"), thumbnail: Boolean = false) {
        view.contentDescription = post.optString("author_name") + "님의 사진"
        imageLoader.bind(view, api, url, thumbnail)
    }
    private fun saveSession(value: JSONObject, big: Boolean) {
        sessions.save(value, big); session = value; room = value.optJSONObject("room") ?: JSONObject()
        imageLoader.clear()
    }
    private fun saveRoom(value: JSONObject, big: Boolean = large, complete: () -> Unit) {
        // Switch to the room just created or joined.
        val account = JSONObject((session ?: return).toString()).put("room", value.getJSONObject("room"))
        val expected = value.getJSONObject("room").getInt("id")
        val previous = room.optInt("id", -1)
        async({ loadRoom(account) }, "가족방을 확인하고 있어요.") { current ->
            saveSession(current, big)
            if (previous != room.optInt("id", -1)) resetRoomState()
            if (room.optInt("id", -1) == expected) complete()
            else {
                if (room.has("id")) home() else roomChoice()
                AlertDialog.Builder(this).setTitle("가족방을 다시 확인했어요")
                    .setMessage("서버에서 확인한 현재 가족방을 사용해요. 다른 가족방으로 소식을 보내지 않았어요.")
                    .setPositiveButton("확인", null).show()
            }
        }
    }
    /** Drafts, the open post and the digest date belong to one room, so drop them when switching. */
    private fun resetRoomState() {
        clearPhotoDraft(); selectedPost = null
        digestDate = LocalDate.now(ZoneId.of("Asia/Seoul")).toString()
    }
    /**
     * Keeps the account's saved room while it is still joined, or opens the only joined room.
     * With several rooms and no saved choice the account is left without a room for [roomChoice].
     */
    private fun loadRoom(account: JSONObject): JSONObject {
        val token = account.getString("token")
        val rooms = objects(ApiClient(token, sessions.serverUrl()).request("families/").getJSONArray("rooms"))
        val saved = account.optJSONObject("room")?.optInt("id", -1)
        val chosen = rooms.firstOrNull { it.getInt("id") == saved } ?: rooms.singleOrNull()
        val currentRoom = chosen?.let {
            try { ApiClient(token, sessions.serverUrl(), it.getInt("id")).request("families/current/") }
            catch (error: ApiException) { if (error.status == 403) null else throw error }
        }
        account.remove("room")
        if (currentRoom != null) account.put("room", currentRoom)
        return account
    }
    private fun roomChoice() {
        val inRoom = room.has("id")
        navigation("우리 가족방", if (inRoom) null else ({ welcome() }), tab = if (inRoom) 1 else null, name = "roomChoice")
        val client = api
        async({ objects(client.request("families/").getJSONArray("rooms")) }, "가족방을 불러오고 있어요.", failure = {
            ui.ghost(content, "가족방 다시 불러오기") { roomChoice() }; false
        }) { rooms ->
            ui.label(content, "나를 반기는 작은 공간", 14f, color = ui.muted); ui.gap(content, 16)
            heading("오늘은 누구의 하루가\n궁금한가요?", when {
                rooms.isEmpty() -> "가족방을 만들거나 초대 코드로 참여해 주세요."
                inRoom -> "다른 가족방을 누르면 그 가족의 소식으로 바뀌어요."
                else -> "들어갈 가족방을 골라 주세요."
            })
            rooms.forEach { roomCard(it); ui.gap(content, 12) }
            if (room.has("id")) { ui.button(content, "가족 추억 찾기", false, if (large) 76 else 56) { familyMemories() }; ui.gap(content, 12) }
            if (rooms.isNotEmpty()) ui.gap(content, 8)
            ui.button(content, "새 가족방 만들기", height = if (large) 76 else 56) { create() }
            ui.button(content, "초대 코드로 참여하기", false, if (large) 76 else 56) { join() }
            ui.gap(content)
            if (!inRoom) {
                ui.ghost(content, "내 계정 수정") { editAccount() }
                ui.ghost(content, "다른 계정으로 로그인") { login() }
            }
            if (BuildConfig.DEBUG) ui.ghost(content, "테스트 연결 설정") { connectionSettings() }
        }
    }
    private fun roomCard(item: JSONObject) {
        val current = item.getInt("id") == room.optInt("id", -1)
        val name = item.getString("name")
        val card = ui.card(content).apply {
            // A white card keeps the illustration's white background seamless; the current room gets a coral outline.
            if (current) background = ui.shape(ui.paper, 20).apply { setStroke(ui.dp(2), ui.coralDeep) }
            isClickable = true; isFocusable = true
            contentDescription = if (current) "$name, 지금 보고 있는 가족방" else "$name 가족방으로 이동"
            setOnClickListener { enterRoom(item.getInt("id")) }
        }
        val intro = ui.row().apply { minimumHeight = ui.dp(if (large) 96 else 80) }
        intro.addView(TodakArtView(this, "grandmother", 56), LinearLayout.LayoutParams(ui.dp(56), ui.dp(67)))
        val labels = ui.column().apply { setPadding(ui.dp(12), 0, ui.dp(8), 0) }
        if (current) { ui.label(labels, "지금 보는 가족방", if (large) 17f else 14f, true, ui.coralDeep); ui.gap(labels, 4) }
        ui.label(labels, name, if (large) 26f else 22f, true)
        val details = listOfNotNull("내가 만든 방".takeIf { item.optBoolean("is_owner") }, "${item.optInt("member_count")}명")
        ui.label(labels, details.joinToString(" · "), if (large) 19f else 15f, color = ui.muted)
        intro.addView(labels, LinearLayout.LayoutParams(0, -2, 1f))
        intro.addView(IconView(this, "next", if (current) ui.coralDeep else ui.ink), LinearLayout.LayoutParams(ui.dp(24), ui.dp(24)))
        card.addView(intro)
    }
    private fun enterRoom(id: Int) {
        if (room.optInt("id", -1) == id) return home()
        val account = JSONObject((session ?: return login()).toString()).put("room", JSONObject().put("id", id))
        val big = large
        async({ loadRoom(account) }, "가족방을 열고 있어요.") { current ->
            saveSession(current, big); resetRoomState()
            if (room.has("id")) home() else roomChoice()
        }
    }
    private fun welcome() {
        navigation("토닥", name = "welcome")
        ui.gap(content, 20)
        ui.label(content, "토닥", 34f, true).gravity = Gravity.CENTER
        ui.gap(content, 20)
        ui.label(content, "가족의 하루에\n마음을 건네는 시간", 26f, true).gravity = Gravity.CENTER
        ui.gap(content, 20); ui.art(content); ui.gap(content, 20)
        ui.label(content, "사진 한 장, 짧은 한마디로\n오늘도 서로의 곁에 있어요.", 18f, color = ui.muted).gravity = Gravity.CENTER
        ui.gap(content, 20)
        ui.button(content, "토닥 시작하기") { register() }
        ui.gap(content, 12)
        ui.ghost(content, "이미 계정이 있어요") { login() }
        if (sessions.all().isNotEmpty()) ui.ghost(content, "이 휴대폰의 계정으로 돌아가기") { accounts() }
        if (BuildConfig.DEBUG) ui.ghost(content, "테스트 연결 설정") { connectionSettings() }
    }
    private fun register() {
        navigation("계정 만들기", { welcome() }, name = "register")
        heading("어떻게 불러드릴까요?", "가족에게 보일 이름을 알려주세요.")
        val name = ui.input(content, "내 이름", "예: 홍정아")
        val username = ui.input(content, "아이디", "로그인할 아이디", identifier = true)
        val password = ui.input(content, "계정 비밀번호", "숫자를 포함한 10자 이상", password = true).apply { typeface = ui.font; setHintTextColor(ui.hintGray) }
        val confirmation = ui.input(content, "비밀번호 확인", "비밀번호를 한 번 더 입력해 주세요", password = true).apply {
            typeface = ui.font; setHintTextColor(ui.hintGray)
        }
        ui.label(content, "성별 (필수)", 16f, true)
        val genders = Spinner(this)
        genders.contentDescription = "성별 (필수)"
        genders.adapter = ArrayAdapter(this, android.R.layout.simple_spinner_dropdown_item, listOf("성별을 선택해 주세요", "남성", "여성"))
        content.addView(genders, LinearLayout.LayoutParams(-1, ui.dp(56)))
        ui.gap(content)
        val voice = voicePicker(ApiClient(baseUrl = sessions.serverUrl()), "소식을 읽어 줄 목소리 (선택)", null, registering = true)
        ui.button(content, "계정 만들기") {
            if (username.text.isBlank() || password.text.isBlank() || name.text.isBlank()) {
                toast("아이디, 비밀번호, 이름을 입력해 주세요."); return@button
            }
            if (genders.selectedItemPosition == 0) { toast("성별을 선택해 주세요."); return@button }
            if (password.text.length !in 10..128 || password.text.none { it in '0'..'9' }) {
                password.error = "비밀번호는 10자 이상, 숫자 포함으로 입력해 주세요. 최대 128자예요."; return@button
            }
            confirmation.error = null
            if (confirmation.text.isEmpty() || password.text.toString() != confirmation.text.toString()) {
                confirmation.error = if (confirmation.text.isEmpty()) "비밀번호를 한 번 더 입력해 주세요."
                    else "비밀번호가 일치하지 않아요. 다시 확인해 주세요."
                confirmation.requestFocus()
                return@button
            }
            if (name.text.toString().trim().length > 40) { name.error = "이름은 40자까지 입력해 주세요."; return@button }
            val data = json("username" to username.text.toString().trim(), "password" to password.text.toString(),
                "name" to name.text.toString().trim(), "gender" to listOf("", "male", "female")[genders.selectedItemPosition])
            voice()?.let { data.put("tts_voice", it) }
            val client = ApiClient(baseUrl = sessions.serverUrl())
            async({ client.request("accounts/register/", "POST", data) }) {
                saveSession(it, false); roomChoice()
            }
        }
    }
    private fun login(initialUsername: String = "", expiredUserId: Int? = null, expiredLarge: Boolean = false) {
        navigation("로그인", { welcome() }, name = "login")
        ui.label(content, "다시 만나 반가워요", 14f, color = ui.muted); ui.gap(content, 16)
        heading("가족이 기다리고 있어요", "내 계정으로 소식을 이어보세요.")
        val username = ui.input(content, "아이디", "계정 아이디", initial = initialUsername, identifier = true)
        val password = ui.input(content, "비밀번호", "계정 비밀번호", password = true)
        ui.button(content, "로그인") {
            if (username.text.isBlank() || password.text.isBlank()) {
                toast("아이디와 비밀번호를 입력해 주세요."); return@button
            }
            val data = json("username" to username.text.toString().trim(), "password" to password.text.toString())
            val client = ApiClient(baseUrl = sessions.serverUrl())
            async({
                val account = client.request("accounts/login/", "POST", data)
                loadRoom(account)
            }) { account ->
                val big = sessions.all().firstOrNull { it.getInt("user_id") == account.getInt("user_id") }?.optBoolean("large")
                    ?: (expiredUserId == account.getInt("user_id") && expiredLarge)
                saveSession(account, big)
                if (room.has("id")) home() else roomChoice()
            }
        }
        ui.button(content, "새 계정 만들기", false) { register() }
    }
    private fun create() {
        navigation("우리 가족 방", { roomChoice() }, name = "create")
        ui.art(content, width = 200); ui.gap(content, 20)
        heading("우리 가족만의\n공간을 만들어요", "초대 코드와 가족방 비밀번호로 함께할 수 있어요.")
        val roomName = ui.input(content, "가족 방 이름", "예: 정아네 가족")
        val password = ui.input(content, "가족 방 비밀번호", "가족에게 공유할 비밀번호", password = true)
        ui.gap(content)
        var at = "21:00"
        val time = ui.button(content, "하루 요약 시간  ·  밤 9시", false) {
            TimePickerDialog(this, { _, h, m -> at = "%02d:%02d".format(h, m) }, 21, 0, true).show()
        }
        // Reflect the selected value when returning from the picker.
        time.setOnClickListener {
            val parts = at.split(":")
            TimePickerDialog(this, { _, h, m -> at = "%02d:%02d".format(h, m); time.text = "하루 요약 시간  ·  " + at }, parts[0].toInt(), parts[1].toInt(), true).show()
        }
        ui.gap(content)
        ui.button(content, "가족 방 만들기") {
            if (roomName.text.isBlank() || password.text.isBlank()) { toast("가족 방 이름과 비밀번호를 입력해 주세요."); return@button }
            val data = json("room_name" to roomName.text.toString(), "password" to password.text.toString(), "digest_time" to at)
            val client = api
            async({ client.request("families/create/", "POST", data) }) {
                saveRoom(it) { invite(password.text.toString()) }
            }
        }
    }
    private fun invite(password: String? = null) {
        navigation("가족 초대", { home() }, name = "invite")
        heading("가족 방이 준비됐어요.", "초대코드와 가족 방 비밀번호를 가족에게 알려 주세요.")
        ui.note(content, room.getString("name"))
        ui.gap(content, 24)
        ui.label(content, "초대코드", 16f, color = ui.muted)
        ui.label(content, room.getString("invite_code"), 36f, true, ui.green)
        ui.gap(content, 24)
        if (password != null) ui.note(content, "가족 방 비밀번호  ·  " + password)
        else ui.label(content, "방을 만들 때 정한 비밀번호도 함께 알려 주세요.", 18f)
        ui.gap(content, 24)
        ui.button(content, "초대코드 복사", false) {
            (getSystemService(CLIPBOARD_SERVICE) as ClipboardManager).setPrimaryClip(ClipData.newPlainText("토닥 가족 초대코드", room.getString("invite_code")))
            toast("초대코드를 복사했어요.")
        }
        ui.button(content, "가족 소식으로 가기") { home() }
    }
    private fun join() {
        navigation("가족 방에 들어가기", { roomChoice() }, name = "join")
        ui.label(content, "초대받으셨나요?", 14f, color = ui.muted); ui.gap(content, 16)
        heading("가족이 보낸 코드를\n입력해 주세요.", "초대 코드와 가족방 비밀번호를 입력해 주세요.")
        val code = ui.input(content, "초대코드", "예: ABC123")
        val password = ui.input(content, "가족 방 비밀번호", "가족이 알려준 비밀번호", password = true)
        ui.button(content, "가족 방 확인하기") {
            if (code.text.isBlank() || password.text.isBlank()) { toast("초대코드와 비밀번호를 입력해 주세요."); return@button }
            invitation = json("invite_code" to code.text.toString().trim().uppercase(), "password" to password.text.toString())
            async({ ApiClient(baseUrl = sessions.serverUrl()).request("families/lookup/", "POST", invitation) }) {
                val userId = session?.optInt("user_id")
                if (objects(it.getJSONArray("members")).any { member -> member.optInt("id") == userId }) {
                    toast("이미 참여한 가족방이에요."); return@async
                }
                joinRoom = it; treeDraft = FamilyTreeDraft(it.getJSONObject("tree")); tree()
            }
        }
    }
    private fun tree() {
        val draft = treeDraft ?: return
        navigation("가족에서 내 자리", { cancelTree() }, name = "tree")
        heading("가계도에서\n내 자리를 찾아보세요.", "한 손가락으로 이동하고, 두 손가락으로 확대·축소하세요. +로 빈 가족을 추가하고 내 자리를 선택해 주세요.")
        val selected = ui.text("", 17f, true, ui.coralDeep)
        val next = ui.button(ui.column(), "선택한 자리로 계속하기") { profile() }
        lateinit var board: FamilyTreeView
        lateinit var undo: Button
        fun update(focus: String? = null) {
            selected.text = if (draft.selectedId == null) "아직 내 자리를 선택하지 않았어요." else session!!.getString("name") + "님의 자리를 선택했어요."
            next.isEnabled = draft.selectedId != null; next.alpha = if (next.isEnabled) 1f else .45f
            undo.isEnabled = draft.additions.isNotEmpty(); undo.alpha = if (undo.isEnabled) 1f else .45f
            board.render(focus)
        }
        board = FamilyTreeView(this, ui, draft, session!!.getString("name"), onAdd = { action ->
            runCatching { draft.add(action.anchor, action.relation, action.coParent) }.fold({ id ->
                update(id); toast("빈 가족을 추가했어요. 이 자리가 나라면 노드를 눌러 선택해 주세요.")
            }, { toast(it.message ?: "가족을 추가하지 못했어요.") })
        }, onPerson = { id ->
            val person = draft.people.getValue(id)
            if (person.occupied) toast("이미 가입한 가족의 자리예요.") else {
                val accountGender = session!!.optString("gender", "unknown")
                if (person.gender != "unknown" && accountGender != "unknown" && person.gender != accountGender) {
                    toast("선택한 자리와 계정의 성별이 달라요. 다른 자리를 선택해 주세요.")
                } else AlertDialog.Builder(this).setTitle("이 자리가 나인가요?")
                    .setMessage(session!!.getString("name") + "님의 계정 정보를 이 자리에 연결해요. 가입 완료 전까지는 저장되지 않아요.")
                    .setPositiveButton("내 자리로 선택") { _, _ -> draft.selectedId = id; update(id) }
                    .setNegativeButton("닫기", null).show()
            }
        })
        content.addView(board, LinearLayout.LayoutParams(-1, ui.dp(440)))
        val controls = ui.row()
        val reset = ui.button(ui.column(), "기준 인물로", false, 52) { board.centerOn(draft.ownerId) }
        undo = ui.button(ui.column(), "추가 취소", false, 52) { draft.undo(); update(draft.selectedId ?: draft.ownerId) }
        (reset.parent as LinearLayout).removeView(reset); (undo.parent as LinearLayout).removeView(undo)
        controls.addView(reset, LinearLayout.LayoutParams(0, -2, 1f).apply { marginEnd = ui.dp(8) })
        controls.addView(undo, LinearLayout.LayoutParams(0, -2, 1f)); content.addView(controls)
        ui.gap(content, 16); content.addView(selected)
        ui.label(content, "살구색: 가입한 가족 · 흰색: 빈 가족\n형제자매는 부모의 자녀 +에서 추가할 수 있어요.", 14f, color = ui.muted)
        (next.parent as LinearLayout).removeView(next); content.addView(next)
        update(draft.selectedId ?: draft.ownerId)
    }

    private fun cancelTree() {
        if (treeDraft?.additions?.isNotEmpty() == true || treeDraft?.selectedId != null) {
            AlertDialog.Builder(this).setTitle("가계도 설정을 취소할까요?").setMessage("추가한 빈 가족과 선택한 자리는 저장되지 않아요.")
                .setPositiveButton("설정 취소") { _, _ -> treeDraft = null; join() }.setNegativeButton("계속 설정", null).show()
        } else { treeDraft = null; join() }
    }

    private fun profile() {
        val draft = treeDraft ?: return
        if (draft.selectedId == null) return
        navigation("가족 방 참여", { tree() }, name = "profile")
        heading(session!!.getString("name") + "님의 자리로\n가족 방에 함께해요.", "가입을 완료하면 추가한 가족과 관계가 함께 저장돼요.")
        val big = Switch(this).apply { text = "큰 글씨로 보기"; textSize = 20f; typeface = ui.font; fontVariationSettings = "'wght' 400"; isChecked = draft.people.getValue(draft.selectedId!!).generation >= 2; minimumHeight = ui.dp(64) }
        content.addView(big); ui.gap(content, 24)
        ui.button(content, "가족 방에 들어가기") {
            val data = draft.payload().put("invite_code", invitation.getString("invite_code")).put("password", invitation.getString("password"))
            val client = api
            async({ client.request("families/join/", "POST", data) }, failure = { error ->
                if (error is ApiException && error.status == 409) {
                    AlertDialog.Builder(this).setTitle("가계도가 변경되었어요")
                        .setMessage("변경 사항은 저장되지 않았어요. 최신 가계도에서 내 자리를 다시 선택해 주세요.")
                        .setCancelable(false).setPositiveButton("다시 시작") { _, _ ->
                            treeDraft = null
                            join()
                            async({ ApiClient(baseUrl = sessions.serverUrl()).request("families/lookup/", "POST", invitation) }) {
                                joinRoom = it; treeDraft = FamilyTreeDraft(it.getJSONObject("tree")); tree()
                            }
                        }.show()
                    true
                } else false
            }) {
                treeDraft = null; invitation = JSONObject()
                saveRoom(it, big.isChecked) { home() }
            }
        }
    }
    private fun home(refresh: SwipeRefreshLayout? = null) {
        if (refresh == null) navigation(room.optString("name", "우리 가족"), tab = 0, name = "home")
        val client = api
        async({ client.request("posts/") }, refresh = refresh) { data ->
            content.removeAllViews()
            ui.button(content, "가족 추억 찾기", false, if (large) 76 else 56) { familyMemories() }
            ui.gap(content, 20)
            val posts = objects(data.getJSONArray("posts")).sortedWith(
                compareByDescending<JSONObject> {
                    runCatching { OffsetDateTime.parse(it.optString("created_at")).toInstant() }.getOrDefault(java.time.Instant.MIN)
                }.thenByDescending { it.optLong("id") }
            )
            if (posts.isEmpty()) {
                ui.art(content, width = 280); ui.gap(content, 20)
                heading("첫 소식을 기다리고 있어요", "멋진 사진이 없어도 괜찮아요.\n짧은 한마디로 하루를 전해 보세요.")
                ui.button(content, "첫 소식 쓰기") { composer() }
                ui.button(content, "가족 초대 코드 보기", false) { invite() }
                ui.ghost(content, "하루 요약 보기") { digest() }
                return@async
            }
            if (large) {
                ui.note(content, "큰 글씨로 보고 있어요.", true); ui.gap(content, 20)
            } else {
                val hero = ui.card(content, ui.sky, stroke = false)
                val row = ui.row()
                val copy = ui.column()
                ui.label(copy, "오늘도, 함께", 14f, color = ui.skyDeep); ui.gap(copy, 8)
                ui.label(copy, "짧은 안부에도\n마음이 전해져요", 20f, true, ui.skyDeep)
                ui.gap(copy, 8)
                ui.label(copy, "오늘의 소식 쓰기  ›", 16f, true, ui.skyDeep).apply {
                    minimumHeight = ui.dp(48); gravity = Gravity.CENTER_VERTICAL
                    isClickable = true; isFocusable = true; setOnClickListener { composer() }
                }
                row.addView(copy, LinearLayout.LayoutParams(0, -2, 1f))
                row.addView(TodakArtView(this, "together", 126), LinearLayout.LayoutParams(ui.dp(126), ui.dp(115)))
                hero.addView(row); ui.gap(content, 20)
            }
            ui.button(content, "우리 가족의 하루 요약", false, if (large) 76 else 56) { digest() }
            ui.gap(content, 20); ui.label(content, "가족의 소식", if (large) 24f else 20f, true); ui.gap(content, 20)
            posts.forEach { post ->
                val card = ui.card(content)
                author(card, post)
                ui.label(card, post.optString("caption").ifBlank { "사진으로 남긴 오늘의 하루" }, if (large) 23f else 18f)
                ui.gap(card, 12); postPhotos(card, post)
                val audio = postAudio(post)
                if (large) {
                    card.addView(audio.toggle, LinearLayout.LayoutParams(-1, -2))
                    ui.button(card, "글로 댓글 쓰기", false, 76) { detail(post, focusComment = true) }
                    ui.button(card, "AI 요약", false, 76) { audio.showSummary() }
                } else {
                    val actions = ui.row(); card.addView(actions)
                    postAction(actions, "comment", "댓글 " + post.getInt("comment_count")) { detail(post) }
                    postAction(actions, "digest", "AI 요약") { audio.showSummary() }
                    actions.addView(audio.toggle, LinearLayout.LayoutParams(0, -2, 1f))
                }
                card.addView(audio, LinearLayout.LayoutParams(-1, -2))
                ui.button(card, "궁금한 점을 물어보세요", false, if (large) 76 else 48) { detail(post, focusQuestion = true) }
                ui.gap(content, 20)
            }
        }
    }
    private fun familyMemories(saved: Bundle? = null) {
        if (!room.has("id")) { roomChoice(); return }
        navigation("가족 추억 찾기", { home() }, tab = 0, name = "memories")
        heading("함께 쌓아온 추억 찾기", "가족이 남긴 소식을 바탕으로\n궁금한 이야기를 찾아드려요.")
        memoryPanel = FamilyMemoryPanel(this, ui, large, api, questions, saved) {
            val username = session?.optString("username").orEmpty()
            val userId = session?.optInt("user_id")
            val big = large
            sessions.removeCurrent(); session = null; room = JSONObject(); imageLoader.clear()
            login(username, userId, big)
        }.also { content.addView(it, LinearLayout.LayoutParams(-1, -2)) }
    }
    private fun postAction(parent: LinearLayout, symbol: String, label: String, action: () -> Unit) {
        val item = ui.column(4).apply {
            gravity = Gravity.CENTER; minimumHeight = ui.dp(60)
            isClickable = true; isFocusable = true; contentDescription = label
            background = android.graphics.drawable.RippleDrawable(android.content.res.ColorStateList.valueOf(ui.border), ui.shape(ui.paper), null)
            setOnClickListener { action() }
        }
        item.addView(IconView(this, symbol, ui.muted), LinearLayout.LayoutParams(ui.dp(22), ui.dp(22)))
        ui.gap(item, 4); ui.label(item, label, 14f, color = ui.muted).gravity = Gravity.CENTER
        parent.addView(item, LinearLayout.LayoutParams(0, -2, 1f))
    }
    private fun feedError(message: String) {
        content.removeAllViews()
        ui.art(content, "grandchild_sad", 180); ui.gap(content, 20)
        heading("소식을 불러오지 못했어요", message)
        ui.button(content, "다시 불러오기") { home() }
        ui.button(content, "가족방으로", false) { roomChoice() }
        if (BuildConfig.DEBUG) ui.ghost(content, "테스트 연결 설정") { connectionSettings() }
    }
    private fun photoItems(post: JSONObject): List<JSONObject> {
        post.optJSONArray("images")?.let { return objects(it).filter { image -> image.optString("url").isNotBlank() } }
        val legacy = post.optString("image_url").takeIf { it.isNotBlank() && it != "null" }
        return if (legacy == null) emptyList() else listOf(json("url" to legacy))
    }

    private fun postPhotos(parent: LinearLayout, post: JSONObject) {
        val photos = photoItems(post)
        if (photos.isEmpty()) return
        parent.addView(PhotoCarousel(this, photos.size, large,
            load = { image, index -> remotePhoto(image, post, photos[index].getString("url")) },
            open = { index -> fullPhoto(post, index) },
            loadThumbnail = { image, index -> remotePhoto(image, post, photos[index].getString("url"), thumbnail = true) },
            release = { image -> imageLoader.release(image) }), LinearLayout.LayoutParams(-1, -2))
    }

    private fun fullPhoto(post: JSONObject, initial: Int = 0) {
        val photos = photoItems(post)
        if (photos.isEmpty()) return
        var index = initial.coerceIn(0, photos.lastIndex)
        val dialog = Dialog(this)
        val container = ui.column(16).apply { setBackgroundColor(Color.WHITE) }
        val image = ImageView(this).apply { scaleType = ImageView.ScaleType.FIT_CENTER }
        val label = ui.label(container, "", 20f, true)
        container.addView(image, LinearLayout.LayoutParams(-1, 0, 1f))
        val controls = ui.row(); container.addView(controls)
        lateinit var previous: Button; lateinit var next: Button
        fun refresh() {
            remotePhoto(image, post, photos[index].getString("url"))
            label.text = "사진 ${index + 1} / ${photos.size}"
            previous.isEnabled = index > 0; next.isEnabled = index < photos.lastIndex
            previous.alpha = if (previous.isEnabled) 1f else 0.4f
            next.alpha = if (next.isEnabled) 1f else 0.4f
        }
        previous = ui.button(controls, "이전 사진", false) { if (index > 0) { index--; refresh() } }
        next = ui.button(controls, "다음 사진", false) { if (index < photos.lastIndex) { index++; refresh() } }
        previous.layoutParams = LinearLayout.LayoutParams(0, -2, 1f).apply { marginEnd = ui.dp(4) }
        next.layoutParams = LinearLayout.LayoutParams(0, -2, 1f).apply { marginStart = ui.dp(4) }
        controls.visibility = if (photos.size > 1) View.VISIBLE else View.GONE
        ui.button(container, "닫기") { dialog.dismiss() }
        dialog.setContentView(container)
        dialog.setOnDismissListener { imageLoader.release(image) }
        dialog.show(); dialog.window?.setLayout(-1, -1)
        refresh()
    }

    private fun author(parent: LinearLayout, post: JSONObject) {
        val row = ui.row()
        val initials = post.getString("author_name").takeLast(2)
        val badge = ui.text(initials, 16f, true, ui.green).apply {
            gravity = Gravity.CENTER; background = ui.shape(ui.sage, 24); contentDescription = post.getString("author_name")
        }
        row.addView(badge, LinearLayout.LayoutParams(ui.dp(46), ui.dp(46)))
        val labels = ui.column().apply { setPadding(ui.dp(12), 0, 0, 0) }
        ui.label(labels, post.getString("author_name"), if (large) 23f else 19f, true)
        val time = runCatching {
            OffsetDateTime.parse(post.getString("created_at")).format(DateTimeFormatter.ofPattern("M월 d일 HH:mm"))
        }.getOrDefault("")
        ui.label(labels, post.getString("relationship") + " · " + time, 14f, color = ui.muted)
        row.addView(labels, LinearLayout.LayoutParams(0, -2, 1f)); parent.addView(row); ui.gap(parent, 14)
    }
    private fun detail(post: JSONObject, focusComment: Boolean = false, focusQuestion: Boolean = false) {
        selectedPost = post
        navigation("가족의 소식", { home() }, name = "detail")
        val client = api
        async({ client.request("posts/" + post.getInt("id") + "/") }) { data ->
            selectedPost = data
            val card = ui.card(content)
            author(card, data)
            ui.label(card, data.getString("caption").ifBlank { "사진으로 남긴 오늘의 하루" }, if (large) 23f else 18f)
            ui.gap(card, 12); postPhotos(card, data)
            val audio = postAudio(data)
            ui.button(card, "AI 요약", false, if (large) 76 else 56) { audio.showSummary() }
            card.addView(audio.toggle, LinearLayout.LayoutParams(-1, -2))
            card.addView(audio, LinearLayout.LayoutParams(-1, -2))
            val qa = PostQuestionPanel(this, ui, data.getInt("id"), large, client, questions)
            card.addView(qa, LinearLayout.LayoutParams(-1, -2))
            if (focusQuestion) qa.post { if (qa.isAttachedToWindow) qa.open(focus = true) }
            val comments = objects(data.getJSONArray("comments"))
            ui.gap(content, 24); ui.label(content, "댓글 ${comments.size}", if (large) 24f else 20f, true); ui.gap(content, 20)
            if (comments.isEmpty()) { ui.label(content, "첫 댓글을 남겨 주세요.", 17f, color = ui.muted); ui.gap(content, 16) }
            comments.forEach { c ->
                val bubble = ui.card(content, ui.blush, stroke = false)
                ui.label(bubble, c.getString("author_name") + " · " + c.getString("relationship"), 16f, true, ui.coralDeep)
                ui.gap(bubble, 8); ui.label(bubble, c.getString("text"), if (large) 23f else 18f)
                ui.gap(content, 12)
            }
            ui.gap(content, 12)
            lateinit var composer: CommentComposer
            composer = CommentComposer(this, ui, large) { comment ->
                if (!busy) {
                    composer.setSending(true)
                    val body = json("text" to comment)
                    async({ client.request("posts/" + data.getInt("id") + "/comments/", "POST", body) },
                        showLoading = false,
                        failure = { error ->
                            val message = if (error is ApiException && error.status == 401)
                                "로그인이 만료되었어요. 작성한 댓글은 유지돼요. 다시 로그인해 주세요."
                            else (error as? ApiException)?.message ?: "댓글을 보내지 못했어요. 작성한 내용은 유지돼요. 다시 시도해 주세요."
                            composer.showError(message)
                            true
                        }) {
                        composer.input.setText("")
                        composer.setSending(false)
                        postingSuccess("댓글을 달았어요!") { detail(data) }
                    }
                }
            }
            content.addView(composer, LinearLayout.LayoutParams(-1, -2))
            val text = composer.input
            ui.button(content, "목소리로 댓글 남기기", false, if (large) 76 else 56) { voice(data, fromDetail = true) }
            ui.gap(content, 12); ui.label(content, "댓글은 이 가족방에만 보여요.", 14f, color = ui.muted)
            if (focusComment) {
                val number = pageNumber
                text.requestFocus()
                text.post {
                    if (number == pageNumber && text.isAttachedToWindow) {
                        (getSystemService(INPUT_METHOD_SERVICE) as InputMethodManager).showSoftInput(text, InputMethodManager.SHOW_IMPLICIT)
                    }
                }
            }
        }
    }
    private fun launchGallery() {
        // Snapshot the draft before opening the gallery, including on rotation.
        caption = captionInput?.text?.toString() ?: caption
        runCatching {
            photoPicker.launch(Intent(this, PhotoPickerActivity::class.java))
        }.onFailure { toast("사진첩을 열 수 없어요.") }
    }
    private fun launchCamera() {
        val directory = File(filesDir, "camera").apply { mkdirs() }
        val output = File.createTempFile("capture-", ".jpg", directory)
        val uri = FileProvider.getUriForFile(this, packageName + ".photos", output)
        val intent = Intent(MediaStore.ACTION_IMAGE_CAPTURE).apply {
            putExtra(MediaStore.EXTRA_OUTPUT, uri)
            addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION or Intent.FLAG_GRANT_READ_URI_PERMISSION)
            clipData = ClipData.newRawUri("사진 저장", uri)
        }
        pendingPhoto = output
        try { startActivityForResult(intent, cameraCode) }
        catch (_: android.content.ActivityNotFoundException) { output.delete(); pendingPhoto = null; toast("카메라를 열 수 없어요. 사진첩에서 골라 주세요.") }
    }
    @Deprecated("Platform result API")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == cameraCode) {
            val output = pendingPhoto; pendingPhoto = null
            if (resultCode == RESULT_OK && output != null && output.length() > 0) {
                val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
                BitmapFactory.decodeFile(output.absolutePath, bounds)
                if (output.length() > 10 * 1024 * 1024 || bounds.outWidth <= 0 || bounds.outHeight <= 0 ||
                    bounds.outWidth.toLong() * bounds.outHeight > 20_000_000) {
                    output.delete(); toast("사진이 너무 크거나 읽을 수 없어요. 다른 사진을 선택해 주세요.")
                    composer()
                    return
                }
                selectedPhotos().filter { it != output }.forEach { it.delete() }; extraPhotos.clear()
                photo = output; draftPhotoIndex = 0; composer()
            } else { output?.delete(); composer() }
        }
    }
    private fun selectedPhotos(): List<File> = listOfNotNull(photo) + extraPhotos
    private fun clearPhotoDraft() {
        selectedPhotos().forEach { it.delete() }
        photo = null; extraPhotos.clear(); caption = ""; draftPhotoIndex = 0
    }
    private fun copyGalleryPhotos(uris: List<Uri>): List<File> {
        val directory = File(filesDir, "camera").apply { mkdirs() }
        val files = mutableListOf<File>()
        var combined = 0L
        try {
            uris.forEach { uri ->
                val output = File.createTempFile("picked-", ".jpg", directory)
                files.add(output)
                contentResolver.openInputStream(uri)?.use { source ->
                    output.outputStream().use { destination ->
                        val buffer = ByteArray(8192); var total = 0L
                        while (true) {
                            val count = source.read(buffer); if (count < 0) break
                            total += count; combined += count
                            if (total > 10 * 1024 * 1024 || combined > 30 * 1024 * 1024) {
                                throw ApiException("사진 한 장은 10MB, 전체 사진은 30MB까지 선택할 수 있어요.")
                            }
                            destination.write(buffer, 0, count)
                        }
                    }
                } ?: throw ApiException("사진을 읽지 못했어요.")
                val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
                BitmapFactory.decodeFile(output.absolutePath, bounds)
                if (bounds.outWidth <= 0 || bounds.outHeight <= 0 || bounds.outWidth.toLong() * bounds.outHeight > 20_000_000) {
                    throw ApiException("읽을 수 없거나 너무 큰 사진이에요. 다른 사진을 선택해 주세요.")
                }
            }
            return files
        } catch (error: Exception) {
            files.forEach { it.delete() }
            if (error is SecurityException) throw ApiException("사진 접근 권한이 바뀌었어요. 사진첩에서 다시 선택해 주세요.")
            throw error
        }
    }
    private fun composer() {
        val files = selectedPhotos()
        draftPhotoIndex = draftPhotoIndex.coerceIn(0, files.lastIndex.coerceAtLeast(0))
        navigation("소식 쓰기", { discardPhoto() }, name = "post")
        ui.note(content, "글만 써도 괜찮아요.\n사진은 최대 5장까지 함께 보낼 수 있어요.", large)
        ui.gap(content, 20)
        val text = ui.input(content, "가족에게 전할 이야기", "오늘은 어떤 하루였나요?\n가족에게 전하고 싶은 이야기를 적어보세요.", multiline = true, initial = caption)
        text.layoutParams = text.layoutParams.apply { height = ui.dp(if (large) 220 else 180) }
        captionInput = text
        val previews = files.map { localPreview(it) }
        val hasInvalidPhoto = previews.any { it == null }
        content.addView(DraftPhotoStrip(this, previews, large,
            remove = { index ->
                caption = captionInput?.text?.toString() ?: caption
                val file = files[index]
                val remaining = selectedPhotos().filter { it != file }
                file.delete(); photo = remaining.firstOrNull(); extraPhotos.clear(); extraPhotos.addAll(remaining.drop(1))
                draftPhotoIndex = index.coerceAtMost(remaining.lastIndex.coerceAtLeast(0)); composer()
            }, choose = { caption = text.text.toString(); launchGallery() }), LinearLayout.LayoutParams(-1, -2))
        if (hasInvalidPhoto) ui.label(content, "읽을 수 없는 사진이 있어요. 빼거나 다시 선택해 주세요.", 18f)
        ui.gap(content, 16)
        ui.label(content, "사진 ${files.size} / 5장 · 한 장당 10MB · 전체 30MB", 14f, color = ui.muted)
        ui.ghost(content, if (files.isEmpty()) "사진 촬영하기" else "새로 촬영하기 · 사진 한 장으로 바꾸기") {
            caption = text.text.toString(); launchCamera()
        }
        ui.gap(content, 12)
        ui.button(content, "가족에게 전하기", height = if (large) 76 else 56) {
            caption = text.text.toString().trim()
            if (caption.length > 2000) { toast("이야기는 2,000자까지 남길 수 있어요."); return@button }
            if (files.isEmpty() && caption.isBlank()) { toast("글이나 사진을 하나 이상 남겨 주세요."); return@button }
            if (hasInvalidPhoto) { toast("읽을 수 없는 사진을 다시 선택해 주세요."); return@button }
            val client = api
            async({ client.uploadPost(files, caption) }, "가족에게 소식을 전하고 있어요.") {
                clearPhotoDraft(); imageLoader.clear()
                postingSuccess("글 업로드가 완료됐어요") { home() }
            }
        }
        ui.gap(content, 16); ui.label(content, "작성한 소식은 이 가족방에만 보여요.", 14f, color = ui.muted)
    }
    private fun localPreview(file: File): Bitmap? {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeFile(file.absolutePath, bounds)
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0 || bounds.outWidth.toLong() * bounds.outHeight > 20_000_000) return null
        var sample = 1
        while (maxOf(bounds.outWidth, bounds.outHeight) / sample > 640) sample *= 2
        val options = BitmapFactory.Options().apply { inSampleSize = sample }
        val bitmap = BitmapFactory.decodeFile(file.absolutePath, options)
        if (bitmap == null) return null
        val orientation = runCatching {
            android.media.ExifInterface(file.absolutePath).getAttributeInt(android.media.ExifInterface.TAG_ORIENTATION, 1)
        }.getOrDefault(1)
        val matrix = android.graphics.Matrix()
        when (orientation) {
            2 -> matrix.setScale(-1f, 1f)
            3 -> matrix.setRotate(180f)
            4 -> matrix.setScale(1f, -1f)
            5 -> { matrix.setRotate(90f); matrix.postScale(-1f, 1f) }
            6 -> matrix.setRotate(90f)
            7 -> { matrix.setRotate(-90f); matrix.postScale(-1f, 1f) }
            8 -> matrix.setRotate(-90f)
        }
        val upright = if (matrix.isIdentity) bitmap else Bitmap.createBitmap(bitmap, 0, 0, bitmap.width, bitmap.height, matrix, true)
        if (upright !== bitmap) bitmap.recycle()
        return upright
    }
    private fun discardPhoto() {
        caption = captionInput?.text?.toString() ?: caption
        if (selectedPhotos().isEmpty() && caption.isBlank()) { home(); return }
        AlertDialog.Builder(this).setTitle("소식 작성을 그만할까요?")
            .setPositiveButton("그만하기") { _, _ -> clearPhotoDraft(); home() }
            .setNegativeButton("계속 쓰기", null).show()
    }
    private fun stopPostAudio() {
        activePostAudio?.stop()
        activePostAudio = null
    }
    private fun postAudio(post: JSONObject): InlinePostAudio = InlinePostAudio(
        this, ui, post, large, api, speaker, summaries,
        activate = { audio ->
            if (activePostAudio !== audio) stopPostAudio()
            activePostAudio = audio
        },
        login = {
            val username = session?.optString("username").orEmpty()
            val userId = session?.optInt("user_id"); val big = large
            sessions.removeCurrent(); session = null; room = JSONObject(); imageLoader.clear()
            login(username, userId, big)
        }
    )
    private fun voice(post: JSONObject, fromDetail: Boolean = false) {
        selectedPost = post; recognized = ""; voiceFromDetail = fromDetail
        navigation("음성 댓글", { leaveVoice(post) }, name = "voice")
        heading("편하게 말씀해 주세요", post.getString("author_name") + "님의 소식에 따뜻한 답장을 남겨요.")
        ui.label(content, "답장은 이 소식의 가족 댓글로 올라가요.", 19f, color = ui.muted)
        ui.gap(content, 24)
        val recorderPanel = ui.card(content, ui.sky, padding = 24, stroke = false)
        recorderPanel.addView(IconView(this, "mic", ui.skyDeep), LinearLayout.LayoutParams(ui.dp(64), ui.dp(64)).apply { gravity = Gravity.CENTER_HORIZONTAL })
        ui.gap(recorderPanel, 20)
        voiceStatus = ui.label(recorderPanel, "아래 버튼을 눌러 말씀해 주세요.", 22f, true, ui.skyDeep)
        ui.gap(recorderPanel, 20)
        voiceText = ui.label(recorderPanel, "말하기를 마치면 글로 바꾼 내용을 확인해요.", 19f, color = ui.skyDeep)
        ui.gap(content, 24)
        voiceButton = ui.button(content, "말하기 시작", height = 76) {
            if (recognized.isNotBlank()) prepareVoice(post)
            else if (recorder?.active == true || recording != null) {
                if (recorder?.active == true) finishRecording()
                val audio = recording
                if (audio == null) toast("조금 더 길게 다시 말씀해 주세요.")
                else {
                    val client = api
                    async({ client.transcribe(post.getInt("id"), audio) }, "말씀을 글로 바꾸고 있어요.") {
                        recognized = it.getString("recognized"); voiceText?.text = recognized
                        voiceStatus?.text = "이렇게 들었어요."
                        audio.delete(); recording = null
                        prepareVoice(post)
                    }
                }
            }
            else startVoice(post)
        }
        ui.button(content, "취소하기", false, 68) { leaveVoice(post) }
    }
    private fun leaveVoice(post: JSONObject) {
        if (voiceFromDetail) detail(post) else home()
    }
    private fun finishRecording() {
        recording = runCatching { recorder?.finish() }.getOrNull()
        voiceButton?.text = if (recording == null) "말하기 시작" else "다 말했어요"
        voiceStatus?.text = if (recording == null) "조금 더 길게 다시 말씀해 주세요." else "녹음을 마쳤어요. 다 말했어요를 누르면 확인해요."
    }
    private fun startVoice(post: JSONObject) {
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), microphoneCode); return
        }
        recognized = ""; speaker.stop(); recording?.delete(); recording = null
        recorder?.close()
        val number = pageNumber
        recorder = Recorder(this) { runOnUiThread { if (number == pageNumber) finishRecording() } }
        runCatching { recorder?.start() }.fold({
            voiceButton?.text = "다 말했어요"
            voiceStatus?.text = "듣고 있어요. 말씀을 마치면 다 말했어요를 눌러 주세요."
            voiceText?.text = "최대 1분까지 말씀하실 수 있어요."
        }, { voiceStatus?.text = "녹음을 시작하지 못했어요. 마이크 사용을 확인해 주세요." })
    }
    override fun onRequestPermissionsResult(code: Int, permissions: Array<String>, results: IntArray) {
        super.onRequestPermissionsResult(code, permissions, results)
        if (code == microphoneCode) {
            if (results.firstOrNull() == PackageManager.PERMISSION_GRANTED) selectedPost?.let { startVoice(it) }
            else { voiceStatus?.text = "말로 답장하려면 마이크 사용을 허용해 주세요."; toast("앱 설정에서 마이크 사용을 허용할 수 있어요.") }
        }
    }
    private fun prepareVoice(post: JSONObject) {
        recorder?.cancel()
        val client = api; val data = json("recognized" to recognized)
        async({ client.request("posts/" + post.getInt("id") + "/replies/prepare/", "POST", data) }, "가족에게 전할 댓글을 정리하고 있어요.") { review(post, it) }
    }
    private fun review(post: JSONObject, draft: JSONObject) {
        navigation("답장 확인", { voice(post, voiceFromDetail) }, name = "review")
        heading("이렇게 전할까요?", "보내기를 누르면 가족 모두가 볼 수 있어요.")
        author(content, post); postPhotos(content, post); ui.gap(content, 24)
        if (post.optString("caption").isNotBlank()) ui.note(content, post.getString("caption"), large)
        ui.label(content, "내가 한 말", 18f, color = ui.muted); ui.gap(content, 8)
        ui.note(content, draft.getString("recognized"), true); ui.gap(content, 24)
        val replyHeading = ui.row(); content.addView(replyHeading)
        replyHeading.addView(ui.text("가족에게 전할 댓글", if (large) 22f else 18f, color = ui.muted),
            LinearLayout.LayoutParams(0, -2, 1f))
        replyHeading.addView(ReplyAudioButton(this, ui, draft.getString("converted"), api, speaker, summaries, large).also { replyPreview = it })
        ui.gap(content, 8)
        ui.note(content, draft.getString("converted"), true); ui.gap(content, 24)
        ui.button(content, "가족에게 보내기", height = 76) {
            val client = api
            async({ client.request("replies/" + draft.getInt("id") + "/send/", "POST", JSONObject()) }, "가족에게 댓글을 전하고 있어요.") {
                postingSuccess("댓글을 달았어요!") { detail(post) }
            }
        }
        ui.button(content, "다시 말하기", false, 76) { voice(post, voiceFromDetail) }
    }
    private fun digest(date: String = digestDate, retry: Boolean = false) {
        digestDate = date
        navigation("하루 요약", { home() }, tab = 0, name = "digest")
        heading("우리 가족의 하루", "매일 " + room.optString("digest_time", "21:00") + "에 가족 소식을 모아요.")
        val client = api
        ui.button(content, date + "  ·  날짜 선택", false) {
            async({ client.request("digests/history/") }) { data ->
                val dates = data.getJSONArray("dates")
                val options = (0 until dates.length()).map { dates.getString(it) }.toTypedArray()
                AlertDialog.Builder(this).setTitle("지난 하루 요약").setItems(options) { _, index -> digest(options[index]) }.show()
            }
        }
        ui.gap(content, 24)
        async({
            if (retry) client.request("digests/", "POST", json("date" to date))
            else client.request("digests/?date=" + date)
        }) { data ->
            when (data.getString("status")) {
                "ready" -> {
                    ui.note(content, data.getString("text"), large); ui.gap(content, 20)
                    listen(content, data.getString("text"), "하루 요약 듣기", if (large) 76 else 64)
                    ui.gap(content, 24); ui.label(content, "요약에 함께한 소식", 20f, true); ui.gap(content)
                    objects(data.getJSONArray("posts")).forEach { p ->
                        postPhotos(content, p)
                        ui.label(content, p.getString("author_name"), 16f, true)
                        if (p.optString("caption").isNotBlank()) ui.label(content, p.getString("caption"), if (large) 23f else 18f)
                        ui.button(content, "소식 보기", false) { detail(p) }
                        ui.gap(content, 20)
                    }
                }
                "pending" -> ui.note(content, "오늘 " + data.getString("digest_time") + "에\n하루 요약이 도착해요.", large)
                "processing" -> { ui.note(content, "하루 요약을 준비하고 있어요.", large); ui.button(content, "다시 확인하기", false) { digest(date) } }
                "empty" -> ui.note(content, "이날은 아직 가족이 남긴 소식이 없어요.", large)
                else -> { ui.note(content, "하루 요약을 준비하지 못했어요. 다시 시도해 주세요.", large); ui.button(content, "요약 다시 준비하기", false) { digest(date, true) } }
            }
        }
    }
    private fun editAccount() {
        val account = session ?: return login()
        navigation("내 계정 수정", { if (room.has("id")) members() else roomChoice() }, name = "editAccount")
        heading("내 정보를 수정해요.")
        ui.label(content, "아이디: " + account.getString("username") + " · 변경할 수 없어요.", 16f, color = ui.muted)
        ui.gap(content)
        val name = ui.input(content, "이름", "가족에게 표시할 이름", initial = account.getString("name"))
        name.filters = arrayOf(android.text.InputFilter.LengthFilter(40))
        val voice = voicePicker(api, "소식을 읽어 줄 목소리", account.optString("tts_voice"))
        ui.label(content, "비밀번호를 바꿀 때만 아래 두 칸을 입력해 주세요. 변경하면 다른 기기에서는 다시 로그인해야 해요.", 17f, color = ui.muted)
        val current = ui.input(content, "현재 비밀번호", "변경할 때만 입력", password = true)
        val replacement = ui.input(content, "새 비밀번호", "숫자를 포함한 10자 이상", password = true).apply { typeface = ui.font; setHintTextColor(ui.hintGray) }
        ui.button(content, "수정 내용 저장하기") {
            if (name.text.isBlank()) { name.error = "이름을 입력해 주세요."; return@button }
            val changingPassword = current.text.isNotEmpty() || replacement.text.isNotEmpty()
            if (changingPassword && (current.text.isEmpty() || replacement.text.length !in 10..128 || replacement.text.none { it in '0'..'9' })) {
                replacement.error = "현재 비밀번호를 입력하고, 새 비밀번호는 10자 이상·숫자 포함으로 만들어 주세요."; return@button
            }
            val data = json("name" to name.text.toString().trim())
            voice()?.let { data.put("tts_voice", it) }
            if (changingPassword) data.put("current_password", current.text.toString()).put("new_password", replacement.text.toString())
            val client = api; val saved = JSONObject(account.toString()); val big = large
            async({ client.request("accounts/me/", "PATCH", data) }) { updated ->
                // Persist a rotated token before a separate room request can fail.
                updated.keys().forEach { key -> saved.put(key, updated.get(key)) }
                saveSession(saved, big); toast("계정 정보를 수정했어요.")
                if (room.has("id")) members() else roomChoice()
            }
        }
    }

    /**
     * Adds a voice picker filled from the server's voice list, so new voices need no app update.
     * It stays hidden unless there is a real choice; the returned getter then gives null and the
     * server keeps the account's current or default voice.
     */
    private fun voicePicker(client: ApiClient, title: String, selected: String?, registering: Boolean = false): () -> String? {
        val box = ui.column().apply { visibility = View.GONE }
        ui.label(box, title, if (registering) 16f else 18f, true)
        val note = if (registering) ui.label(box, "", 15f, color = ui.muted) else null
        val spinner = Spinner(this).apply { contentDescription = title }
        box.addView(spinner, LinearLayout.LayoutParams(-1, ui.dp(56)))
        var keys = emptyList<String>()
        val preview = ui.button(box, "선택한 목소리 미리 듣기", false) {
            val key = keys.getOrNull(spinner.selectedItemPosition) ?: return@button
            speaker.stop()
            playVoiceSample(client, key)
        }.apply { visibility = View.GONE }
        ui.gap(box)
        content.addView(box, LinearLayout.LayoutParams(-1, -2))
        val number = pageNumber
        network.execute {
            val loaded = runCatching {
                val data = client.request("speech/voices/")
                objects(data.getJSONArray("voices")) to data.getString("default")
            }.getOrNull()
            runOnUiThread {
                if (loaded == null || isDestroyed || number != pageNumber) return@runOnUiThread
                val (voices, fallback) = loaded
                if (voices.size < 2) return@runOnUiThread
                keys = voices.map { it.getString("key") }
                // Options show what each voice sounds like; a voice without a description shows its name.
                val titles = voices.map { it.optString("description").ifBlank { it.getString("name") } }
                val samples = voices.map { it.optBoolean("sample") }
                spinner.adapter = ArrayAdapter(this, android.R.layout.simple_spinner_dropdown_item, titles)
                spinner.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
                    override fun onItemSelected(parent: AdapterView<*>?, view: View?, position: Int, id: Long) {
                        speaker.stop()
                        preview.visibility = if (samples[position]) View.VISIBLE else View.GONE
                    }
                    override fun onNothingSelected(parent: AdapterView<*>?) {}
                }
                spinner.setSelection(keys.indexOf(selected?.takeIf { it in keys } ?: fallback).coerceAtLeast(0))
                note?.text = "기본값: " + (titles.getOrNull(keys.indexOf(fallback)) ?: titles.first()) + " · 내 계정 수정에서 언제든 바꿀 수 있어요."
                box.visibility = View.VISIBLE
            }
        }
        return { keys.getOrNull(spinner.selectedItemPosition) }
    }

    /** Plays the short line every voice reads, so people can compare voices before choosing. */
    private fun playVoiceSample(client: ApiClient, key: String) {
        val number = pageNumber
        network.execute {
            val bytes = runCatching { client.voiceSample(key) }.getOrNull()
            runOnUiThread {
                if (isDestroyed || number != pageNumber || !foreground) return@runOnUiThread
                if (bytes == null) { toast("목소리 예시를 재생하지 못했어요. 다시 시도해 주세요."); return@runOnUiThread }
                val file = File.createTempFile("voice-sample-", ".mp3", cacheDir)
                runCatching { file.writeBytes(bytes); speaker.play(file) }.onFailure { file.delete(); toast("목소리 예시를 재생하지 못했어요.") }
            }
        }
    }

    private fun familyTree() {
        navigation("우리 가족 가계도", { members() }, name = "familyTree")
        heading("우리 가족의 연결을\n한눈에 살펴보세요.", "한 손가락으로 이동하고, 두 손가락으로 확대·축소하세요.")
        val draft = FamilyTreeDraft(room.getJSONObject("tree"))
        draft.selectedId = objects(room.getJSONArray("members"))
            .firstOrNull { it.getInt("id") == session?.optInt("user_id") }?.optString("person_id")
        val board = FamilyTreeView(this, ui, draft, session!!.getString("name"),
            onAdd = {}, onPerson = {}, editable = false)
        content.addView(board, LinearLayout.LayoutParams(-1, ui.dp(440)))
        ui.gap(content, 12)
        ui.button(content, "내 자리로", false) { board.centerOn(draft.selectedId ?: draft.ownerId) }
        ui.label(content, "진한 살구색: 나 · 살구색: 가입한 가족 · 흰색: 빈 가족", 14f, color = ui.muted)
        board.post { board.centerOn(draft.selectedId ?: draft.ownerId) }
    }

    private fun members() {
        navigation("내 설정", tab = 2, name = "members")
        val client = api
        async({ client.request("families/current/") }) { data ->
            room = data
            session?.put("room", data)?.let { sessions.save(it, large) }
            val profile = ui.card(content, stroke = false)
            val intro = ui.row()
            intro.addView(TodakArtView(this, if (large) "grandmother" else "grandchild", 68), LinearLayout.LayoutParams(ui.dp(68), ui.dp(82)))
            val labels = ui.column().apply { setPadding(ui.dp(16), 0, 0, 0) }
            ui.label(labels, session?.optString("name").orEmpty() + "님", if (large) 30f else 26f, true)
            ui.label(labels, room.getString("name"), 16f, color = ui.muted)
            intro.addView(labels, LinearLayout.LayoutParams(0, -2, 1f)); profile.addView(intro)
            ui.gap(content, 20)
            val preferences = ui.card(content)
            val fontChoice = ui.row().apply {
                minimumHeight = ui.dp(if (large) 76 else 56)
                isClickable = true; isFocusable = true
                contentDescription = if (large) "기본 글씨로 보기" else "큰 글씨로 보기"
                setOnClickListener { saveSession(session!!, !large); members() }
            }
            fontChoice.addView(ui.text(if (large) "기본 글씨로 보기" else "큰 글씨로 보기", if (large) 23f else 18f), LinearLayout.LayoutParams(0, -2, 1f))
            fontChoice.addView(IconView(this, "next", ui.ink), LinearLayout.LayoutParams(ui.dp(24), ui.dp(24)))
            preferences.addView(fontChoice)
            ui.label(preferences, "글씨와 버튼 이름을 더 크게 표시해요.", 14f, color = ui.muted)
            ui.gap(content, 20)
            val invitationCard = ui.card(content, ui.blush, padding = 20, stroke = false)
            ui.label(invitationCard, "가족을 초대해 보세요", 20f, true, ui.coralDeep)
            ui.gap(invitationCard, 8)
            ui.label(invitationCard, "초대 코드  " + room.optString("invite_code"), 18f, color = ui.coralDeep)
            ui.button(invitationCard, "초대 코드 확인") { invite() }
            ui.gap(content, 20)
            ui.label(content, "우리 가족", 20f, true)
            ui.button(content, "가계도 보기", false) { familyTree() }
            ui.gap(content, 12)
            objects(room.getJSONArray("members")).forEach { m ->
                val row = ui.column(16).apply { background = ui.shape(ui.paper, 20, stroke = true) }
                ui.label(row, m.getString("name"), 22f, true)
                ui.label(row, m.getString("relationship"), 17f, color = ui.muted)
                content.addView(row); ui.gap(content, 12)
            }
            ui.gap(content)
            ui.button(content, "내 계정 수정", false) { editAccount() }
            val owner = objects(room.getJSONArray("members")).firstOrNull { it.getBoolean("is_owner") }
            if (owner?.getInt("id") == session?.getInt("user_id")) {
                ui.button(content, "하루 요약 시간  ·  " + room.getString("digest_time"), false) {
                    val parts = room.getString("digest_time").split(":")
                    TimePickerDialog(this, { _, h, m ->
                        val time = "%02d:%02d".format(h, m)
                        async({ client.request("families/current/", "PATCH", json("digest_time" to time)) }) { room = it; members() }
                    }, parts[0].toInt(), parts[1].toInt(), true).show()
                }
            }
            if (BuildConfig.DEBUG) ui.button(content, "테스트 연결 설정", false) { connectionSettings() }
            ui.button(content, "이 휴대폰의 다른 계정으로 보기", false) { accounts() }
            ui.button(content, "로그아웃", false) {
                val client = api
                async({ client.request("accounts/logout/", "POST", JSONObject()) }) {
                    sessions.removeCurrent(); session = null; room = JSONObject(); imageLoader.clear(); welcome()
                }
            }
        }
    }
    private fun accounts() {
        navigation("이 휴대폰의 계정", { if (session == null) welcome() else if (room.has("id")) members() else roomChoice() }, name = "accounts")
        heading("누구의 화면을 볼까요?", "이 휴대폰에서 로그인한 계정만 보여요.")
        sessions.all().forEach { account ->
            val name = account.getString("name") + " (" + account.getString("username") + ")" +
                (account.optJSONObject("room")?.let { " · " + it.optString("name") } ?: "")
            ui.button(content, name, false) {
                saveSession(account, account.optBoolean("large"))
                async({ loadRoom(account) }) { updated ->
                    saveSession(updated, updated.optBoolean("large"))
                    if (room.has("id")) home() else roomChoice()
                }
            }
        }
        ui.gap(content, 24)
        ui.button(content, "다른 계정으로 로그인", false) { login() }
        ui.button(content, "새 계정 만들기", false) { register() }
    }
}
