package kr.talkdock.app.ui

import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.content.res.ColorStateList
import android.graphics.drawable.RippleDrawable
import android.text.TextUtils
import android.view.Gravity
import android.view.MotionEvent
import android.view.ScaleGestureDetector
import android.view.ViewConfiguration
import android.widget.FrameLayout
import kr.talkdock.app.data.*
import kotlin.math.abs
import kotlin.math.roundToInt

/** A two-axis viewport with native, accessible node buttons above the connectors. */
class FamilyTreeView(context: Context, private val ui: Ui, private val draft: FamilyTreeDraft, private val myName: String,
                     private val onAdd: (TreeAction) -> Unit, private val onPerson: (String) -> Unit,
                     private val editable: Boolean = true) : FrameLayout(context) {
    private var drawing = FamilyTreeLayout.drawing(draft, editable)
    private val density = resources.displayMetrics.density
    private fun px(value: Float) = value * density
    private val linePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = ui.skyDeep; strokeWidth = px(2f); strokeCap = Paint.Cap.ROUND }
    private val world = object : FrameLayout(context) {
        init { setWillNotDraw(false); pivotX = 0f; pivotY = 0f }
        override fun onDraw(canvas: Canvas) {
            super.onDraw(canvas)
            fun line(x1: Float, y1: Float, x2: Float, y2: Float) = canvas.drawLine(px(x1), px(y1), px(x2), px(y2), linePaint)
            drawing.pairs.forEach {
                val a = drawing.points.getValue(it.first); val b = drawing.points.getValue(it.second)
                line(a.x, a.y, b.x, b.y)
            }
            drawing.parents.groupBy { it.child }.map { (child, links) -> links.map { it.parent }.sorted() to child }
                .groupBy({ it.first }, { it.second }).forEach { (parents, children) ->
                    val pp = parents.map { drawing.points.getValue(it) }
                    val cp = children.map { drawing.points.getValue(it) }
                    val center = pp.map { it.x }.average().toFloat()
                    val parentY = pp.first().y
                    line(pp.minOf { it.x }, parentY, pp.maxOf { it.x }, parentY)
                    val junction = (parentY + cp.first().y) / 2f
                    line(center, parentY, center, junction)
                    line(minOf(center, cp.minOf { it.x }), junction, maxOf(center, cp.maxOf { it.x }), junction)
                    cp.forEach { line(it.x, junction, it.x, it.y) }
                }
        }
    }
    private val slop = ViewConfiguration.get(context).scaledTouchSlop
    private var startX = 0f; private var startY = 0f
    private var originX = 0f; private var originY = 0f
    private var dragging = false
    private val scaling = ScaleGestureDetector(context, object : ScaleGestureDetector.SimpleOnScaleGestureListener() {
        override fun onScale(detector: ScaleGestureDetector): Boolean {
            val scale = (world.scaleX * detector.scaleFactor).coerceIn(.4f, 3f)
            val ratio = scale / world.scaleX
            world.translationX = detector.focusX - (detector.focusX - world.translationX) * ratio
            world.translationY = detector.focusY - (detector.focusY - world.translationY) * ratio
            world.scaleX = scale; world.scaleY = scale
            clampPosition()
            return true
        }
    }).apply { isQuickScaleEnabled = false }

    init {
        clipChildren = true; clipToOutline = true; background = ui.shape(ui.sky, 20, stroke = true)
        addView(world); render(draft.ownerId)
    }

    fun render(focusId: String? = null) {
        drawing = FamilyTreeLayout.drawing(draft, editable)
        world.removeAllViews()
        world.layoutParams = LayoutParams(px(drawing.width).roundToInt(), px(drawing.height).roundToInt())
        drawing.nodes.forEach { node ->
            val point = drawing.points.getValue(node.id)
            val selected = node.id == draft.selectedId
            val size = if (node.action != null) 66f else 82f
            val label = when { node.action != null -> "+"; selected -> myName; node.label.isNotBlank() -> node.label; else -> "빈 가족" }
            val view = ui.text(label, if (node.action != null) 30f else 17f, true,
                if (selected) ui.paper else if (node.action != null) ui.coralDeep else ui.ink).apply {
                gravity = Gravity.CENTER; maxLines = 2; ellipsize = TextUtils.TruncateAt.END
                setPadding(ui.dp(6), ui.dp(3), ui.dp(6), ui.dp(3))
                val fill = when { selected -> ui.coralDeep; node.occupied -> ui.coral; node.action != null -> ui.milk; else -> ui.paper }
                val shape = ui.shape(fill, 20, stroke = true).apply {
                    if (node.action != null) setStroke(ui.dp(1), ui.coralDeep, px(5f), px(4f))
                    else if (selected) setStroke(ui.dp(2), ui.coralDeep)
                }
                background = RippleDrawable(ColorStateList.valueOf(ui.border), shape, null)
                isClickable = editable; isFocusable = editable
                contentDescription = if (node.action != null) {
                    val anchor = draft.people.getValue(node.action.anchor).name.ifBlank { "빈 가족" }
                    anchor + "의 " + when (node.action.relation) { "father" -> "아버지 추가"; "mother" -> "어머니 추가"; "parent" -> "부모 추가"; "spouse" -> "배우자 추가"; else -> "자녀 추가" }
                } else label + if (node.occupied) ", 가입한 가족" else if (editable) ", 내 자리로 선택 가능" else ""
                if (editable) setOnClickListener { node.action?.let(onAdd) ?: onPerson(node.id) }
            }
            world.addView(view, LayoutParams(px(size).roundToInt(), px(size).roundToInt()).apply {
                leftMargin = px(point.x - size / 2).roundToInt(); topMargin = px(point.y - size / 2).roundToInt()
            })
            if (node.action != null) {
                val caption = when (node.action.relation) { "father" -> "아버지"; "mother" -> "어머니"; "parent" -> "부모"; "spouse" -> "배우자"; else -> "자녀" }
                world.addView(ui.text(caption, 13f, color = ui.muted).apply { gravity = Gravity.CENTER; importantForAccessibility = IMPORTANT_FOR_ACCESSIBILITY_NO },
                    LayoutParams(ui.dp(100), ui.dp(24)).apply { leftMargin = px(point.x - 50).roundToInt(); topMargin = px(point.y + size / 2 + 3).roundToInt() })
            }
        }
        world.invalidate()
        if (focusId != null) post { centerOn(focusId) } else post { clampPosition() }
    }

    fun centerOn(id: String) {
        val point = drawing.points[id] ?: return
        world.translationX = width / 2f - px(point.x) * world.scaleX
        world.translationY = height * (if (id == draft.ownerId) .6f else .5f) - px(point.y) * world.scaleY
        clampPosition()
    }

    private fun clampPosition() {
        val margin = px(40f)
        val right = width - world.width * world.scaleX - margin
        val bottom = height - world.height * world.scaleY - margin
        world.translationX = world.translationX.coerceIn(minOf(margin, right), maxOf(margin, right))
        world.translationY = world.translationY.coerceIn(minOf(margin, bottom), maxOf(margin, bottom))
    }

    override fun dispatchTouchEvent(event: MotionEvent): Boolean {
        scaling.onTouchEvent(event)
        return super.dispatchTouchEvent(event)
    }

    override fun onInterceptTouchEvent(event: MotionEvent): Boolean {
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                parent.requestDisallowInterceptTouchEvent(true)
                startX = event.x; startY = event.y; originX = world.translationX; originY = world.translationY; dragging = false
            }
            MotionEvent.ACTION_MOVE -> if (abs(event.x - startX) > slop || abs(event.y - startY) > slop) dragging = true
            MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> parent.requestDisallowInterceptTouchEvent(false)
        }
        if (event.pointerCount > 1) dragging = true
        return dragging
    }

    override fun onTouchEvent(event: MotionEvent): Boolean {
        if (event.pointerCount > 1) dragging = true
        if (event.actionMasked == MotionEvent.ACTION_POINTER_UP) {
            val remaining = if (event.actionIndex == 0) 1 else 0
            startX = event.getX(remaining); startY = event.getY(remaining)
            originX = world.translationX; originY = world.translationY
        }
        if (event.actionMasked == MotionEvent.ACTION_MOVE && event.pointerCount == 1 && !scaling.isInProgress) {
            world.translationX = originX + event.x - startX; world.translationY = originY + event.y - startY
            clampPosition()
        }
        if (event.actionMasked == MotionEvent.ACTION_UP || event.actionMasked == MotionEvent.ACTION_CANCEL) {
            parent.requestDisallowInterceptTouchEvent(false); if (!dragging) performClick(); dragging = false
        }
        return true
    }
    override fun performClick(): Boolean { super.performClick(); return true }
}
