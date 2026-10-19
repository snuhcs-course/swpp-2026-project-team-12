package kr.talkdock.app.ui

import android.app.Activity
import android.content.res.ColorStateList
import android.graphics.drawable.RippleDrawable
import android.view.Gravity
import android.view.View
import android.widget.LinearLayout
import kr.talkdock.app.data.ApiClient
import kr.talkdock.app.data.ApiException
import kr.talkdock.app.device.Speaker
import org.json.JSONObject
import java.io.File
import java.util.concurrent.ExecutorService
import java.util.concurrent.Future

/** UI-thread owned playback for one post. Requests never block comment actions. */
class InlinePostAudio(
    private val activity: Activity,
    private val ui: Ui,
    private val post: JSONObject,
    private val large: Boolean,
    private val client: ApiClient,
    private val speaker: Speaker,
    private val executor: ExecutorService,
    private val activate: (InlinePostAudio) -> Unit,
    private val login: () -> Unit
) : LinearLayout(activity) {
    val toggle = ui.column(4).apply {
        gravity = Gravity.CENTER
        minimumHeight = ui.dp(if (large) 76 else 60)
        isClickable = true; isFocusable = true
        background = RippleDrawable(ColorStateList.valueOf(ui.border), ui.shape(ui.paper), null)
        setOnClickListener {
            if (needsLogin) login()
            else if (active) stop()
            else if (summaryText != null) startSpeech(summaryText!!)
            else loadSummary(false)
        }
    }
    private var task: Future<*>? = null
    private var generation = 0
    private var active = false
    private var summaryText: String? = null
    private var status = ""
    private var summaryRetry: Boolean? = null
    private var speechRetry: String? = null
    private var needsLogin = false

    init {
        orientation = VERTICAL
        visibility = GONE
        updateToggle()
    }

    private fun updateToggle() {
        val label = if (active) (if (large) "듣기 중지" else "중지") else (if (large) "소식 듣기" else "듣기")
        toggle.contentDescription = label
        toggle.isSelected = active
        toggle.removeAllViews()
        toggle.addView(IconView(activity, if (active) "stop" else "listen", ui.skyDeep),
            LayoutParams(ui.dp(if (large) 28 else 22), ui.dp(if (large) 28 else 22)))
        ui.label(toggle, label, if (large) 22f else 14f, color = ui.skyDeep).gravity = Gravity.CENTER
    }

    private fun render() {
        removeAllViews()
        if (summaryText == null && status.isBlank() && summaryRetry == null && speechRetry == null && !needsLogin) {
            visibility = GONE
            updateToggle()
            return
        }
        visibility = VISIBLE
        ui.gap(this, 12)
        summaryText?.let { ui.note(this, it, large) }
        if (status.isNotBlank()) ui.note(this, status, large).apply {
            accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
        }
        if (needsLogin) ui.button(this, "다시 로그인", false, height()) { login() }
        else {
            summaryRetry?.let { retry ->
                ui.button(this, if (retry) "설명 다시 준비하기" else "다시 확인하기", false, height()) { loadSummary(retry) }
                val caption = post.optString("caption")
                if (caption.isNotBlank()) ui.button(this, "가족이 쓴 글 듣기", false, height()) { startSpeech(caption) }
            }
            speechRetry?.let { text ->
                ui.button(this, "음성 다시 준비하기", false, height()) { startSpeech(text) }
            }
        }
        updateToggle()
    }

    private fun height() = if (large) 76 else 56

    private fun begin(message: String): Int {
        activate(this)
        stop()
        speaker.stop() // Also stop a digest or reply preview sharing this player.
        active = true
        summaryRetry = null; speechRetry = null; needsLogin = false
        status = message
        render()
        return generation
    }

    /** Invalidate pending callbacks as well as stopping already playing audio. */
    fun stop() {
        generation++
        task?.cancel(true); task = null
        if (active) {
            speaker.stop()
            active = false
            status = ""
            render()
        }
    }

    private fun current(request: Int) = request == generation && isAttachedToWindow && !activity.isDestroyed

    private fun loadSummary(retry: Boolean) {
        val request = begin("가족 소식을 준비하고 있어요. 댓글은 바로 남길 수 있어요.")
        task = executor.submit {
            val result = runCatching {
                client.request("posts/${post.getInt("id")}/message/", if (retry) "POST" else "GET", if (retry) JSONObject() else null)
            }
            activity.runOnUiThread {
                if (!current(request)) return@runOnUiThread
                task = null
                result.fold({ data ->
                    val text = data.optString("text").trim()
                    if (data.optString("status") == "ready" && text.isNotEmpty()) {
                        summaryText = text
                        startSpeech(text)
                    } else {
                        active = false
                        val processing = data.optString("status") == "processing"
                        status = if (processing) "가족 소식을 준비하고 있어요. 잠시 후 다시 확인해 주세요."
                            else "설명을 준비하지 못했어요. 다시 시도해 주세요."
                        summaryRetry = !processing
                        render()
                    }
                }, { fail(it, summary = true) })
            }
        }
    }

    private fun startSpeech(text: String) {
        val pendingSummaryRetry = summaryRetry
        val request = begin("소리를 준비하고 있어요. 댓글은 바로 남길 수 있어요.")
        // Listening to the original caption must keep summary recovery available.
        if (summaryText == null) { summaryRetry = pendingSummaryRetry; render() }
        task = executor.submit {
            val result = runCatching {
                val bytes = client.speech(text)
                val file = File.createTempFile("post-listen-", ".mp3", activity.cacheDir)
                try { file.writeBytes(bytes); file } catch (error: Exception) { file.delete(); throw error }
            }
            activity.runOnUiThread {
                if (!current(request)) { result.getOrNull()?.delete(); return@runOnUiThread }
                task = null
                result.fold({ file ->
                    status = ""
                    render()
                    speaker.play(file, completed = {
                        if (current(request)) { active = false; status = ""; render() }
                    }, failed = { message ->
                        if (current(request)) fail(Exception(message), speech = text)
                    })
                }, { fail(it, speech = text) })
            }
        }
    }

    private fun fail(error: Throwable, summary: Boolean = false, speech: String? = null) {
        active = false
        needsLogin = error is ApiException && error.status == 401
        status = if (needsLogin) "로그인이 만료되었어요. 다시 로그인해 주세요."
            else (error as? ApiException)?.message ?: if (summary) "설명을 불러오지 못했어요. 다시 시도해 주세요."
            else "소리를 재생하지 못했어요. 다시 시도해 주세요."
        summaryRetry = if (needsLogin) null else if (summary) true else summaryRetry
        speechRetry = if (!needsLogin) speech else null
        render()
    }

    override fun onDetachedFromWindow() {
        stop()
        super.onDetachedFromWindow()
    }
}
