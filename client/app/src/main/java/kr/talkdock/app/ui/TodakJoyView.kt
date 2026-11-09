package kr.talkdock.app.ui

import android.animation.AnimatorSet
import android.animation.ObjectAnimator
import android.animation.ValueAnimator
import android.content.Context
import android.widget.ImageView

/** Briefly bounces the same boy used in notices after a successful post or comment. */
class TodakJoyView(context: Context) : ImageView(context) {
    private var motion: AnimatorSet? = null

    init {
        scaleType = ScaleType.FIT_CENTER
        setImageBitmap(TodakArtView.bitmap(context, "grandchild"))
        importantForAccessibility = IMPORTANT_FOR_ACCESSIBILITY_NO
    }

    override fun onAttachedToWindow() {
        super.onAttachedToWindow()
        if (!ValueAnimator.areAnimatorsEnabled()) return
        val lift = 10f * resources.displayMetrics.density
        motion = AnimatorSet().apply {
            playTogether(
                ObjectAnimator.ofFloat(this@TodakJoyView, "translationY", 0f, -lift, 0f, -lift * .6f, 0f),
                ObjectAnimator.ofFloat(this@TodakJoyView, "rotation", 0f, -3f, 3f, -2f, 0f)
            )
            duration = 1800L
            start()
        }
    }

    override fun onWindowVisibilityChanged(visibility: Int) {
        super.onWindowVisibilityChanged(visibility)
        if (visibility != VISIBLE) stopMotion()
    }

    override fun onDetachedFromWindow() {
        stopMotion()
        super.onDetachedFromWindow()
    }

    private fun stopMotion() {
        motion?.cancel(); motion = null
        translationY = 0f; rotation = 0f
    }
}
