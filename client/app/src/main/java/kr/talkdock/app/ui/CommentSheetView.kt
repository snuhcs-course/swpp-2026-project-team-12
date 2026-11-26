package kr.talkdock.app.ui

import android.content.Context
import android.graphics.Rect
import android.graphics.drawable.GradientDrawable
import android.view.Gravity
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ScrollView
import androidx.core.graphics.Insets
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat

/** An opaque reading surface with independently scrolling comments and a fixed composer. */
internal class CommentSheetView(context: Context, private val ui: Ui, dismiss: () -> Unit) : FrameLayout(context) {
    private var bars = Insets.NONE
    private var keyboardVisible = false
    private val placePanelAfterLayout = Runnable { placePanel() }
    val body = ui.column().apply { setPadding(ui.dp(20), 0, ui.dp(20), ui.dp(16)) }
    val footer = ui.column().apply { setPadding(ui.dp(20), ui.dp(12), ui.dp(20), ui.dp(16)) }
    val statusHost = ui.column().apply { setPadding(ui.dp(20), 0, ui.dp(20), 0) }
    private val panel = ui.column().apply {
        tag = "comment-sheet-panel"
        background = GradientDrawable().apply {
            setColor(ui.paper)
            val radius = ui.dp(24).toFloat()
            cornerRadii = floatArrayOf(radius, radius, radius, radius, 0f, 0f, 0f, 0f)
        }
        clipToOutline = true
        elevation = ui.dp(12).toFloat()
        isClickable = true
    }

    init {
        tag = "comment-sheet-root"
        setOnClickListener { dismiss() }
        addView(panel, LayoutParams(-1, -1, Gravity.BOTTOM))
        val header = ui.row().apply {
            tag = "comment-sheet-header"
            setBackgroundColor(ui.paper)
            setPadding(ui.dp(20), ui.dp(8), ui.dp(12), ui.dp(8))
            minimumHeight = ui.dp(64)
        }
        header.addView(ui.text("댓글", 23f, true), LinearLayout.LayoutParams(0, -2, 1f))
        header.addView(ui.iconButton("close", "댓글 닫기", dismiss))
        panel.addView(header, LinearLayout.LayoutParams(-1, -2))
        ui.line(panel)
        panel.addView(statusHost, LinearLayout.LayoutParams(-1, -2))
        panel.addView(ScrollView(context).apply {
            tag = "comment-list-scroll"
            setBackgroundColor(ui.paper)
            isFillViewport = true
            addView(body)
        }, LinearLayout.LayoutParams(-1, 0, 1f))
        ui.line(panel)
        footer.setBackgroundColor(ui.paper)
        panel.addView(footer, LinearLayout.LayoutParams(-1, -2))

        ViewCompat.setOnApplyWindowInsetsListener(this) { _, insets ->
            bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            keyboardVisible = insets.isVisible(WindowInsetsCompat.Type.ime())
            schedulePlacement()
            insets
        }
    }

    override fun onAttachedToWindow() {
        super.onAttachedToWindow()
        post { ViewCompat.requestApplyInsets(this) }
    }

    override fun onSizeChanged(w: Int, h: Int, oldw: Int, oldh: Int) {
        super.onSizeChanged(w, h, oldw, oldh)
        // Updating LayoutParams inside onSizeChanged can leave children measured at the
        // previous window height for this layout pass. Request a fresh measure afterwards.
        schedulePlacement()
    }

    override fun onDetachedFromWindow() {
        removeCallbacks(placePanelAfterLayout)
        super.onDetachedFromWindow()
    }

    private fun schedulePlacement() {
        removeCallbacks(placePanelAfterLayout)
        post(placePanelAfterLayout)
    }

    private fun placePanel() {
        if (height == 0) return
        val visible = Rect()
        getWindowVisibleDisplayFrame(visible)
        val origin = IntArray(2)
        getLocationOnScreen(origin)
        // Older Android versions resize the window to expose IME insets. Only subtract
        // the part still covered on screen, rather than counting that resize twice.
        val coveredBottom = if (keyboardVisible) (origin[1] + height - visible.bottom).coerceAtLeast(0) else 0
        val bottom = maxOf(bars.bottom, coveredBottom)
        val available = (height - bars.top - bottom).coerceAtLeast(0)
        val wantedHeight = if (keyboardVisible) available else minOf((height * .75f).toInt(), available)
        val params = panel.layoutParams as LayoutParams
        if (params.height != wantedHeight || params.bottomMargin != bottom ||
            params.leftMargin != bars.left || params.rightMargin != bars.right) {
            panel.layoutParams = params.apply {
                this.height = wantedHeight
                bottomMargin = bottom
                leftMargin = bars.left
                rightMargin = bars.right
            }
        }
    }
}
