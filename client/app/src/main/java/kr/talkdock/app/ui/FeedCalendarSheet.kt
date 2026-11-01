package kr.talkdock.app.ui

import android.content.Context
import android.graphics.Typeface
import android.view.Gravity
import android.view.View
import android.widget.LinearLayout
import android.widget.TextView
import java.time.LocalDate
import java.time.YearMonth
import java.time.format.TextStyle
import java.util.Locale

/** Bottom-sheet month calendar; days after [today] stay visible but cannot be chosen. */
class FeedCalendarSheet(
    context: Context,
    private val ui: Ui,
    private val large: Boolean,
    private val selected: LocalDate,
    private val today: LocalDate,
    private val onPick: (LocalDate) -> Unit,
) : LinearLayout(context) {
    private var month = YearMonth.from(selected)
    private val title = ui.text("", if (large) 24f else 21f, true)
    private val previous = arrow("back", "이전 달") { show(month.minusMonths(1)) }
    private val next = arrow("next", "다음 달") { show(month.plusMonths(1)) }
    private val grid = ui.column()

    init {
        orientation = VERTICAL
        setPadding(ui.dp(20), ui.dp(10), ui.dp(20), ui.dp(24))
        background = ui.shape(ui.paper, 0).apply {
            val r = ui.dp(28).toFloat(); cornerRadii = floatArrayOf(r, r, r, r, 0f, 0f, 0f, 0f)
        }
        addView(View(context).apply { background = ui.shape(ui.border, 3) },
            LayoutParams(ui.dp(40), ui.dp(5)).apply { gravity = Gravity.CENTER_HORIZONTAL; bottomMargin = ui.dp(14) })
        val header = ui.row().apply { setPadding(ui.dp(6), 0, 0, ui.dp(10)) }
        header.addView(title, LayoutParams(0, -2, 1f))
        header.addView(previous); header.addView(next)
        addView(header)
        val weekdays = ui.row()
        listOf("일", "월", "화", "수", "목", "금", "토").forEach { day ->
            weekdays.addView(ui.text(day, if (large) 17f else 14f, color = ui.muted).apply {
                gravity = Gravity.CENTER; importantForAccessibility = IMPORTANT_FOR_ACCESSIBILITY_NO
            }, LayoutParams(0, ui.dp(32), 1f))
        }
        addView(weekdays)
        addView(grid)
        show(month)
    }

    private fun arrow(symbol: String, description: String, action: () -> Unit) =
        IconView(context, symbol, ui.ink, true).apply {
            contentDescription = description; isClickable = true; isFocusable = true
            background = ui.shape(ui.paper, 24)
            layoutParams = LayoutParams(ui.dp(48), ui.dp(48))
            setOnClickListener { if (isEnabled) action() }
        }

    private fun show(target: YearMonth) {
        month = target
        title.text = "${target.year}년 ${target.monthValue}월"
        val canGoForward = target.isBefore(YearMonth.from(today))
        next.isEnabled = canGoForward; next.alpha = if (canGoForward) 1f else .3f
        grid.removeAllViews()
        // Sunday-first grid; leading blanks shift the 1st under its weekday.
        val leading = target.atDay(1).dayOfWeek.value % 7
        val cells = (List(leading) { null } + (1..target.lengthOfMonth()).map { target.atDay(it) }).chunked(7)
        cells.forEach { week ->
            val row = ui.row()
            (0 until 7).forEach { index -> row.addView(cell(week.getOrNull(index)), LayoutParams(0, ui.dp(if (large) 58 else 52), 1f)) }
            grid.addView(row)
        }
    }

    private fun cell(date: LocalDate?): View {
        if (date == null) return View(context)
        val future = date.isAfter(today)
        val chosen = date == selected
        val label = TextView(context).apply {
            text = date.dayOfMonth.toString(); gravity = Gravity.CENTER; textSize = if (large) 21f else 18f
            includeFontPadding = false
            typeface = Typeface.create(ui.font, if (chosen || date == today) Typeface.BOLD else Typeface.NORMAL)
            setTextColor(when { chosen -> ui.paper; future -> ui.border; date == today -> ui.coralDeep; else -> ui.ink })
            if (chosen) background = ui.shape(ui.coralDeep, 22)
        }
        return android.widget.FrameLayout(context).apply {
            addView(label, android.widget.FrameLayout.LayoutParams(ui.dp(44), ui.dp(44), Gravity.CENTER))
            tag = "calendar-day:$date"
            val weekday = date.dayOfWeek.getDisplayName(TextStyle.FULL, Locale.KOREAN)
            contentDescription = "${date.monthValue}월 ${date.dayOfMonth}일 $weekday" + if (date == today) ", 오늘" else ""
            if (chosen) androidx.core.view.ViewCompat.setStateDescription(this, "선택됨")
            isEnabled = !future; isClickable = !future; isFocusable = !future
            if (!future) setOnClickListener { onPick(date) }
        }
    }
}
