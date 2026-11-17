package kr.talkdock.app.ui

import android.Manifest
import android.content.pm.PackageManager
import android.view.View
import android.widget.*
import kr.talkdock.app.data.ApiClient
import kr.talkdock.app.device.Recorder
import java.io.File
import java.util.concurrent.ExecutorService
import java.util.concurrent.Future

/** A reviewed, editable transcript is inserted into the post only by an explicit tap. */
class PostVoiceInput(
    private val ui: Ui, large: Boolean, private val client: ApiClient,
    private val executor: ExecutorService, private val requestPermission: () -> Unit,
    initial: String, private val remember: (String) -> Unit, private val beforeRecording: () -> Unit,
    private val insert: (String) -> Boolean,
) : LinearLayout(ui.context) {
    private val status: TextView
    private val toggle: Button
    private var recorder: Recorder? = null
    private var task: Future<*>? = null
    private var epoch = 0
    private var stopped = false
    private var preview: EditText? = null
    private val review = ui.column()

    init {
        orientation = VERTICAL
        toggle = ui.button(this, "말로 쓰기", false, if (large) 76 else 56) {
            if (recorder?.active == true) finish() else start()
        }
        status = ui.label(this, "말씀을 글로 바꾼 뒤 확인하고 넣을 수 있어요.", if (large) 18f else 14f, color = ui.muted)
        status.accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
        addView(review)
        if (initial.isNotBlank()) showReview(initial)
    }

    fun start() {
        if (stopped || task?.isDone == false) return
        if (context.checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestPermission(); return
        }
        beforeRecording()
        recorder?.close()
        recorder = Recorder(context) { post { finish() } }
        runCatching { recorder!!.start() }.fold({
            toggle.text = "말하기 마치기"
            status.text = "듣고 있어요 · 최대 1분. 마치기를 누르면 글로 바꿔요."
        }, { status.text = "마이크 사용을 허용하고 다시 말해 주세요." })
    }

    private fun finish() {
        if (recorder?.active != true) return
        val audio = runCatching { recorder!!.finish() }.getOrNull()
        toggle.text = "말로 쓰기"
        if (audio == null) { status.text = "조금 더 길게 다시 말씀해 주세요."; return }
        transcribe(audio)
    }

    private fun transcribe(audio: File) {
        val request = ++epoch
        toggle.isEnabled = false; status.text = "말씀을 글로 바꾸고 있어요."
        task = executor.submit {
            val result = runCatching { client.transcribePost(audio).getString("recognized") }
            audio.delete()
            post {
                if (stopped || request != epoch) return@post
                toggle.isEnabled = true
                result.fold({ showReview(it) }, { status.text = it.message ?: "다시 말하기를 눌러 녹음해 주세요." })
            }
        }
    }

    private fun showReview(text: String) {
        review.removeAllViews()
        status.text = "잘못 들은 부분을 고치고 ‘글에 넣기’를 눌러 주세요."
        preview = ui.input(review, "말씀하신 내용", "내용을 확인해 주세요", multiline = true, initial = text).apply {
            tag = "post-voice-transcript"
            addTextChangedListener(object : android.text.TextWatcher {
                override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) = Unit
                override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) { remember(s.toString()) }
                override fun afterTextChanged(s: android.text.Editable?) = Unit
            })
        }
        remember(text)
        ui.button(review, "글에 넣기", false) {
            val value = preview?.text?.toString()?.trim().orEmpty()
            if (value.isBlank()) { preview?.error = "넣을 내용을 입력해 주세요."; return@button }
            if (!insert(value)) { preview?.error = "소식은 모두 2,000자까지 쓸 수 있어요. 내용을 줄여 주세요."; return@button }
            remember(""); preview = null; review.removeAllViews()
            status.text = "글에 넣었어요. 내용을 확인한 뒤 가족에게 전해 주세요."
        }
        ui.ghost(review, "음성 글 지우기") { remember(""); preview = null; review.removeAllViews() }
    }

    fun pauseRecording() {
        if (recorder?.active == true) {
            recorder?.cancel(); toggle.text = "말로 쓰기"
            status.text = "녹음이 중단됐어요. 말로 쓰기를 다시 눌러 주세요."
        }
    }

    fun close() { stopped = true; epoch++; recorder?.close(); task?.cancel(true) }
    override fun onDetachedFromWindow() { close(); super.onDetachedFromWindow() }
}
