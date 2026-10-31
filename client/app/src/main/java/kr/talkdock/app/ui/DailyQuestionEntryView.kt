package kr.talkdock.app.ui

import android.content.Context
import android.content.res.ColorStateList
import android.graphics.drawable.RippleDrawable
import android.text.TextUtils
import android.view.Gravity
import android.view.View
import android.widget.LinearLayout
import androidx.core.view.ViewCompat

/** A fixed, quiet preview that stays outside the swipeable family letters. */
class DailyQuestionEntryView(context: Context, ui: Ui, large: Boolean, onOpen: () -> Unit) : LinearLayout(context) {
    private val preview = ui.text("가족과 나눌 오늘의 질문을 확인해 보세요", if (large) 22f else 16f, true).apply {
        maxLines = 1; ellipsize = TextUtils.TruncateAt.END
        importantForAccessibility = IMPORTANT_FOR_ACCESSIBILITY_NO
    }
    private val unreadDot = View(context).apply {
        background = ui.shape(ui.coralDeep, 4)
        importantForAccessibility = IMPORTANT_FOR_ACCESSIBILITY_NO
    }

    init {
        orientation = HORIZONTAL; gravity = Gravity.CENTER_VERTICAL
        minimumHeight = ui.dp(if (large) 76 else 56)
        setPadding(ui.dp(12), ui.dp(8), ui.dp(12), ui.dp(8))
        background = RippleDrawable(ColorStateList.valueOf(ui.blush), ui.shape(ui.coral, 16), null)
        isClickable = true; isFocusable = true; contentDescription = "오늘의 질문"
        setOnClickListener { onOpen() }
        addView(IconView(context, "chat", ui.coralDeep), LayoutParams(ui.dp(26), ui.dp(26)))
        val words = ui.column()
        ui.label(words, "오늘의 질문", if (large) 16f else 12f, true, ui.coralDeep).importantForAccessibility = IMPORTANT_FOR_ACCESSIBILITY_NO
        ui.gap(words, 2); words.addView(preview)
        addView(words, LayoutParams(0, -2, 1f).apply { marginStart = ui.dp(10); marginEnd = ui.dp(8) })
        addView(unreadDot, LayoutParams(ui.dp(7), ui.dp(7)).apply { marginEnd = ui.dp(8) })
        addView(IconView(context, "next", ui.coralDeep), LayoutParams(ui.dp(20), ui.dp(20)))
    }

    fun bind(title: String, unread: Boolean) {
        preview.text = title.ifBlank { "가족과 나눌 오늘의 질문을 확인해 보세요" }
        unreadDot.visibility = if (unread) VISIBLE else GONE
        ViewCompat.setStateDescription(this, "${preview.text}. " + if (unread) "새 질문이나 가족 이야기가 있어요" else "확인한 질문")
    }
}
