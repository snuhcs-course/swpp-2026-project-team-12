package kr.talkdock.app.ui

import android.app.Activity
import android.view.View
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import kr.talkdock.app.data.Telemetry
import kr.talkdock.app.data.ApiClient
import kr.talkdock.app.data.ApiException
import kr.talkdock.app.device.Recorder
import org.json.JSONObject
import java.util.concurrent.ExecutorService
import java.util.concurrent.Future

/**
 * Elderly feed reply: typing or speaking happens inside the post card, so replying never
 * opens another screen. A spoken reply is always shown for confirmation before sending.
 * Sending itself is handed to the app's background posting queue.
 */
class ElderReplyPanel(
    private val activity: Activity,
    private val ui: Ui,
    private val post: JSONObject,
    private val client: ApiClient,
    private val executor: ExecutorService,
    private val hasMicrophone: () -> Boolean,
    private val requestMicrophone: (ElderReplyPanel) -> Unit,
    private val beforeRecording: () -> Unit,
    private val close: () -> Unit,
    private val login: () -> Unit,
    private val submitText: (String) -> Unit,
    private val submitVoice: (JSONObject) -> Unit,
) : LinearLayout(activity) {
    private enum class Stage { IDLE, RECORDING, CONVERTING, REVIEW }

    private var stage = Stage.IDLE
    private var voiceOperation: Telemetry.Operation? = null
    private var recorder: Recorder? = null
    private var task: Future<*>? = null
    private var generation = 0
    private var draft: JSONObject? = null
    private var message = ""
    val composer = CommentComposer(activity, ui, true, title = "", hintText = "하고 싶은 말씀을 적어보세요",
        compact = true) { text -> sendText(text) }
    val inUse get() = stage != Stage.IDLE || composer.input.text.isNotBlank()

    init {
        orientation = VERTICAL
        tag = "elder-reply:${post.optInt("id")}"
        // Taps inside the panel must not fall through to the card, which opens the detail screen.
        isClickable = true
        setPadding(0, ui.dp(14), 0, 0)
        composer.tag = "elder-reply-text"
        render()
    }

    private fun render() {
        removeAllViews()
        val header = ui.row()
        header.addView(ui.text(post.optString("author_name") + "님에게 답장", 21f, true),
            LayoutParams(0, -2, 1f))
        header.addView(ui.iconButton("close", "답장 닫기") { cancel(); close() })
        addView(header, LayoutParams(-1, -2))
        ui.gap(this, 10)
        when (stage) {
            Stage.IDLE -> idle()
            Stage.RECORDING -> recording()
            Stage.CONVERTING -> waiting("말씀을 글로 바꾸고 있어요.")
            Stage.REVIEW -> review()
        }
    }

    private fun status(text: String, size: Float = 20f, bold: Boolean = false): TextView =
        ui.label(this, text, size, bold, if (bold) ui.ink else ui.muted).apply {
            accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
        }

    private fun idle() {
        (composer.parent as? LinearLayout)?.removeView(composer)
        ui.button(this, "말로 답하기", true, 76) { startRecording() }.apply {
            tag = "elder-reply-voice"; contentDescription = "말로 답하기"
        }
        if (message.isNotBlank()) { ui.gap(this, 8); status(message, 19f).setTextColor(ui.coralDeep) }
        ui.gap(this, 14)
        ui.label(this, "글로 쓰셔도 돼요", 18f, color = ui.muted)
        ui.gap(this, 8)
        addView(composer, LayoutParams(-1, -2))
    }

    private fun recording() {
        status("듣고 있어요", 23f, true)
        ui.gap(this, 4)
        status("다 말씀하시면 아래 버튼을 눌러 주세요. 최대 1분이에요.", 18f)
        ui.button(this, "■ 다 말했어요", true, 76) { finishRecording() }.apply {
            tag = "elder-reply-finish"; contentDescription = "다 말했어요"
        }
        ui.ghost(this, "취소", 64) { cancel(); render() }
    }

    private fun waiting(text: String) {
        val row = ui.row()
        row.addView(ProgressBar(activity).apply { indeterminateTintList = android.content.res.ColorStateList.valueOf(ui.coralDeep) },
            LayoutParams(ui.dp(32), ui.dp(32)))
        row.addView(ui.text(text, 20f).apply { setPadding(ui.dp(12), 0, 0, 0); tag = "elder-reply-waiting" })
        addView(row, LayoutParams(-1, -2))
    }

    private fun review() {
        val value = draft ?: return
        status("이렇게 보낼게요", 21f, true)
        ui.gap(this, 8)
        ui.note(this, value.optString("converted").ifBlank { value.optString("recognized") }, true)
        if (message.isNotBlank()) { ui.gap(this, 8); status(message, 19f).setTextColor(ui.coralDeep) }
        ui.button(this, "가족에게 보내기", true, 76) { sendDraft() }.apply { tag = "elder-reply-send" }
        ui.ghost(this, "다시 말하기", 64) { startRecording() }
    }

    fun startRecording() {
        if (stage == Stage.CONVERTING) return
        if (voiceOperation == null) voiceOperation = Telemetry.start("voice_reply")
        if (!hasMicrophone()) { requestMicrophone(this); return }
        cancel()
        beforeRecording()
        val request = generation
        val engine = Recorder(activity) { activity.runOnUiThread { if (request == generation && recorder?.active == true) finishRecording() } }
        recorder = engine
        runCatching { engine.start(voiceOperation) }.fold({ stage = Stage.RECORDING; message = "" }, {
            recorder = null; stage = Stage.IDLE; message = "녹음을 시작하지 못했어요. 마이크 사용을 확인해 주세요."
        })
        render()
    }

    fun microphoneDenied() {
        voiceOperation?.stage("microphone_permission", "error", fields = mapOf("error_code" to "permission_denied"))
        voiceOperation = null
        stage = Stage.IDLE; message = "말로 답장하려면 마이크 사용을 허용해 주세요."; render()
    }

    private fun finishRecording() {
        val audio = runCatching { recorder?.finish() }.getOrNull()
        val operation = recorder?.operation ?: Telemetry.start("voice_reply")
        recorder = null
        val tracked = client.tracked(operation)
        if (audio == null) { stage = Stage.IDLE; message = "조금 더 길게 다시 말씀해 주세요."; render(); return }
        stage = Stage.CONVERTING; message = ""; render()
        val request = ++generation
        task = executor.submit {
            val result = runCatching {
                try {
                    val recognized = tracked.transcribe(post.getInt("id"), audio).getString("recognized")
                    operation.stage("stt_completed")
                    tracked.request("posts/${post.getInt("id")}/replies/prepare/", "POST",
                        JSONObject().put("recognized", recognized))
                } finally { audio.delete() }
            }
            activity.runOnUiThread {
                if (request != generation || activity.isDestroyed) return@runOnUiThread
                task = null
                result.fold({ value ->
                    value.put("_telemetry_operation_id", operation.id)
                    draft = value; stage = Stage.REVIEW; render()
                    post { operation.stage("draft_shown", fields = mapOf("draft_edited" to false)) }
                },
                    { error -> failed(error, "말씀을 글로 바꾸지 못했어요. 다시 말씀해 주세요.") })
            }
        }
    }

    /** Sending runs in the shared background queue; its status bar handles progress and retry. */
    private fun sendDraft() {
        val value = draft ?: return
        submitVoice(value)
        draft = null; stage = Stage.IDLE; message = ""; render()
    }

    private fun sendText(text: String) {
        if (stage != Stage.IDLE) return
        submitText(text)
        composer.input.setText("")
    }

    private fun failed(error: Throwable, fallback: String) {
        if (error is ApiException && error.status == 401) { stage = Stage.IDLE; render(); login(); return }
        stage = Stage.IDLE
        message = (error as? ApiException)?.message ?: fallback
        render()
    }

    /** Stops recording and drops late responses; a typed draft stays in the field. */
    fun cancel() {
        generation++
        task?.cancel(true); task = null
        recorder?.cancel(); recorder = null
        draft = null; message = ""
        stage = Stage.IDLE
        composer.setSending(false)
    }

    override fun onDetachedFromWindow() {
        cancel()
        super.onDetachedFromWindow()
    }
}
