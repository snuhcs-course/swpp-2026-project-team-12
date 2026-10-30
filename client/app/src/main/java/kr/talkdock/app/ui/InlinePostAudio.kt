package kr.talkdock.app.ui

import android.app.Activity
import android.content.res.ColorStateList
import android.graphics.drawable.RippleDrawable
import android.view.Gravity
import android.view.View
import android.widget.LinearLayout
import androidx.core.view.doOnLayout
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
    private val login: () -> Unit,
    private val playbackChanged: (Boolean) -> Unit = {},
) : LinearLayout(activity) {
    val toggle = ui.row().apply {
        gravity = Gravity.CENTER
        minimumHeight = ui.dp(if (large) 64 else 48)
        setPadding(ui.dp(10), ui.dp(6), ui.dp(10), ui.dp(6))
        isClickable = true; isFocusable = true
        background = RippleDrawable(ColorStateList.valueOf(ui.border), ui.shape(if (large) ui.sky else ui.paper), null)
        setOnClickListener { togglePlayback() }
    }
    private var task: Future<*>? = null
    private var generation = 0
    private var active = false
    private var summaryLoading = false
    private var speechLoading = false
    private var autoplayAfterSummary = false
    private var summaryText: String? = null
    private var status = ""
    private var summaryRetry: Boolean? = null
    private var speechRetry: String? = null
    private var needsLogin = false
    private var revealSummary = false
    val isPlaying get() = active

    init {
        orientation = VERTICAL
        visibility = GONE
        updateToggle()
    }

    /** Uses the same summary as listening, without requesting speech. */
    fun showSummary() {
        revealSummary = true
        if (needsLogin) login()
        else if (summaryText != null) render()
        else if (!summaryLoading) loadSummary(false, autoplay = false)
    }

    fun togglePlayback() {
        if (needsLogin) login()
        else if (active) stop()
        else if (summaryLoading) {
            activate(this)
            speaker.stop()
            active = true
            autoplayAfterSummary = true
            updateToggle()
        }
        else if (summaryText != null) startSpeech(summaryText!!)
        else loadSummary(false)
    }

    private fun updateToggle() {
        val label = if (active) (if (large) "듣기 중지" else "중지") else (if (large) "소식 듣기" else "듣기")
        toggle.contentDescription = label
        toggle.isSelected = active
        toggle.removeAllViews()
        toggle.addView(IconView(activity, if (active) "stop" else "listen", ui.skyDeep),
            LayoutParams(ui.dp(22), ui.dp(22)))
        ui.label(toggle, label, if (large) 20f else 16f, bold = large, color = ui.ink).apply { gravity = Gravity.CENTER; setPadding(ui.dp(6), 0, 0, 0) }
        playbackChanged(active)
    }

    private fun render() {
        removeAllViews()
        if (summaryText == null && status.isBlank() && !summaryLoading && !speechLoading && summaryRetry == null && speechRetry == null && !needsLogin) {
            visibility = GONE
            updateToggle()
            return
        }
        visibility = VISIBLE
        ui.gap(this, 12)
        summaryText?.let { ui.note(this, it, large) }
        // A false retry flag means the server is still processing, with manual recheck available.
        if (speechLoading || summaryLoading || summaryRetry == false) {
            val stage = if (speechLoading) PostPreparationView.Stage.SPEECH else PostPreparationView.Stage.NEWS
            addView(PostPreparationView(activity, ui, large, stage), LayoutParams(-1, -2).apply { topMargin = ui.dp(8) })
        }
        else if (status.isNotBlank()) ui.note(this, status, large).apply {
            accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
        }
        if (needsLogin) ui.button(this, "다시 로그인", false, height()) { login() }
        else {
            summaryRetry?.let { retry ->
                ui.button(this, if (retry) "설명 다시 준비하기" else "다시 확인하기", false, height()) {
                    loadSummary(retry, autoplayAfterSummary)
                }
                val caption = post.optString("caption")
                if (caption.isNotBlank()) ui.button(this, "가족이 쓴 글 듣기", false, height()) { startSpeech(caption) }
            }
            speechRetry?.let { text ->
                ui.button(this, "음성 다시 준비하기", false, height()) { startSpeech(text) }
            }
        }
        updateToggle()
        if (revealSummary && summaryText != null) {
            revealSummary = false
            doOnLayout { if (isAttachedToWindow) requestRectangleOnScreen(android.graphics.Rect(0, 0, width, minOf(height, ui.dp(120))), true) }
        }
    }

    private fun height() = if (large) 76 else 56

    private fun begin(message: String, playback: Boolean = true, generatingSpeech: Boolean = false,
                      preparingSummary: Boolean = false): Int {
        if (playback) activate(this)
        stop()
        if (playback) speaker.stop() // Also stop a digest or reply preview sharing this player.
        active = playback
        speechLoading = generatingSpeech
        summaryLoading = preparingSummary
        summaryRetry = null; speechRetry = null; needsLogin = false
        status = message
        render()
        return generation
    }

    /** Invalidate pending callbacks as well as stopping already playing audio. */
    fun stop() {
        generation++
        task?.cancel(true); task = null
        autoplayAfterSummary = false
        if (active || summaryLoading || speechLoading) {
            if (active) speaker.stop()
            active = false
            summaryLoading = false
            speechLoading = false
            status = ""
            render()
        }
    }

    private fun current(request: Int) = request == generation && isAttachedToWindow && !activity.isDestroyed

    private fun loadSummary(retry: Boolean, autoplay: Boolean = true) {
        val request = begin("", playback = autoplay, preparingSummary = true)
        autoplayAfterSummary = autoplay
        revealLoadingIndicator()
        task = executor.submit {
            val result = runCatching {
                client.request("posts/${post.getInt("id")}/message/", if (retry) "POST" else "GET", if (retry) JSONObject() else null)
            }
            activity.runOnUiThread {
                if (!current(request)) return@runOnUiThread
                task = null
                summaryLoading = false
                result.fold({ data ->
                    val text = data.optString("text").trim()
                    if (data.optString("status") == "ready" && text.isNotEmpty()) {
                        summaryText = text
                        if (autoplayAfterSummary) startSpeech(text)
                        else { status = ""; render() }
                    } else {
                        active = false
                        val processing = data.optString("status") == "processing"
                        status = if (processing) "" else "설명을 준비하지 못했어요. 다시 시도해 주세요."
                        summaryRetry = !processing
                        render()
                    }
                }, { fail(it, summary = true) })
            }
        }
    }

    private fun revealLoadingIndicator() {
        findViewWithTag<View>(if (speechLoading) "speech-loading" else "summary-loading")?.doOnLayout { loading ->
            if (loading.isAttachedToWindow) loading.requestRectangleOnScreen(android.graphics.Rect(0, 0, loading.width, loading.height), true)
        }
    }

    private fun startSpeech(text: String) {
        val pendingSummaryRetry = summaryRetry
        val request = begin("", generatingSpeech = true)
        // Listening to the original caption must keep summary recovery available.
        if (summaryText == null) { summaryRetry = pendingSummaryRetry; render() }
        revealLoadingIndicator()
        task = executor.submit {
            val result = runCatching {
                val bytes = client.speech(text)
                val file = File.createTempFile("post-listen-", ".mp3", activity.cacheDir)
                try { file.writeBytes(bytes); file } catch (error: Exception) { file.delete(); throw error }
            }
            activity.runOnUiThread {
                if (!current(request)) { result.getOrNull()?.delete(); return@runOnUiThread }
                task = null
                speechLoading = false
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
        summaryLoading = false
        speechLoading = false
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
