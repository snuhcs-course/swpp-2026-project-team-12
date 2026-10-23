package kr.talkdock.app.ui

import android.app.Activity
import android.content.res.ColorStateList
import android.graphics.drawable.RippleDrawable
import android.view.Gravity
import android.view.View
import android.widget.FrameLayout
import android.widget.ProgressBar
import android.widget.Toast
import kr.talkdock.app.data.ApiClient
import kr.talkdock.app.data.ApiException
import kr.talkdock.app.device.Speaker
import java.io.File
import java.util.concurrent.ExecutorService
import java.util.concurrent.Future

/** One accessible play/stop action beside the reviewed reply's heading. */
class ReplyAudioButton(
    private val activity: Activity,
    private val ui: Ui,
    private val text: String,
    private val client: ApiClient,
    private val speaker: Speaker,
    private val executor: ExecutorService,
    large: Boolean
) : FrameLayout(activity) {
    private var request = 0
    private var active = false
    private var task: Future<*>? = null

    init {
        val size = ui.dp(if (large) 64 else 48)
        layoutParams = android.widget.LinearLayout.LayoutParams(size, size)
        background = RippleDrawable(ColorStateList.valueOf(ui.border), ui.shape(ui.sky, 16), null)
        isClickable = true; isFocusable = true
        setOnClickListener { if (active) stop() else play() }
        render()
    }

    private fun render(loading: Boolean = false) {
        isSelected = active
        contentDescription = if (active) "댓글 듣기 중지" else "댓글 소리로 확인하기"
        removeAllViews()
        val glyph: View = if (loading) ProgressBar(activity).apply {
            indeterminateTintList = ColorStateList.valueOf(ui.skyDeep)
        } else IconView(activity, if (active) "stop" else "listen", ui.skyDeep)
        glyph.importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
        val side = if (loading) ui.dp(26) else LayoutParams.MATCH_PARENT
        addView(glyph, LayoutParams(side, side, Gravity.CENTER))
    }

    private fun current(token: Int) = token == request && isAttachedToWindow && !activity.isDestroyed

    fun stop() {
        request++; task?.cancel(true); task = null
        if (active) speaker.stop()
        active = false
        render()
    }

    private fun play() {
        stop(); speaker.stop()
        active = true; render(loading = true)
        val token = request
        task = executor.submit {
            val result = runCatching {
                val bytes = client.speech(text)
                val file = File.createTempFile("reply-preview-", ".mp3", activity.cacheDir)
                try { file.writeBytes(bytes); file } catch (error: Exception) { file.delete(); throw error }
            }
            activity.runOnUiThread {
                if (!current(token)) { result.getOrNull()?.delete(); return@runOnUiThread }
                task = null
                result.fold({ file ->
                    render()
                    speaker.play(file, completed = { if (current(token)) stop() }, failed = { message ->
                        if (current(token)) fail(message)
                    })
                }, { error -> fail((error as? ApiException)?.message ?: "소리를 재생하지 못했어요. 다시 눌러 주세요.") })
            }
        }
    }

    private fun fail(message: String) {
        stop()
        Toast.makeText(activity, message, Toast.LENGTH_LONG).show()
    }

    override fun onDetachedFromWindow() {
        stop()
        super.onDetachedFromWindow()
    }
}
