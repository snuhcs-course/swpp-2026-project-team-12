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
class CommentComposer(context: Context, private val ui: Ui, large: Boolean, onSend: (String) -> Unit) : LinearLayout(context) {
    val input = EditText(context).apply {
        hint = "가족에게 하고 싶은 말"
        contentDescription = "댓글 입력"
        textSize = if (large) 23f else 18f
        typeface = ui.font; fontVariationSettings = "'wght' 400"
        setTextColor(ui.ink); setHintTextColor(ui.muted)
        inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_MULTI_LINE or InputType.TYPE_TEXT_FLAG_CAP_SENTENCES
        isSingleLine = false; gravity = Gravity.TOP or Gravity.START
        setPadding(ui.dp(16), ui.dp(15), ui.dp(16), ui.dp(8))
        background = null
    }
    private var sending = false
    val sendButton = ui.iconButton("up", "댓글 보내기") {
        if (!sending && input.text.isNotBlank()) onSend(input.text.toString())
    }.apply {
        background = RippleDrawable(ColorStateList.valueOf(ui.border), ui.shape(ui.coral, 32), null)
    }
    private val progress = ProgressBar(context).apply {
        visibility = GONE; contentDescription = "댓글 전송 중"
        indeterminateTintList = ColorStateList.valueOf(ui.coralDeep)
    }
    private val error = ui.text("", if (large) 20f else 16f, color = ui.coralDeep).apply {
        visibility = GONE
        accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
    }

    init {
        orientation = VERTICAL
        ui.label(this, "따뜻한 한마디 남기기", if (large) 20f else 16f, true)
        ui.gap(this, 8)
        val size = if (large) 64 else 48
        val field = FrameLayout(context).apply { background = ui.shape(ui.paper, stroke = true) }
        addView(field, LayoutParams(-1, ui.dp(if (large) 224 else 184)))
        field.addView(input, FrameLayout.LayoutParams(-1, -1).apply { bottomMargin = ui.dp(size + 16) })
        field.addView(sendButton, FrameLayout.LayoutParams(ui.dp(size), ui.dp(size), Gravity.BOTTOM or Gravity.END).apply {
            bottomMargin = ui.dp(8); marginEnd = ui.dp(8)
        })
        field.addView(progress, FrameLayout.LayoutParams(ui.dp(24), ui.dp(24), Gravity.BOTTOM or Gravity.END).apply {
            bottomMargin = ui.dp(8 + (size - 24) / 2); marginEnd = ui.dp(size + 24)
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
