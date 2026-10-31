package kr.talkdock.app.ui

import android.content.Context
import android.content.res.ColorStateList
import android.graphics.Rect
import android.graphics.drawable.RippleDrawable
import android.view.Gravity
import android.view.View
import android.widget.FrameLayout
import android.widget.LinearLayout
import kotlin.math.min

/** Post questions, listening and summaries share one contextual popover. */
class AssistantBubbleMenu(
    context: Context, private val ui: Ui, private val large: Boolean,
    askPost: () -> Unit, findMemories: () -> Unit,
    listenPost: (() -> Unit)? = null, summarizePost: (() -> Unit)? = null,
) : FrameLayout(context) {
    private val content = ui.column(12)
    private val postOption: View
    private var listenOption: View? = null
    private var listenText: android.widget.TextView? = null
    private var summaryOption: View? = null
    init {
        tag = "assistant-bubble-menu"; contentDescription = "토닥 도우미 메뉴"
        background = ui.shape(ui.paper, 26); elevation = ui.dp(8).toFloat()
        addView(android.widget.ScrollView(context).apply { addView(content) }, LayoutParams(-1, -2))
        ui.label(content, "무엇을 도와드릴까요?", if (large) 21f else 18f, true).apply {
            setPadding(ui.dp(8), ui.dp(8), ui.dp(8), ui.dp(12))
        }
        fun option(label: String, symbol: String, action: () -> Unit): View {
            val row = ui.row().apply {
                minimumHeight = ui.dp(if (large) 64 else 56)
                setPadding(ui.dp(8), ui.dp(8), ui.dp(4), ui.dp(8))
                isClickable = true; isFocusable = true; contentDescription = label
                background = RippleDrawable(ColorStateList.valueOf(ui.coral), ui.shape(ui.paper, 14), null)
                setOnClickListener { action() }
            }
            row.addView(IconView(context, symbol, ui.ink), LinearLayout.LayoutParams(ui.dp(24), ui.dp(24)))
            val text = ui.text(label, if (large) 20f else 17f).apply { importantForAccessibility = IMPORTANT_FOR_ACCESSIBILITY_NO }
            row.addView(text,
                LinearLayout.LayoutParams(0, -2, 1f).apply { marginStart = ui.dp(10) })
            row.addView(IconView(context, "next", ui.muted), LinearLayout.LayoutParams(ui.dp(20), ui.dp(20)))
            content.addView(row)
            return row
        }
        postOption = option("이 소식 물어보기", "comment", askPost)
        if (listenPost != null) {
            ui.line(content)
            listenOption = option("음성으로 듣기", "listen", listenPost)
            listenText = (listenOption as LinearLayout).getChildAt(1) as android.widget.TextView
        }
        if (summarizePost != null) {
            ui.line(content)
            summaryOption = option("AI 요약 보기", "digest", summarizePost)
        }
        ui.line(content)
        option("가족 추억 찾기", "family", findMemories)
    }
    fun setPostAvailable(available: Boolean) {
        postOption.isEnabled = available; postOption.alpha = if (available) 1f else .4f
        postOption.contentDescription = if (available) "이 소식 물어보기" else "이 소식 물어보기, 현재 선택된 소식이 없어요"
        listOfNotNull(listenOption, summaryOption).forEach { it.isEnabled = available; it.alpha = if (available) 1f else .4f }
    }
    fun setAudioActive(active: Boolean) {
        val label = if (active) "듣기 중지" else "음성으로 듣기"
        listenText?.text = label
        listenOption?.contentDescription = label
    }
    fun follow(character: FloatingAssistantView, viewport: Rect) {
        val toRight = character.x + character.width / 2f < viewport.exactCenterX()
        val menuWidth = min(ui.dp(if (large) 300 else 260), viewport.width() - ui.dp(16)).coerceAtLeast(1)
        measure(MeasureSpec.makeMeasureSpec(menuWidth, MeasureSpec.EXACTLY),
            MeasureSpec.makeMeasureSpec(viewport.height(), MeasureSpec.AT_MOST))
        val menuHeight = measuredHeight.coerceAtLeast(1)
        if (layoutParams.width != menuWidth || layoutParams.height != menuHeight)
            layoutParams = layoutParams.apply { width = menuWidth; height = menuHeight }
        val desiredX = if (toRight) character.x + ui.dp(12) else character.x + character.width - menuWidth - ui.dp(12)
        x = desiredX.coerceIn(viewport.left.toFloat(), maxOf(viewport.left.toFloat(), (viewport.right - menuWidth).toFloat()))
        val above = character.y - menuHeight - ui.dp(8)
        val desiredY = if (above >= viewport.top) above else character.y + character.height + ui.dp(8)
        y = desiredY.coerceIn(viewport.top.toFloat(), maxOf(viewport.top.toFloat(), (viewport.bottom - menuHeight).toFloat()))
    }
    companion object { internal const val BODY_COLOR = 0xFFFFFFFF.toInt() }
}
