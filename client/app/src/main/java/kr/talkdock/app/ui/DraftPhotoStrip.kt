package kr.talkdock.app.ui

import android.content.Context
import android.graphics.Bitmap
import android.view.Gravity
import android.view.View
import android.widget.*

/** Figma compose screen: square attachments in one horizontal strip. */
class DraftPhotoStrip(
    context: Context,
    previews: List<Bitmap?>,
    large: Boolean,
    remove: (Int) -> Unit,
    choose: () -> Unit,
) : HorizontalScrollView(context) {
    init {
        val ui = Ui(context)
        isHorizontalScrollBarEnabled = false
        val row = ui.row().apply { gravity = Gravity.TOP }
        val side = if (large) 148 else 108
        previews.forEachIndexed { index, bitmap ->
            val column = ui.column()
            val frame = FrameLayout(context).apply { background = ui.shape(ui.sky); clipToOutline = true }
            val image = ImageView(context).apply {
                scaleType = ImageView.ScaleType.FIT_CENTER; setImageBitmap(bitmap)
                contentDescription = "첨부 사진 ${index + 1}"
            }
            frame.addView(image, FrameLayout.LayoutParams(-1, -1))
            if (!large) {
                val close = FrameLayout(context).apply {
                    contentDescription = "${index + 1}번째 사진 빼기"; isClickable = true; isFocusable = true
                    setOnClickListener { remove(index) }
                }
                val circle = FrameLayout(context).apply {
                    background = ui.shape(ui.milk, 16)
                    importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
                }
                circle.addView(IconView(context, "close", ui.ink), FrameLayout.LayoutParams(ui.dp(16), ui.dp(16), Gravity.CENTER))
                close.addView(circle, FrameLayout.LayoutParams(ui.dp(28), ui.dp(28), Gravity.CENTER))
                frame.addView(close, FrameLayout.LayoutParams(ui.dp(48), ui.dp(48), Gravity.TOP or Gravity.END))
            }
            column.addView(frame, LinearLayout.LayoutParams(ui.dp(side), ui.dp(side)))
            if (large) ui.button(column, "이 사진 빼기", false, 76) { remove(index) }
            row.addView(column, LinearLayout.LayoutParams(ui.dp(side), -2).apply { marginEnd = ui.dp(12) })
        }
        val add = ui.column(12).apply {
            gravity = Gravity.CENTER; background = ui.shape(ui.sky)
            isClickable = true; isFocusable = true
            contentDescription = if (previews.isEmpty()) "사진 추가하기" else "첨부 사진 다시 선택하기"
            setOnClickListener { choose() }
        }
        add.addView(IconView(context, "photo", ui.skyDeep), LinearLayout.LayoutParams(ui.dp(28), ui.dp(28)))
        ui.gap(add, 8)
        ui.label(add, if (previews.isEmpty()) "사진 추가" else "다시 선택", if (large) 20f else 14f, color = ui.skyDeep)
        row.addView(add, LinearLayout.LayoutParams(ui.dp(side), ui.dp(side)))
        addView(row)
    }
}
