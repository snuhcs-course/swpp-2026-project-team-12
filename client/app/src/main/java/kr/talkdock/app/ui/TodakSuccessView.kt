package kr.talkdock.app.ui

import android.content.Context
import android.view.Gravity
import android.view.View
import android.widget.LinearLayout

/** A brief success screen after the server accepts a post or comment. */
class TodakSuccessView(context: Context, message: String, complete: () -> Unit) : LinearLayout(context) {
    private val finish = Runnable { complete() }

    init {
        val ui = Ui(context)
        orientation = VERTICAL; gravity = Gravity.CENTER
        setPadding(ui.dp(24), ui.dp(24), ui.dp(24), ui.dp(24))
        setBackgroundColor(ui.milk)
        isClickable = true; isFocusable = true
        addView(TodakJoyView(context), LayoutParams(LayoutParams.MATCH_PARENT, ui.dp(300)))
        ui.gap(this, 24)
        ui.label(this, message, 24f, true).apply {
            gravity = Gravity.CENTER
            accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
        }
    }

    override fun onAttachedToWindow() {
        super.onAttachedToWindow()
        postDelayed(finish, 3000L)
    }

    override fun onDetachedFromWindow() {
        removeCallbacks(finish)
        super.onDetachedFromWindow()
    }
}
