package kr.talkdock.app

import android.Manifest
import android.app.Activity
import android.app.AlertDialog
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
import kr.talkdock.app.data.*
import kr.talkdock.app.device.Recorder
import kr.talkdock.app.device.Speaker
import kr.talkdock.app.ui.IconView
import kr.talkdock.app.ui.Ui
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
    private val images = Executors.newFixedThreadPool(2)
    private val bitmaps = object : android.util.LruCache<String, Bitmap>(12 * 1024 * 1024) {
        override fun sizeOf(key: String, value: Bitmap) = value.byteCount
    }
    private var session: JSONObject? = null
    private var room = JSONObject()
    private var screen = "welcome"
    private var generation = 0
    private var pageNumber = 0
    private var busy = false
    private var foreground = false
    private var selectedPost: JSONObject? = null
    private var photo: File? = null
    private var pendingPhoto: File? = null
    private var caption = ""
    private var captionInput: EditText? = null
    private var recognized = ""
    private var voiceFromDetail = false
    private var voiceStatus: TextView? = null
    private var voiceText: TextView? = null
    private var joinRoom = JSONObject()
    private var invitation = JSONObject()
    private var pickedSlot: FamilySlot? = null
    private var digestDate = LocalDate.now(ZoneId.of("Asia/Seoul")).toString()
    private var currentBack: (() -> Unit)? = null
    private val large get() = session?.optBoolean("large", false) ?: false
    private val api get() = ApiClient(session?.optString("token", "") ?: "", sessions.serverUrl())
    private val cameraCode = 10
    private val galleryCode = 11
    private val microphoneCode = 12

    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        ui = Ui(this); sessions = SessionStore(this); session = sessions.current()
        session?.optJSONObject("room")?.let { room = it }
        root = FrameLayout(this).apply { setBackgroundColor(Color.WHITE) }
        setContentView(root)
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
        pendingPhoto = state?.getString("pendingPhoto")?.let { File(it) }
        caption = state?.getString("caption", "") ?: ""
        selectedPost = state?.getString("post")?.let { JSONObject(it) }
        val restoredScreen = state?.getString("screen")
        when {
            restoredScreen == "post" && photo != null -> composer()
            restoredScreen == "camera" -> camera()
            restoredScreen == "detail" && selectedPost != null -> detail(selectedPost!!)
            restoredScreen == "senior" && selectedPost != null -> senior(selectedPost!!)
            session != null && session?.optJSONObject("room") != null -> home()
            session != null -> roomChoice()
            else -> welcome()
        }
    }
    override fun onSaveInstanceState(out: Bundle) {
        super.onSaveInstanceState(out)
        out.putString("screen", screen); out.putString("photo", photo?.absolutePath)
        out.putString("pendingPhoto", pendingPhoto?.absolutePath)
        out.putString("caption", captionInput?.text?.toString() ?: caption)
        out.putString("post", selectedPost?.toString())
    }
    override fun onResume() { super.onResume(); foreground = true }
    override fun onPause() {
        foreground = false
        super.onPause(); speaker.stop(); recorder?.cancel()
    }
    override fun onDestroy() {
        speaker.close(); recorder?.close(); recording?.delete(); network.shutdownNow(); images.shutdownNow()
        super.onDestroy()
    }
    private fun toast(message: String) = Toast.makeText(this, message, Toast.LENGTH_LONG).show()
    private fun json(vararg pairs: Pair<String, Any>) = JSONObject().apply { pairs.forEach { put(it.first, it.second) } }
    private fun objects(array: JSONArray): List<JSONObject> = (0 until array.length()).map { array.getJSONObject(it) }
    private fun navigation(title: String, back: (() -> Unit)? = null, tab: Int? = null, name: String) {
        screen = name; pageNumber++; captionInput = null; currentBack = back
        speaker.stop(); recorder?.close(); recorder = null
        recording?.delete(); recording = null
        (getSystemService(INPUT_METHOD_SERVICE) as InputMethodManager).hideSoftInputFromWindow(root.windowToken, 0)
        root.removeAllViews()
        page = ui.column(); root.addView(page, FrameLayout.LayoutParams(-1, -1))
        val header = ui.row().apply { setPadding(ui.dp(14), ui.dp(4), ui.dp(14), ui.dp(4)); minimumHeight = ui.dp(64) }
        if (back != null) header.addView(ui.iconButton("back", "이전 화면") { back() })
        header.addView(ui.text(title, 23f, true), LinearLayout.LayoutParams(0, -2, 1f))
        if (tab == 0) {
            header.addView(ui.iconButton("refresh", "가족 소식 새로고침") { home() })
            header.addView(ui.iconButton("camera", "오늘 기록하기") { camera() })
        }
        page.addView(header)
        val scroll = ScrollView(this).apply { isFillViewport = true; clipToPadding = false }
        content = ui.column().apply { setPadding(ui.dp(22), ui.dp(12), ui.dp(22), ui.dp(30)) }
        scroll.addView(content)
        page.addView(scroll, LinearLayout.LayoutParams(-1, 0, 1f))
        if (tab != null) bottomBar(tab)
    }
    private fun bottomBar(selected: Int) {
        ui.line(page)
        val row = ui.row()
        val titles = listOf("가족 소식", "하루 요약", "우리 가족")
        val symbols = listOf("feed", "digest", "family")
        titles.forEachIndexed { i, title ->
            val item = ui.column(4).apply {
                gravity = Gravity.CENTER; minimumHeight = ui.dp(76)
                background = ui.shape(if (selected == i) ui.sage else Color.WHITE)
                isClickable = true; isFocusable = true; contentDescription = title
                setOnClickListener { when (i) { 0 -> home(); 1 -> digest(); else -> members() } }
            }
            item.addView(IconView(this, symbols[i], if (selected == i) ui.green else ui.muted), LinearLayout.LayoutParams(ui.dp(30), ui.dp(30)))
            val text = ui.text(title, 13f, selected == i, if (selected == i) ui.green else ui.muted).apply { gravity = Gravity.CENTER }
            item.addView(text)
            row.addView(item, LinearLayout.LayoutParams(0, -2, 1f))
        }
        page.addView(row)
    }
    private fun heading(text: String, sub: String? = null) {
        ui.label(content, text, if (large) 30f else 28f, true); ui.gap(content, 12)
        if (sub != null) { ui.label(content, sub, if (large) 21f else 17f, color = ui.muted); ui.gap(content, 24) }
    }
    private fun <T> async(work: () -> T, message: String = "잠시만 기다려 주세요.", complete: (T) -> Unit) {
        if (busy) return
        busy = true
        val number = pageNumber
        val cover = ui.column(24).apply {
            gravity = Gravity.CENTER
            setBackgroundColor(Color.argb(235, 255, 255, 255)); isClickable = true; isFocusable = true
            addView(ProgressBar(this@MainActivity), LinearLayout.LayoutParams(ui.dp(48), ui.dp(48)))
            ui.gap(this, 20); ui.label(this, message, 19f, true)
        }
        root.addView(cover, FrameLayout.LayoutParams(-1, -1))
        network.execute {
            val result = runCatching { work() }
            runOnUiThread {
                busy = false; root.removeView(cover)
                if (isDestroyed || number != pageNumber) return@runOnUiThread
                result.fold({ complete(it) }, { error ->
                    if (error is ApiException && error.status == 401 && screen !in listOf("login", "register")) {
                        val username = session?.optString("username").orEmpty()
                        val userId = session?.optInt("user_id")
                        val big = large
                        sessions.removeCurrent(); session = null; room = JSONObject(); bitmaps.evictAll()
                        login(username, userId, big)
                        AlertDialog.Builder(this).setTitle("로그인이 만료되었어요")
                            .setMessage("비밀번호를 입력해 다시 로그인해 주세요.")
                            .setPositiveButton("확인", null).show()
                    } else {
                        val message = (error as? ApiException)?.message ?: "서버에 연결하지 못했어요. 인터넷 연결을 확인하고 다시 시도해 주세요."
                        AlertDialog.Builder(this).setTitle("다시 확인해 주세요").setMessage(message)
                            .setPositiveButton("확인", null).show()
                    }
                })
            }
        }
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
                bitmaps.evictAll(); dialog.dismiss()
                if (session == null) welcome() else if (room.has("id")) members() else roomChoice()
            }
        }
        dialog.show()
    }
    private fun remotePhoto(view: ImageView, post: JSONObject) {
        val url = post.getString("image_url")
        val client = api; val key = client.token.hashCode().toString() + url; val number = pageNumber
        bitmaps.get(key)?.let { view.setImageBitmap(it); return }
        view.contentDescription = post.optString("author_name") + "님의 사진"
        images.execute {
            val bitmap = runCatching {
                val data = client.image(url)
                BitmapFactory.decodeByteArray(data, 0, data.size, BitmapFactory.Options().apply { inSampleSize = 2 })
            }.getOrNull()
            runOnUiThread {
                if (number == pageNumber && !isDestroyed) {
                    if (bitmap != null) { bitmaps.put(key, bitmap); view.setImageBitmap(bitmap) }
                    else {
                        view.contentDescription = "사진을 불러오지 못했어요."; view.setImageDrawable(null)
                        val parent = view.parent as? LinearLayout
                        parent?.addView(ui.text("사진을 불러오지 못했어요. 소식을 눌러 다시 확인해 주세요.", 15f, color = ui.muted), parent.indexOfChild(view) + 1)
                    }
                }
            }
        }
    }
    private fun saveSession(value: JSONObject, big: Boolean) {
        sessions.save(value, big); session = value; room = value.optJSONObject("room") ?: JSONObject()
        bitmaps.evictAll()
    }
    private fun saveRoom(value: JSONObject, big: Boolean = large) {
        val account = session ?: return
        account.put("room", value.getJSONObject("room"))
        saveSession(account, big)
    }
    private fun loadRoom(account: JSONObject): JSONObject {
        val client = ApiClient(account.getString("token"), sessions.serverUrl())
        val currentRoom = try { client.request("families/current/") }
            catch (error: ApiException) { if (error.status == 403) null else throw error }
        account.remove("room")
        if (currentRoom != null) account.put("room", currentRoom)
        return account
    }
    private fun roomChoice() {
        navigation("가족 방", { welcome() }, name = "roomChoice")
        heading(session?.optString("name", "가족") + "님,\n가족 방에 연결해 주세요.", "방을 만들거나 초대코드로 가족의 방에 들어갈 수 있어요.")
        ui.button(content, "우리 가족 방 만들기") { create() }
        ui.button(content, "초대받은 방에 들어가기", false) { join() }
        ui.gap(content)
        ui.button(content, "다른 계정으로 로그인", false) { login() }
        if (BuildConfig.DEBUG) ui.button(content, "테스트 연결 설정", false) { connectionSettings() }
    }
    private fun welcome() {
        navigation("토닥", name = "welcome")
        ui.gap(content, 24)
        heading("가족의 하루를\n두드려 주세요!", "사진 한 장과 짧은 이야기로\n가족의 일상을 함께 나눠요.")
        ui.photo(content, 224).setImageResource(R.drawable.family)
        ui.gap(content, 24)
        ui.button(content, "로그인") { login() }
        ui.button(content, "새 계정 만들기", false) { register() }
        ui.gap(content, 16)
        if (sessions.all().isNotEmpty()) ui.button(content, "이 휴대폰의 계정으로 돌아가기", false) { accounts() }
        if (BuildConfig.DEBUG) ui.button(content, "테스트 연결 설정", false) { connectionSettings() }
    }
    private fun register() {
        navigation("계정 만들기", { welcome() }, name = "register")
        heading("먼저 내 계정을\n만들어 주세요.", "아이디와 비밀번호로 다음에도 로그인할 수 있어요.")
        val username = ui.input(content, "아이디", "로그인할 아이디", identifier = true)
        val password = ui.input(content, "계정 비밀번호", "10자 이상", password = true)
        val name = ui.input(content, "내 이름", "예: 홍정아")
        ui.label(content, "가족에게 표시할 관계", 16f, true)
        val genders = Spinner(this)
        genders.adapter = ArrayAdapter(this, android.R.layout.simple_spinner_dropdown_item, listOf("자녀 · 손주로 표시", "아들 · 손자로 표시", "딸 · 손녀로 표시"))
        content.addView(genders, LinearLayout.LayoutParams(-1, ui.dp(56)))
        ui.gap(content)
        ui.button(content, "계정 만들기") {
            if (username.text.isBlank() || password.text.isBlank() || name.text.isBlank()) {
                toast("아이디, 비밀번호, 이름을 입력해 주세요."); return@button
            }
            val data = json("username" to username.text.toString().trim(), "password" to password.text.toString(),
                "name" to name.text.toString().trim(), "gender" to listOf("unknown", "male", "female")[genders.selectedItemPosition])
            val client = ApiClient(baseUrl = sessions.serverUrl())
            async({ client.request("accounts/register/", "POST", data) }) {
                saveSession(it, false); roomChoice()
            }
        }
    }
    private fun login(initialUsername: String = "", expiredUserId: Int? = null, expiredLarge: Boolean = false) {
        navigation("로그인", { welcome() }, name = "login")
        heading("다시 만나서\n반가워요.")
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
        heading("우리 가족만의 방을\n만들어볼까요?", "가족이 초대코드와 비밀번호로 들어올 수 있어요.")
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
                saveRoom(it); invite(password.text.toString())
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
        heading("가족이 보내준\n초대를 확인해 주세요.")
        val code = ui.input(content, "초대코드", "예: ABC123")
        val password = ui.input(content, "가족 방 비밀번호", "가족이 알려준 비밀번호", password = true)
        ui.button(content, "가족 방 확인하기") {
            if (code.text.isBlank() || password.text.isBlank()) { toast("초대코드와 비밀번호를 입력해 주세요."); return@button }
            invitation = json("invite_code" to code.text.toString().trim().uppercase(), "password" to password.text.toString())
            async({ ApiClient(baseUrl = sessions.serverUrl()).request("families/lookup/", "POST", invitation) }) {
                joinRoom = it; generation = 0; tree()
            }
        }
    }
    private fun tree() {
        navigation("가족에서 내 자리", { join() }, name = "tree")
        val creator = joinRoom.getString("owner_name")
        val list = objects(joinRoom.getJSONArray("members"))
        heading(FamilyLogic.introduction(creator, list.filter { !it.getBoolean("is_owner") }.map { it.getString("name") }),
            "위아래 화살표로 움직여\n가족에서 내 자리를 선택해 주세요.")
        val board = ui.column(16).apply { background = ui.shape(ui.sage); gravity = Gravity.CENTER }
        content.addView(board, LinearLayout.LayoutParams(-1, -2))
        val levels = mapOf(2 to "두 세대 위", 1 to "한 세대 위", 0 to "기준", -1 to "한 세대 아래", -2 to "두 세대 아래")
        fun choices() {
            ui.label(board, levels[generation] ?: "", 16f, color = ui.muted)
            FamilyLogic.slots.filter { it.generation == generation }.forEach { slot ->
                val member = list.firstOrNull { it.optString("slot") == slot.key }
                val qualifier = when (slot.key) { "grandma-father" -> " · 아버지 쪽"; "grandma-mother" -> " · 어머니 쪽"; else -> "" }
                val button = ui.button(board, if (member == null) slot.label + qualifier else member.getString("name") + " · 가입한 가족", false) {
                    pickedSlot = slot; profile()
                }
                if (member != null) { button.isEnabled = false; button.alpha = .45f }
            }
        }
        if (generation > 0) { choices(); ui.gap(board, 20); ui.line(board); ui.gap(board, 20) }
        board.addView(ui.iconButton("up", "한 세대 위로") { if (generation < 2) { generation++; tree() } else toast("두 세대 위까지 선택할 수 있어요.") })
        val owner = ui.text(creator, 24f, true, ui.green).apply {
            gravity = Gravity.CENTER; setPadding(ui.dp(24), ui.dp(20), ui.dp(24), ui.dp(20)); background = ui.shape(Color.WHITE, stroke = true)
            isClickable = true; isFocusable = true; contentDescription = creator + " 기준으로 돌아가기"
            setOnClickListener { generation = 0; tree() }
        }
        board.addView(owner, LinearLayout.LayoutParams(-1, -2))
        ui.gap(board, 16)
        board.addView(ui.iconButton("down", "한 세대 아래로") { if (generation > -2) { generation--; tree() } else toast("두 세대 아래까지 선택할 수 있어요.") })
        if (generation < 0) { ui.gap(board, 20); ui.line(board); ui.gap(board, 20); choices() }
        ui.label(board, "이름을 누르면 기준 자리로 돌아와요.", 15f, color = ui.muted)
        ui.gap(content, 20)
        if (generation == 0) ui.label(content, "할머니라면 위 화살표를 두 번 눌러 주세요.", 17f, color = ui.muted)
    }
    private fun profile() {
        val slot = pickedSlot ?: return
        navigation("가족 방 참여", { tree() }, name = "profile")
        heading(joinRoom.getString("owner_name") + "님의\n" + slot.relation + "로 함께해요.")
        val big = Switch(this).apply { text = "큰 글씨로 보기"; textSize = 20f; typeface = ui.font; fontVariationSettings = "'wght' 400"; isChecked = slot.generation == 2; minimumHeight = ui.dp(64) }
        content.addView(big); ui.gap(content, 24)
        ui.button(content, "가족 방에 들어가기") {
            val data = JSONObject(invitation.toString()).put("slot", slot.key)
            val client = api
            async({ client.request("families/join/", "POST", data) }) { saveRoom(it, big.isChecked); home() }
        }
    }
    private fun home() {
        navigation("토닥", tab = 0, name = "home")
        val client = api
        async({ client.request("posts/") }) { data ->
            if (large) {
                heading(FamilyLogic.shortName(session!!.getString("name")) + "님,\n가족 소식이 도착했어요.")
            } else {
                ui.label(content, room.optString("name", "우리 가족") + "의 하루", 20f, true)
                ui.gap(content, 14)
            }
            val posts = objects(data.getJSONArray("posts"))
            if (posts.isEmpty()) {
                ui.photo(content, 200).setImageResource(R.drawable.family); ui.gap(content, 24)
                heading("첫 번째 가족 소식을\n남겨 주세요.", "사진 한 장부터 시작해볼까요?")
                ui.button(content, "오늘 기록하기") { camera() }
            }
            posts.forEach { post ->
                author(content, post)
                val image = ui.photo(content, square = true)
                remotePhoto(image, post)
                image.isClickable = true; image.isFocusable = true
                image.setOnClickListener { if (large) senior(post) else detail(post) }
                ui.gap(content, 14)
                val text = post.optString("caption").ifBlank { "사진으로 남긴 오늘의 하루" }
                ui.label(content, text, if (large) 23f else 18f)
                ui.gap(content, 8)
                ui.button(content, if (large) "소식 듣고 답장하기" else "댓글 " + post.getInt("comment_count") + "개 · 소식 보기", false) {
                    if (large) senior(post) else detail(post)
                }
                ui.gap(content, 26); ui.line(content); ui.gap(content, 26)
            }
        }
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
    private fun detail(post: JSONObject) {
        selectedPost = post
        navigation("가족 소식", { home() }, name = "detail")
        val client = api
        async({ client.request("posts/" + post.getInt("id") + "/") }) { data ->
            selectedPost = data; author(content, data)
            remotePhoto(ui.photo(content, square = true), data); ui.gap(content)
            ui.label(content, data.getString("caption").ifBlank { "사진으로 남긴 오늘의 하루" }, if (large) 23f else 19f)
            ui.gap(content)
            ui.button(content, "소식 듣기", false) { senior(data) }
            ui.gap(content, 24); ui.label(content, "가족 댓글", 21f, true)
            ui.label(content, "이 글의 댓글은 가족 모두가 볼 수 있어요.", 15f, color = ui.muted); ui.gap(content)
            val comments = objects(data.getJSONArray("comments"))
            if (comments.isEmpty()) ui.label(content, "첫 댓글을 남겨 주세요.", 17f, color = ui.muted)
            comments.forEach { c ->
                ui.label(content, c.getString("author_name") + " · " + c.getString("relationship"), 16f, true)
                ui.label(content, c.getString("text"), if (large) 23f else 18f)
                ui.gap(content); ui.line(content); ui.gap(content)
            }
            val text = ui.input(content, "댓글 남기기", "가족에게 하고 싶은 말", multiline = true)
            ui.button(content, "글로 댓글 보내기") {
                if (text.text.isBlank()) { toast("댓글을 입력해 주세요."); return@button }
                val body = json("text" to text.text.toString())
                async({ client.request("posts/" + data.getInt("id") + "/comments/", "POST", body) }) { toast("가족에게 댓글을 보냈어요."); detail(data) }
            }
            ui.button(content, "말로 댓글 남기기", false) { voice(data, fromDetail = true) }
        }
    }
    private fun camera() {
        navigation("오늘 기록하기", { home() }, name = "camera")
        heading("오늘의 순간을\n사진으로 남겨 주세요.", "아래 버튼을 누르면 휴대폰 카메라가 열려요.")
        val box = FrameLayout(this).apply { background = ui.shape(Color.rgb(37, 45, 42)); minimumHeight = ui.dp(310) }
        val icon = IconView(this, "camera", Color.WHITE)
        box.addView(icon, FrameLayout.LayoutParams(ui.dp(80), ui.dp(80), Gravity.CENTER)); content.addView(box)
        ui.gap(content, 24)
        ui.button(content, "사진 촬영하기") { launchCamera() }
        ui.button(content, "사진첩에서 고르기", false) { launchGallery() }
    }
    private fun launchGallery() {
        val intent = Intent(Intent.ACTION_OPEN_DOCUMENT).apply { type = "image/*"; addCategory(Intent.CATEGORY_OPENABLE) }
        runCatching { startActivityForResult(intent, galleryCode) }.onFailure { toast("사진첩을 열 수 없어요.") }
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
                if (photo != output) photo?.delete()
                photo = output; composer()
            } else { output?.delete(); if (photo != null) composer() else camera() }
        }
        if (requestCode == galleryCode && resultCode == RESULT_OK) {
            val uri = data?.data ?: return
            val directory = File(filesDir, "camera").apply { mkdirs() }
            val output = File.createTempFile("picked-", ".jpg", directory)
            async({
                try {
                    contentResolver.openInputStream(uri)?.use { source ->
                        output.outputStream().use { destination ->
                            val buffer = ByteArray(8192); var total = 0
                            while (true) {
                                val count = source.read(buffer); if (count < 0) break
                                total += count
                                if (total > 10 * 1024 * 1024) throw ApiException("사진은 10MB까지 선택할 수 있어요.")
                                destination.write(buffer, 0, count)
                            }
                        }
                    } ?: throw ApiException("사진을 읽지 못했어요.")
                    output
                } catch (error: Exception) { output.delete(); throw error }
            }) { photo?.delete(); photo = it; composer() }
        }
    }
    private fun composer() {
        val file = photo ?: return camera()
        navigation("사진 올리기", { discardPhoto() }, name = "post")
        heading("가족에게 보여줄\n오늘의 이야기")
        val preview = ui.photo(content, square = true)
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeFile(file.absolutePath, bounds)
        var sample = 1
        while (maxOf(bounds.outWidth, bounds.outHeight) / sample > 1600) sample *= 2
        val options = BitmapFactory.Options().apply { inSampleSize = sample }
        val bitmap = BitmapFactory.decodeFile(file.absolutePath, options)
        if (bitmap == null) { toast("읽을 수 없는 사진이에요. 다시 골라 주세요."); file.delete(); photo = null; camera(); return }
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
        preview.setImageBitmap(upright)
        ui.gap(content, 24)
        val text = ui.input(content, "함께 남길 이야기 · 선택", "학교에서 점심 먹었어요", multiline = true, initial = caption)
        captionInput = text
        ui.button(content, "가족에게 사진 올리기") {
            caption = text.text.toString()
            if (caption.length > 2000) { toast("이야기는 2,000자까지 남길 수 있어요."); return@button }
            val client = api
            async({ client.upload(file, caption) }) {
                file.delete(); photo = null; caption = ""; toast("가족에게 사진을 올렸어요."); home()
            }
        }
        ui.button(content, "다시 촬영하기", false) { caption = text.text.toString(); launchCamera() }
        ui.button(content, "사진첩에서 바꾸기", false) { caption = text.text.toString(); launchGallery() }
    }
    private fun discardPhoto() {
        AlertDialog.Builder(this).setTitle("사진 올리기를 그만할까요?")
            .setPositiveButton("그만하기") { _, _ -> photo?.delete(); photo = null; caption = ""; home() }
            .setNegativeButton("계속 쓰기", null).show()
    }
    private fun senior(post: JSONObject, retry: Boolean = false) {
        selectedPost = post
        navigation("가족 소식 듣기", { if (large) home() else detail(post) }, name = "senior")
        author(content, post); remotePhoto(ui.photo(content, square = true), post); ui.gap(content, 24)
        val summary = ui.note(content, "가족 소식을 준비하고 있어요.", true)
        val client = api
        async({ client.request("posts/" + post.getInt("id") + "/message/", if (retry) "POST" else "GET", if (retry) JSONObject() else null) }) { data ->
            val ready = data.getString("status") == "ready"
            val processing = data.getString("status") == "processing"
            summary.text = when {
                ready -> data.getString("text")
                processing -> "가족 소식을 준비하고 있어요."
                else -> "설명을 준비하지 못했어요.\n다시 시도해 주세요."
            }
            ui.gap(content, 16)
            if (ready) listen(content, data.getString("text"), "소리로 듣기", 76)
            else {
                ui.button(content, if (processing) "다시 확인하기" else "설명 다시 준비하기", false, 76) { senior(post, !processing) }
                if (post.optString("caption").isNotBlank()) listen(content, post.getString("caption"), "가족이 쓴 글 듣기", 76)
            }
            ui.button(content, "말로 답장하기", height = 76) { voice(post) }
            ui.button(content, "가족 댓글 보기", false, 68) { detail(post) }
        }
    }
    private fun voice(post: JSONObject, fromDetail: Boolean = false) {
        selectedPost = post; recognized = ""; voiceFromDetail = fromDetail
        navigation("말로 답장하기", { leaveVoice(post) }, name = "voice")
        heading(post.getString("author_name") + "님에게\n하고 싶은 말을 들려주세요.")
        ui.label(content, "답장은 이 소식의 가족 댓글로 올라가요.", 19f, color = ui.muted)
        ui.gap(content, 24)
        voiceStatus = ui.label(content, "아래 버튼을 눌러 말씀해 주세요.", 22f, true)
        ui.gap(content, 24)
        voiceText = ui.note(content, "예: 정아가 고생했다고 전해줘", true)
        ui.gap(content, 24)
        ui.button(content, "말하기 시작", height = 76) { startVoice(post) }
        ui.button(content, "다 말했어요", height = 76) {
            if (recognized.isNotBlank()) prepareVoice(post)
            else {
                if (recorder?.active == true) finishRecording()
                val audio = recording
                if (audio == null) toast("말하기 시작을 누르고 말씀해 주세요.")
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
        }
        ui.button(content, "취소하기", false, 68) { leaveVoice(post) }
    }
    private fun leaveVoice(post: JSONObject) {
        if (voiceFromDetail) detail(post) else senior(post)
    }
    private fun finishRecording() {
        recording = runCatching { recorder?.finish() }.getOrNull()
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
        author(content, post); remotePhoto(ui.photo(content, 170), post); ui.gap(content, 24)
        ui.label(content, "내가 한 말", 18f, color = ui.muted); ui.gap(content, 8)
        ui.note(content, draft.getString("recognized"), true); ui.gap(content, 24)
        ui.label(content, "가족에게 전할 댓글", 18f, color = ui.muted); ui.gap(content, 8)
        ui.note(content, draft.getString("converted"), true); ui.gap(content, 24)
        listen(content, draft.getString("converted"), "댓글 소리로 확인하기", 68)
        ui.button(content, "가족에게 보내기", height = 76) {
            val client = api
            async({ client.request("replies/" + draft.getInt("id") + "/send/", "POST", JSONObject()) }) {
                toast("가족에게 댓글을 보냈어요."); detail(post)
            }
        }
        ui.button(content, "다시 말하기", false, 76) { voice(post, voiceFromDetail) }
        ui.button(content, "취소하기", false, 68) { leaveVoice(post) }
    }
    private fun digest(date: String = digestDate, retry: Boolean = false) {
        digestDate = date
        navigation("하루 요약", tab = 1, name = "digest")
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
                    ui.gap(content, 24); ui.label(content, "요약에 함께한 사진", 20f, true); ui.gap(content)
                    objects(data.getJSONArray("posts")).forEach { p ->
                        val image = ui.photo(content, 164); remotePhoto(image, p)
                        image.isClickable = true; image.isFocusable = true
                        image.setOnClickListener { if (large) senior(p) else detail(p) }
                        ui.label(content, p.getString("author_name"), 16f); ui.gap(content, 20)
                    }
                }
                "pending" -> ui.note(content, "오늘 " + data.getString("digest_time") + "에\n하루 요약이 도착해요.", large)
                "processing" -> { ui.note(content, "하루 요약을 준비하고 있어요.", large); ui.button(content, "다시 확인하기", false) { digest(date) } }
                "empty" -> ui.note(content, "이날은 아직 가족이 남긴 소식이 없어요.", large)
                else -> { ui.note(content, "하루 요약을 준비하지 못했어요. 다시 시도해 주세요.", large); ui.button(content, "요약 다시 준비하기", false) { digest(date, true) } }
            }
        }
    }
    private fun members() {
        navigation("우리 가족", tab = 2, name = "members")
        val client = api
        async({ client.request("families/current/") }) { data ->
            room = data
            session?.put("room", data)?.let { sessions.save(it, large) }
            heading(room.getString("name"))
            objects(room.getJSONArray("members")).forEach { m ->
                val row = ui.column(16).apply { background = ui.shape(ui.sage) }
                ui.label(row, m.getString("name"), 22f, true)
                ui.label(row, m.getString("relationship"), 17f, color = ui.muted)
                content.addView(row); ui.gap(content, 12)
            }
            ui.gap(content)
            ui.button(content, "가족 초대하기", false) { invite() }
            ui.button(content, if (large) "기본 글씨로 보기" else "큰 글씨로 보기", false) {
                saveSession(session!!, !large); members()
            }
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
                    sessions.removeCurrent(); session = null; room = JSONObject(); bitmaps.evictAll(); welcome()
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
