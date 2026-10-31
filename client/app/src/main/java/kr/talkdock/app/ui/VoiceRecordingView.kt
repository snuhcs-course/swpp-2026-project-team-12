package kr.talkdock.app.ui

import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.os.SystemClock
import android.view.View
import kotlin.math.sin

/** A listening animation and elapsed time, not a simulated live transcription. */
class VoiceRecordingView(context: Context, private val ui: Ui,
    private val active: () -> Boolean, private val startedAt: () -> Long) : View(context) {
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = ui.coralDeep; strokeCap = Paint.Cap.ROUND }
    init { contentDescription = "음성 답장 녹음 상태"; importantForAccessibility = IMPORTANT_FOR_ACCESSIBILITY_NO }
    private var lastElapsed = 0L
    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        if (active() && startedAt() != 0L) lastElapsed = (SystemClock.elapsedRealtime() - startedAt()) / 1000
        val elapsed = lastElapsed
        val center = width / 2f
        paint.strokeWidth = ui.dp(4).toFloat()
        for (i in -9..9) {
            val wave = if (active()) (sin(SystemClock.uptimeMillis() / 240.0 + i * .8) + 1.5).toFloat() else .6f
            val bar = ui.dp(7) * wave
            canvas.drawLine(center + i * ui.dp(10), ui.dp(24) - bar, center + i * ui.dp(10), ui.dp(24) + bar, paint)
        }
        paint.textAlign = Paint.Align.CENTER; paint.textSize = 16 * resources.displayMetrics.scaledDensity; paint.typeface = ui.font
        paint.color = ui.muted
        canvas.drawText("${elapsed / 60}:${(elapsed % 60).toString().padStart(2, '0')}", center, ui.dp(76).toFloat(), paint)
        paint.color = ui.coralDeep
        if (active() && isAttachedToWindow) postInvalidateOnAnimation()
    }
}
