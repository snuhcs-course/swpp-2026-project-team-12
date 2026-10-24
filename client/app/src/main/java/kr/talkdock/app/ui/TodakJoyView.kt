package kr.talkdock.app.ui

import android.animation.ValueAnimator
import android.content.Context
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Movie
import android.os.SystemClock
import android.view.View

/** Plays the supplied joy preview once after a successful post or comment. */
@Suppress("DEPRECATION")
class TodakJoyView(context: Context) : View(context) {
    private val movie = context.assets.open("todak/todak_joy.gif").use { Movie.decodeStream(it) }
    private val still = context.assets.open("todak/todak_joy_still.png").use { BitmapFactory.decodeStream(it) }
    private var startedAt = 0L

    init {
        setLayerType(LAYER_TYPE_SOFTWARE, null)
        importantForAccessibility = IMPORTANT_FOR_ACCESSIBILITY_NO
    }

    override fun onAttachedToWindow() {
        super.onAttachedToWindow()
        startedAt = SystemClock.uptimeMillis()
        invalidate()
    }

    override fun onWindowVisibilityChanged(visibility: Int) {
        super.onWindowVisibilityChanged(visibility)
        if (visibility == VISIBLE) invalidate()
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val animate = movie != null && ValueAnimator.areAnimatorsEnabled()
        val sourceWidth = if (animate) movie!!.width() else still.width
        val sourceHeight = if (animate) movie!!.height() else still.height
        val scale = minOf(width.toFloat() / sourceWidth, height.toFloat() / sourceHeight)
        val save = canvas.save()
        canvas.translate((width - sourceWidth * scale) / 2f, (height - sourceHeight * scale) / 2f)
        canvas.scale(scale, scale)
        if (animate) {
            val duration = movie!!.duration().coerceAtLeast(1)
            movie.setTime((SystemClock.uptimeMillis() - startedAt).coerceAtMost(duration - 1L).toInt())
            movie.draw(canvas, 0f, 0f)
        } else {
            canvas.drawBitmap(still, 0f, 0f, null)
        }
        canvas.restoreToCount(save)
        if (animate && SystemClock.uptimeMillis() - startedAt < movie!!.duration() &&
            isAttachedToWindow && isShown && windowVisibility == VISIBLE) {
            postInvalidateOnAnimation()
        }
    }
}
