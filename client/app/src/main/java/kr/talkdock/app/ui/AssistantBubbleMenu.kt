package kr.talkdock.app.ui

import android.content.Context
import android.content.res.ColorStateList
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.ColorFilter
import android.graphics.Paint
import android.graphics.Path
import android.graphics.PixelFormat
import android.graphics.Rect
import android.graphics.RectF
import android.graphics.drawable.Drawable
import android.graphics.drawable.RippleDrawable
import android.view.Gravity
import android.view.View
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ScrollView
import kotlin.math.abs
import kotlin.math.min

/** Three compact, individually sized balloons next to the character. */
class AssistantBubbleMenu(
    context: Context,
    private val ui: Ui,
    private val large: Boolean,
    askPost: () -> Unit,
    findMemories: () -> Unit,
    dailyDigest: () -> Unit,
) : FrameLayout(context) {
    private val content = ui.column()
    private val options = mutableListOf<Option>()
    private val postOption: View
    private var tailOnLeft = false
    private class Option(val text: android.widget.TextView, val balloon: BalloonDrawable)

    init {
        tag = "assistant-bubble-menu"
        contentDescription = "토닥 도우미 메뉴"
        addView(ScrollView(context).apply {
            isFillViewport = false; isVerticalScrollBarEnabled = false
            addView(content, LinearLayout.LayoutParams(-1, -2))
        }, LayoutParams(-1, -2))
        fun option(label: String, action: () -> Unit): View {
            val balloon = BalloonDrawable(ui)
            val row = FrameLayout(context).apply {
                minimumHeight = ui.dp(if (large) 56 else 48)
                contentDescription = label
                isClickable = true; isFocusable = true; setOnClickListener { action() }
            }
            val text = ui.text(label, if (large) 16f else 13f, color = ui.skyDeep).apply {
                gravity = Gravity.RIGHT or Gravity.CENTER_VERTICAL
                fontVariationSettings = "'wght' 500"
                minHeight = ui.dp(if (large) 40 else 32)
                setPadding(ui.dp(12), ui.dp(7), ui.dp(18), ui.dp(7))
                background = RippleDrawable(ColorStateList.valueOf(ui.border), balloon, null)
                importantForAccessibility = IMPORTANT_FOR_ACCESSIBILITY_NO
                setOnClickListener { action() }
            }
            row.addView(text, LayoutParams(-2, -2, Gravity.RIGHT or Gravity.CENTER_VERTICAL))
            content.addView(row, LinearLayout.LayoutParams(-1, -2))
            options.add(Option(text, balloon))
            return row
        }
        postOption = option("이 글에 대해 궁금하세요?", askPost)
        ui.gap(content, 2)
        option("가족의 지난 추억이 궁금하세요?", findMemories)
        ui.gap(content, 2)
        option("오늘 가족의 하루", dailyDigest)
    }

    fun setPostAvailable(available: Boolean) {
        postOption.isEnabled = available
        options.first().text.isEnabled = available
        postOption.alpha = if (available) 1f else .4f
        postOption.contentDescription = if (available) "이 글에 대해 궁금하세요?" else "이 글에 대해 궁금하세요? 현재 선택된 글이 없어요"
    }

    /** Anchor in root coordinates, including while dragging or resizing for the keyboard. */
    fun follow(character: FloatingAssistantView, viewport: Rect) {
        val toRight = character.x + character.width / 2f < viewport.exactCenterX()
        val attachment = character.bubbleAttachmentX()
        val available = (if (toRight) viewport.right - attachment else attachment - viewport.left).toInt()
        if (available <= 0 || viewport.height() <= 0) { visibility = INVISIBLE; return }
        visibility = VISIBLE
        if (tailOnLeft != toRight) {
            tailOnLeft = toRight
            options.forEach {
                it.text.setPadding(ui.dp(if (toRight) 18 else 12), ui.dp(7), ui.dp(if (toRight) 12 else 18), ui.dp(7))
                val params = it.text.layoutParams as LayoutParams
                params.gravity = (if (toRight) Gravity.LEFT else Gravity.RIGHT) or Gravity.CENTER_VERTICAL
                it.text.layoutParams = params
            }
        }
        val menuWidth = min(ui.dp(if (large) 260 else 224), available)
        measure(MeasureSpec.makeMeasureSpec(menuWidth, MeasureSpec.EXACTLY),
            MeasureSpec.makeMeasureSpec(viewport.height(), MeasureSpec.AT_MOST))
        val menuHeight = measuredHeight.coerceAtLeast(1)
        val params = layoutParams
        if (params.width != menuWidth || params.height != menuHeight) {
            params.width = menuWidth; params.height = menuHeight; layoutParams = params
        }
        val desiredX = if (toRight) attachment else attachment - menuWidth
        val desiredY = (character.y + character.height / 2f - menuHeight / 2f)
            .coerceIn(viewport.top.toFloat(), maxOf(viewport.top.toFloat(), viewport.bottom - menuHeight.toFloat()))
        if (abs(x - desiredX) > .1f) x = desiredX
        if (abs(y - desiredY) > .1f) y = desiredY
        options.forEach { it.balloon.pointAt(toRight) }
    }

    private class BalloonDrawable(private val ui: Ui) : Drawable() {
        private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
        private var onLeft = false
        fun pointAt(left: Boolean) {
            if (onLeft != left) { onLeft = left; invalidateSelf() }
        }
        override fun draw(canvas: Canvas) {
            val stroke = ui.dp(1).toFloat().coerceAtLeast(1f)
            val tailWidth = ui.dp(6).toFloat()
            val round = ui.dp(14).toFloat().coerceAtMost(bounds.height() / 2f)
            val rect = RectF(if (onLeft) tailWidth else stroke / 2f, stroke / 2f,
                bounds.width() - if (onLeft) stroke / 2f else tailWidth, bounds.height() - stroke / 2f)
            val center = bounds.height() / 2f
            val shape = Path().apply { addRoundRect(rect, round, round, Path.Direction.CW) }
            val tail = Path().apply {
                val edge = if (onLeft) rect.left + stroke else rect.right - stroke
                moveTo(edge, center - ui.dp(4))
                lineTo(if (onLeft) stroke / 2f else bounds.width() - stroke / 2f, center + ui.dp(4))
                lineTo(edge, center + ui.dp(5)); close()
            }
            shape.op(tail, Path.Op.UNION)
            paint.style = Paint.Style.FILL; paint.color = BODY_COLOR; canvas.drawPath(shape, paint)
            paint.style = Paint.Style.STROKE; paint.strokeWidth = stroke; paint.strokeJoin = Paint.Join.ROUND
            paint.color = Color.argb(65, 70, 107, 123); canvas.drawPath(shape, paint)
        }
        override fun setAlpha(alpha: Int) { paint.alpha = alpha; invalidateSelf() }
        override fun setColorFilter(colorFilter: ColorFilter?) { paint.colorFilter = colorFilter; invalidateSelf() }
        @Deprecated("Deprecated in Android") override fun getOpacity() = PixelFormat.TRANSLUCENT
    }

    companion object {
        // Sampled from the blue torso in the bundled character PNG.
        internal val BODY_COLOR = Color.rgb(193, 232, 251)
    }
}
