package kr.talkdock.app.ui

import android.content.Context
import android.graphics.Bitmap
import android.view.Gravity
import android.view.View
import android.widget.*

/** Attached-photo previews followed by a full-width chooser button. */
class DraftPhotoStrip(
    context: Context,
    previews: List<Bitmap?>,
    large: Boolean,
    remove: (Int) -> Unit,
    choose: () -> Unit,
) : LinearLayout(context) {
    init {
        val ui = Ui(context)
        orientation = VERTICAL
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
        if (previews.isNotEmpty()) {
            addView(HorizontalScrollView(context).apply {
                isHorizontalScrollBarEnabled = false
                addView(row)
            }, LayoutParams(-1, -2))
        }
        ui.button(this, if (previews.isEmpty()) "사진 추가" else "사진 다시 선택", false, if (large) 76 else 56, choose).apply {
            contentDescription = if (previews.isEmpty()) "사진 추가하기" else "첨부 사진 다시 선택하기"
        }
    }
}
