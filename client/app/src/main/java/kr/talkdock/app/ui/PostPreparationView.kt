package kr.talkdock.app.ui

import android.animation.ValueAnimator
import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.view.Gravity
import android.view.View
import android.view.animation.LinearInterpolator
import android.widget.LinearLayout
import kotlin.math.abs
import kotlin.math.sin

/** Unboxed summary/speech preparation. Both animations are decorative. */
class PostPreparationView(context: Context, ui: Ui, large: Boolean, stage: Stage) : LinearLayout(context) {
    enum class Stage { NEWS, SPEECH }

    init {
        orientation = HORIZONTAL; gravity = Gravity.CENTER
        minimumHeight = ui.dp(if (large) 64 else 56)
        setPadding(0, ui.dp(8), 0, ui.dp(8))
        tag = if (stage == Stage.SPEECH) "speech-loading" else "summary-loading"
        addView(PreparationAnimation(context, ui, stage), LayoutParams(ui.dp(44), ui.dp(32)))
        val label = if (stage == Stage.SPEECH) "목소리 생성중" else "가족 소식 준비중"
        addView(ui.text(label, if (large) 20f else 16f, color = ui.skyDeep).apply {
            accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
        }, LayoutParams(-2, -2).apply { marginStart = ui.dp(12) })
    }
}

private class PreparationAnimation(context: Context, private val ui: Ui,
                                   private val stage: PostPreparationView.Stage) : View(context) {
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = ui.coralDeep; strokeCap = Paint.Cap.ROUND; strokeWidth = ui.dp(3).toFloat()
    }
    private var phase = 0f
    private var animator: ValueAnimator? = null

    init { importantForAccessibility = IMPORTANT_FOR_ACCESSIBILITY_NO }

    private fun updateAnimation() {
        if (!isAttachedToWindow || !isShown || windowVisibility != VISIBLE || !ValueAnimator.areAnimatorsEnabled()) {
            stopAnimation()
            return
        }
        if (animator != null) return
        animator = ValueAnimator.ofFloat(0f, (Math.PI * 2).toFloat()).apply {
            duration = if (stage == PostPreparationView.Stage.NEWS) 1200 else 1100
            repeatCount = ValueAnimator.INFINITE; interpolator = LinearInterpolator()
            addUpdateListener { phase = it.animatedValue as Float; invalidate() }
            start()
        }
    }

    private fun stopAnimation() {
        animator?.cancel(); animator = null; phase = 0f; invalidate()
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        if (stage == PostPreparationView.Stage.NEWS) {
            for (i in 0..2) {
                val rise = if (animator == null) 0f else maxOf(0f, sin(phase - i * 1.2f))
                paint.alpha = if (animator == null) 255 else (110 + rise * 145).toInt()
                canvas.drawCircle(width / 2f + (i - 1) * ui.dp(12), height / 2f - rise * ui.dp(4), ui.dp(3).toFloat(), paint)
            }
            return
        }
        paint.alpha = 255
        for (i in 0..4) {
            val base = ui.dp(10 + (2 - abs(i - 2)) * 5)
            val pulse = .6f + .4f * sin(phase + i * .9f)
            val half = base * pulse / 2f
            val x = width / 2f + (i - 2) * ui.dp(8)
            canvas.drawLine(x, height / 2f - half, x, height / 2f + half, paint)
        }
    }

    override fun onAttachedToWindow() { super.onAttachedToWindow(); updateAnimation() }
    override fun onDetachedFromWindow() { stopAnimation(); super.onDetachedFromWindow() }
    override fun onVisibilityChanged(changedView: View, visibility: Int) {
        super.onVisibilityChanged(changedView, visibility); updateAnimation()
    }
    override fun onWindowVisibilityChanged(visibility: Int) {
        super.onWindowVisibilityChanged(visibility); updateAnimation()
    }
}
