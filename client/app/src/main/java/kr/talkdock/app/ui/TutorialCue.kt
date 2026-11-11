package kr.talkdock.app.ui

import android.animation.ValueAnimator
import android.content.Context
import android.graphics.Canvas
import android.graphics.ColorFilter
import android.graphics.Paint
import android.graphics.PixelFormat
import android.graphics.drawable.Drawable
import android.view.View
import android.view.accessibility.AccessibilityManager
import android.view.animation.LinearInterpolator
import android.widget.EditText
import androidx.core.view.ViewCompat
import kotlin.math.sin

/** Draws in the real control's overlay. The control keeps its layout and all touch events. */
class TutorialCue(
    val target: View,
    description: String,
    private val example: String? = null,
    private val tapFirst: Boolean = false,
) {
    private val editor = target as? EditText
    private val oldHint = editor?.hint
    private val oldDescription = ViewCompat.getStateDescription(target)
    private val hand = TapHand(target)
    private val positioning = View.OnLayoutChangeListener { _, _, _, _, _, _, _, _, _ -> positionHand() }
    private var animator: ValueAnimator? = null

    init {
        ViewCompat.setStateDescription(target, description)
        target.addOnLayoutChangeListener(positioning)
        positionHand()
        if (example != null) requireNotNull(editor)
        val access = target.context.getSystemService(Context.ACCESSIBILITY_SERVICE) as AccessibilityManager
        if (ValueAnimator.areAnimatorsEnabled() && !access.isTouchExplorationEnabled) animate()
        else if (example == null) target.overlay.add(hand)
        else editor?.hint = example
    }

    private fun positionHand() {
        val density = target.resources.displayMetrics.density
        val side = minOf((48 * density).toInt(), target.width, target.height)
        if (side <= 0) return
        val inset = (6 * density).toInt()
        val left = (target.width - side - inset).coerceAtLeast(0)
        val top = minOf((target.height - side) / 2, inset * 2)
        hand.setBounds(left, top, left + side, top + side)
    }

    private fun animate() {
        val text = example
        val typeStart = if (tapFirst) 900 else 0
        val total = if (text == null) 1300 else typeStart + text.length * 110
        if (text != null) editor?.hint = ""
        var showingHand = text == null || tapFirst
        if (showingHand) target.overlay.add(hand)
        animator = ValueAnimator.ofInt(0, total).apply {
            duration = total.toLong()
            repeatCount = if (text == null) 2 else 0
            interpolator = LinearInterpolator()
            addUpdateListener { animation ->
                val elapsed = animation.animatedValue as Int
                if (text == null || elapsed < typeStart) {
                    hand.phase = elapsed.toFloat() / (if (text == null) total else typeStart)
                } else {
                    if (showingHand) {
                        target.overlay.remove(hand)
                        showingHand = false
                    }
                    val count = ((elapsed - typeStart) / 110).coerceAtMost(text.length)
                    if (editor?.hint?.length != count) editor?.hint = text.take(count)
                }
            }
            start()
        }
    }

    fun clear() {
        animator?.cancel()
        target.overlay.remove(hand)
        target.removeOnLayoutChangeListener(positioning)
        if (example != null) editor?.hint = oldHint
        ViewCompat.setStateDescription(target, oldDescription)
    }
}

private class TapHand(target: View) : Drawable() {
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val ringColor = target.context.getColor(kr.talkdock.app.R.color.todak_accent)
    var phase = .35f
        set(value) { field = value; invalidateSelf() }

    override fun draw(canvas: Canvas) {
        if (bounds.isEmpty) return
        val side = bounds.width().toFloat()
        val press = sin(Math.PI * phase).toFloat()
        val tipX = bounds.exactCenterX()
        val tipY = bounds.top + side * .24f
        val ripple = ((phase - .32f) / .55f).coerceIn(0f, 1f)
        paint.style = Paint.Style.STROKE
        paint.strokeWidth = side * .044f
        paint.color = ringColor
        paint.alpha = (255 * (1 - ripple)).toInt()
        canvas.drawCircle(tipX, tipY, side * (.09f + .16f * ripple), paint)
        paint.style = Paint.Style.FILL
        paint.color = android.graphics.Color.BLACK
        paint.textAlign = Paint.Align.CENTER
        paint.textSize = side * (.68f + .05f * (1 - press))
        canvas.drawText("👆", tipX, bounds.top + side * (.92f - .12f * press), paint)
    }

    override fun setAlpha(alpha: Int) {}
    override fun setColorFilter(colorFilter: ColorFilter?) {}
    @Deprecated("Deprecated in Android") override fun getOpacity(): Int = PixelFormat.TRANSLUCENT
}
