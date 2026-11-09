package kr.talkdock.app.ui

import android.content.Context
import android.content.res.ColorStateList
import android.graphics.Rect
import android.graphics.drawable.RippleDrawable
import android.text.Editable
import android.text.InputType
import android.text.TextWatcher
import android.view.Gravity
import android.view.View
import android.view.ViewTreeObserver
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ProgressBar

/** Multiline input with a reserved footer so long comments cannot cover Send. */
class CommentComposer(
    context: Context, private val ui: Ui, large: Boolean,
    title: String = "따뜻한 한마디 남기기", hintText: String = "가족에게 하고 싶은 말",
    inputLabel: String = "댓글 입력", sendLabel: String = "댓글 보내기", pendingLabel: String = "댓글 전송 중",
    private val compact: Boolean = false, onVoice: (() -> Unit)? = null,
    compactFieldHeight: Int? = null,
    onSend: (String) -> Unit
) : LinearLayout(context) {
    val input = EditText(context).apply {
        hint = hintText
        contentDescription = inputLabel
        textSize = if (large) 23f else 18f
        typeface = ui.font
        setTextColor(ui.ink); setHintTextColor(ui.muted)
        inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_MULTI_LINE or InputType.TYPE_TEXT_FLAG_CAP_SENTENCES
        isSingleLine = false; gravity = Gravity.TOP or Gravity.START
        setPadding(ui.dp(16), ui.dp(15), ui.dp(16), ui.dp(8))
        background = null
    }
    private var sending = false
    private val voice = onVoice?.let { action -> ui.iconButton("mic", "말로 댓글 쓰기", action) }
    val sendButton = ui.iconButton("up", sendLabel) {
        if (!sending && input.text.isNotBlank()) onSend(input.text.toString())
    }.apply {
        background = RippleDrawable(ColorStateList.valueOf(ui.border), ui.shape(ui.coral, 32), null)
    }
    private val progress = ProgressBar(context).apply {
        visibility = GONE; contentDescription = pendingLabel
        indeterminateTintList = ColorStateList.valueOf(ui.coralDeep)
    }
    private val error = ui.text("", if (large) 20f else 16f, color = ui.coralDeep).apply {
        visibility = GONE
        accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
    }

    init {
        orientation = VERTICAL
        if (title.isNotBlank()) { ui.label(this, title, if (large) 20f else 16f, true); ui.gap(this, 8) }
        val size = if (large) 64 else 48
        val fieldHeight = if (compact) compactFieldHeight ?: (if (large) 112 else 88) else if (large) 224 else 184
        val controlInset = minOf(8, ((fieldHeight - size) / 2).coerceAtLeast(0))
        val field = FrameLayout(context).apply {
            background = ui.shape(if (compact) ui.blush else ui.paper, if (compact) 28 else 20, stroke = !compact)
            clipToOutline = true
        }
        if (compact) voice?.background = RippleDrawable(ColorStateList.valueOf(ui.border), ui.shape(ui.paper, size / 2), null)
        addView(field, LayoutParams(-1, ui.dp(fieldHeight)))
        field.addView(input, FrameLayout.LayoutParams(-1, -1).apply { bottomMargin = ui.dp(if (compact) 4 else size + 16); marginEnd = ui.dp(if (compact) size + 16 else 0) })
        field.addView(sendButton, FrameLayout.LayoutParams(ui.dp(size), ui.dp(size), Gravity.BOTTOM or Gravity.END).apply {
            bottomMargin = ui.dp(controlInset); marginEnd = ui.dp(controlInset)
        })
        voice?.let { field.addView(it, FrameLayout.LayoutParams(ui.dp(size), ui.dp(size), Gravity.BOTTOM or Gravity.END).apply {
            bottomMargin = ui.dp(controlInset); marginEnd = ui.dp(controlInset)
        }) }
        field.addView(progress, FrameLayout.LayoutParams(ui.dp(24), ui.dp(24), Gravity.BOTTOM or Gravity.END).apply {
            bottomMargin = ui.dp(controlInset + (size - 24) / 2); marginEnd = ui.dp(size + 24)
        })
        addView(error, LayoutParams(-1, -2).apply { topMargin = ui.dp(8) })
        input.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) = Unit
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) { updateButton() }
            override fun afterTextChanged(s: Editable?) = Unit
        })
        updateButton()
    }

    private val keepSendVisible = ViewTreeObserver.OnPreDrawListener {
        if (input.hasFocus() && ViewCompat.getRootWindowInsets(this)?.isVisible(WindowInsetsCompat.Type.ime()) == true) {
            val visible = Rect()
            if (!sendButton.getGlobalVisibleRect(visible) || visible.height() < sendButton.height) {
                // ScrollView normally reveals only the focused editor, excluding its footer.
                sendButton.requestRectangleOnScreen(Rect(0, 0, sendButton.width, sendButton.height), true)
            }
        }
        true
    }

    override fun onAttachedToWindow() {
        super.onAttachedToWindow()
        viewTreeObserver.addOnPreDrawListener(keepSendVisible)
    }

    override fun onDetachedFromWindow() {
        viewTreeObserver.removeOnPreDrawListener(keepSendVisible)
        super.onDetachedFromWindow()
    }

    private fun updateButton() {
        sendButton.visibility = if (compact && input.text.isBlank() && !sending) GONE else VISIBLE
        voice?.visibility = if (compact && input.text.isBlank() && !sending) VISIBLE else GONE
        sendButton.isEnabled = !sending && input.text.isNotBlank()
        sendButton.alpha = if (sendButton.isEnabled) 1f else 0.35f
    }

    fun setSending(value: Boolean) {
        sending = value
        input.isEnabled = !value
        progress.visibility = if (value) VISIBLE else GONE
        if (value) error.visibility = GONE
        updateButton()
    }

    fun showError(message: String) {
        setSending(false)
        error.text = message
        error.visibility = VISIBLE
    }
}
