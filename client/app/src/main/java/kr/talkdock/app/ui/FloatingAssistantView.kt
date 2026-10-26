package kr.talkdock.app.ui

import android.content.Context
import android.graphics.Rect
import android.graphics.Matrix
import android.os.Bundle
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewConfiguration
import android.view.ViewTreeObserver
import android.view.accessibility.AccessibilityNodeInfo
import android.widget.FrameLayout
import android.widget.ImageView
import kr.talkdock.app.R
import kotlin.math.abs
import kotlin.math.min
import kotlin.math.roundToInt

/** One viewport overlay, independent of the scrolling post cards. Never starts an AI request. */
class FloatingAssistantView(
    context: Context,
    private val ui: Ui,
    private val viewport: () -> Rect?,
    private val onPositionChanged: (Float) -> Unit,
    private val onMoveStarted: () -> Unit = {},
    onOpen: () -> Unit,
) : FrameLayout(context) {
    private val preferences = context.getSharedPreferences("talkdock-assistant", Context.MODE_PRIVATE)
    private var anchor = AssistantAnchor(
        if (preferences.getBoolean("left", false)) AssistantEdge.LEFT else AssistantEdge.RIGHT,
        preferences.getFloat("height", .62f).takeIf { it.isFinite() } ?: .62f,
    )
    private var startRawX = 0f
    private var startRawY = 0f
    private var startX = 0f
    private var startY = 0f
    private var dragging = false
    private var touching = false
    private val slop = ViewConfiguration.get(context).scaledTouchSlop
    private var observer: ViewTreeObserver? = null
    private val layoutObserver = ViewTreeObserver.OnGlobalLayoutListener { refreshPosition() }
    private val scrollObserver = ViewTreeObserver.OnScrollChangedListener { reportPosition() }
    private val characterImage = ImageView(context).apply {
        setImageResource(R.drawable.assistant_character)
        scaleType = ImageView.ScaleType.MATRIX
        scaleX = if (anchor.edge == AssistantEdge.LEFT) 1f else -1f
        importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
    }

    init {
        layoutParams = LayoutParams((ui.dp(76) * 1.2f).roundToInt(), (ui.dp(88) * 1.2f).roundToInt(), Gravity.TOP or Gravity.LEFT)
        isClickable = true; isFocusable = true
        contentDescription = "토닥 도우미. 누르면 질문하기, 끌어서 위치 옮기기"
        addView(characterImage, LayoutParams(-1, -1))
        characterImage.addOnLayoutChangeListener { _, left, top, right, bottom, oldLeft, oldTop, oldRight, oldBottom ->
            if (right - left != oldRight - oldLeft || bottom - top != oldBottom - oldTop) {
                alignCharacterBody()
            }
        }
        setOnClickListener { onOpen() }
    }

    private fun alignCharacterBody() {
        val drawable = characterImage.drawable ?: return
        val sourceWidth = drawable.intrinsicWidth.toFloat()
        val sourceHeight = drawable.intrinsicHeight.toFloat()
        if (sourceWidth <= 0 || sourceHeight <= 0) return
        // The supplied PNG's straight torso cut is at x=50 on a 1151px canvas.
        // Align that cut, rather than transparent padding, to the docking edge.
        // Mirroring the ImageView then aligns the same cut with the right edge.
        val bodyLeft = sourceWidth * CHARACTER_BODY_LEFT_FRACTION
        val scale = min(characterImage.width / (sourceWidth - bodyLeft), characterImage.height / sourceHeight)
        characterImage.imageMatrix = Matrix().apply {
            setScale(scale, scale)
            postTranslate(-bodyLeft * scale, (characterImage.height - sourceHeight * scale) / 2f)
        }
    }

    private fun bounds(): AssistantBounds? = viewport()?.let {
        AssistantBounds(it.left.toFloat(), it.top.toFloat(), it.right.toFloat(), it.bottom.toFloat())
    }

    /** Attach menus to the visible hand, excluding the PNG's transparent canvas. */
    internal fun bubbleAttachmentX(): Float {
        val drawable = characterImage.drawable ?: return x + width / 2f
        val point = floatArrayOf(drawable.intrinsicWidth * (1122f / 1151f), 0f)
        characterImage.imageMatrix.mapPoints(point)
        val innerEdge = if (characterImage.scaleX < 0) width - point[0] else point[0]
        return x + innerEdge.coerceIn(0f, width.toFloat())
    }

    fun refreshPosition() {
        if (width == 0 || height == 0) return
        val area = bounds() ?: return
        if (!touching) {
            val point = AssistantPlacement.position(anchor, area, width.toFloat(), height.toFloat())
            x = point.x; y = point.y
        }
        updateCharacterFacing(area)
        reportPosition()
    }

    /** Keep the source artwork on the left; mirror only the image on the right. */
    private fun updateCharacterFacing(area: AssistantBounds) {
        val onLeft = x + width / 2f < (area.left + area.right) / 2f
        characterImage.scaleX = if (onLeft) 1f else -1f
    }

    private fun reportPosition() { if (isAttachedToWindow && height > 0) onPositionChanged(y + height / 2f) }

    private fun saveAnchor() {
        preferences.edit().putBoolean("left", anchor.edge == AssistantEdge.LEFT)
            .putFloat("height", anchor.fraction).apply()
        refreshPosition()
    }

    override fun onTouchEvent(event: MotionEvent): Boolean {
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                startRawX = event.rawX; startRawY = event.rawY; startX = x; startY = y
                dragging = false; touching = true; isPressed = true
                parent.requestDisallowInterceptTouchEvent(true)
                return true
            }
            MotionEvent.ACTION_MOVE -> {
                val dx = event.rawX - startRawX; val dy = event.rawY - startRawY
                if (!dragging && (abs(dx) > slop || abs(dy) > slop)) {
                    dragging = true; isPressed = false
                    onMoveStarted()
                }
                if (dragging) bounds()?.let {
                    x = (startX + dx).coerceIn(it.left, maxOf(it.left, it.right - width))
                    y = (startY + dy).coerceIn(it.top, maxOf(it.top, it.bottom - height))
                    updateCharacterFacing(it)
                    reportPosition()
                }
                return true
            }
            MotionEvent.ACTION_UP -> {
                touching = false; isPressed = false
                parent.requestDisallowInterceptTouchEvent(false)
                if (dragging) bounds()?.let {
                    anchor = AssistantPlacement.dropped(x, y, it, width.toFloat(), height.toFloat())
                    saveAnchor()
                } else performClick()
                return true
            }
            MotionEvent.ACTION_CANCEL -> {
                touching = false; dragging = false; isPressed = false
                parent.requestDisallowInterceptTouchEvent(false)
                refreshPosition()
                return true
            }
        }
        return super.onTouchEvent(event)
    }

    override fun performClick(): Boolean = super.performClick()

    override fun onInitializeAccessibilityNodeInfo(info: AccessibilityNodeInfo) {
        super.onInitializeAccessibilityNodeInfo(info)
        info.className = "android.widget.Button"
        info.addAction(AccessibilityNodeInfo.AccessibilityAction(ACTION_LEFT, "왼쪽 가장자리로 이동"))
        info.addAction(AccessibilityNodeInfo.AccessibilityAction(ACTION_RIGHT, "오른쪽 가장자리로 이동"))
        info.addAction(AccessibilityNodeInfo.AccessibilityAction(ACTION_UP, "위로 이동"))
        info.addAction(AccessibilityNodeInfo.AccessibilityAction(ACTION_DOWN, "아래로 이동"))
    }

    override fun performAccessibilityAction(action: Int, arguments: Bundle?): Boolean {
        anchor = when (action) {
            ACTION_LEFT -> anchor.copy(edge = AssistantEdge.LEFT)
            ACTION_RIGHT -> anchor.copy(edge = AssistantEdge.RIGHT)
            ACTION_UP -> anchor.copy(fraction = (anchor.fraction - .15f).coerceAtLeast(0f))
            ACTION_DOWN -> anchor.copy(fraction = (anchor.fraction + .15f).coerceAtMost(1f))
            else -> return super.performAccessibilityAction(action, arguments)
        }
        onMoveStarted()
        saveAnchor()
        return true
    }

    override fun onAttachedToWindow() {
        super.onAttachedToWindow()
        observer = viewTreeObserver.also {
            it.addOnGlobalLayoutListener(layoutObserver); it.addOnScrollChangedListener(scrollObserver)
        }
        post { refreshPosition() }
    }

    override fun onDetachedFromWindow() {
        observer?.takeIf { it.isAlive }?.let {
            it.removeOnGlobalLayoutListener(layoutObserver); it.removeOnScrollChangedListener(scrollObserver)
        }
        observer = null
        super.onDetachedFromWindow()
    }

    companion object {
        internal const val CHARACTER_BODY_LEFT_FRACTION = 50f / 1151f
        const val ACTION_LEFT = 0x01030001
        const val ACTION_RIGHT = 0x01030002
        const val ACTION_UP = 0x01030003
        const val ACTION_DOWN = 0x01030004
    }
}
