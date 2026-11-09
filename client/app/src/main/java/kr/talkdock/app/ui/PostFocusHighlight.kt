package kr.talkdock.app.ui

import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.graphics.Rect
import android.graphics.RectF
import android.view.View
import android.widget.FrameLayout

/** Keep the current card clear and shade its surroundings without intercepting input. */
class PostFocusHighlight(private val ui: Ui, private val root: FrameLayout) {
    private var card: View? = null
    private val shade = object : View(ui.context) {
        private val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.argb(102, 40, 46, 52) }
        init {
            tag = "post-focus-shade"
            isClickable = false; isFocusable = false
            importantForAccessibility = IMPORTANT_FOR_ACCESSIBILITY_NO
            setWillNotDraw(false)
        }
        override fun onDraw(canvas: Canvas) {
            super.onDraw(canvas)
            val target = card ?: return
            val visible = Rect()
            if (!target.getGlobalVisibleRect(visible)) return
            val origin = IntArray(2); getLocationOnScreen(origin)
            visible.offset(-origin[0], -origin[1])
            val position = IntArray(2); target.getLocationOnScreen(position)
            val fullCard = RectF((position[0] - origin[0]).toFloat(), (position[1] - origin[1]).toFloat(),
                (position[0] - origin[0] + target.width).toFloat(), (position[1] - origin[1] + target.height).toFloat())
            val hole = Path().apply { addRoundRect(fullCard, ui.dp(20).toFloat(), ui.dp(20).toFloat(), Path.Direction.CW) }
            // Intersect with the actual visible scroll area so the hole never clears
            // the fixed header or navigation when the card extends off screen.
            hole.op(Path().apply { addRect(RectF(visible), Path.Direction.CW) }, Path.Op.INTERSECT)
            val outside = Path().apply { addRect(0f, 0f, width.toFloat(), height.toFloat(), Path.Direction.CW) }
            outside.op(hole, Path.Op.DIFFERENCE)
            canvas.drawPath(outside, paint)
        }
    }

    fun show(next: View?) {
        if (next === card) {
            if (next != null) shade.invalidate() // Same post, different visible bounds after scrolling.
            return
        }
        clear()
        val target = next ?: return
        card = target; target.isActivated = true
        // Page first, then shade, then the assistant and its menu remain fully colored.
        root.addView(shade, minOf(1, root.childCount), FrameLayout.LayoutParams(-1, -1))
        shade.invalidate()
    }

    fun clear() {
        (shade.parent as? FrameLayout)?.removeView(shade)
        card?.isActivated = false
        card = null
    }
}
