package kr.talkdock.app.ui

import android.animation.ObjectAnimator
import android.animation.ValueAnimator
import android.content.Context
import android.content.res.ColorStateList
import android.view.Gravity
import android.view.View
import android.widget.LinearLayout
import android.widget.ProgressBar

/** Indeterminate waiting feedback; no invented completion percentages. */
class TodakWaitingView(context: Context, message: String) : LinearLayout(context) {
    private val ui = Ui(context)
    private val art = TodakArtView(context, "together", 168)
    private var motion: ObjectAnimator? = null
    init {
        orientation = VERTICAL; gravity = Gravity.CENTER
        setPadding(ui.dp(24), ui.dp(24), ui.dp(24), ui.dp(24))
        setBackgroundColor(ui.milk)
        isClickable = true; isFocusable = true
        addView(art, LayoutParams(ui.dp(168), ui.dp(153)))
        ui.gap(this, 24)
        addView(ProgressBar(context).apply { indeterminateTintList = ColorStateList.valueOf(ui.coralDeep) },
            LayoutParams(ui.dp(32), ui.dp(32)))
        ui.gap(this, 20)
        ui.label(this, message, 19f, true).apply {
            gravity = Gravity.CENTER; accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
        }
        ui.gap(this, 8)
        ui.label(this, "토닥토닥, 잠시만 기다려 주세요.", 16f, color = ui.muted).gravity = Gravity.CENTER
    }
    override fun onAttachedToWindow() {
        super.onAttachedToWindow()
        if (ValueAnimator.areAnimatorsEnabled()) {
            motion = ObjectAnimator.ofFloat(art, "translationY", 0f, -ui.dp(3).toFloat(), 0f).apply {
                duration = 1800; repeatCount = ValueAnimator.INFINITE; start()
            }
        }
    }
    override fun onDetachedFromWindow() {
        motion?.cancel(); motion = null; art.translationY = 0f
        super.onDetachedFromWindow()
    }
}
