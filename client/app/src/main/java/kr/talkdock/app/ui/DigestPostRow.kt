package kr.talkdock.app.ui

import android.content.res.ColorStateList
import android.graphics.Color
import android.graphics.drawable.RippleDrawable
import android.text.TextUtils
import android.view.Gravity
import android.view.View
import android.view.accessibility.AccessibilityNodeInfo
import android.widget.LinearLayout
import org.json.JSONObject

/** A text-only link to a digest's source post; photos are loaded on the detail screen. */
class DigestPostRow(ui: Ui, post: JSONObject, large: Boolean, openPost: () -> Unit) : LinearLayout(ui.context) {
    init {
        orientation = HORIZONTAL
        gravity = Gravity.CENTER_VERTICAL
        minimumHeight = ui.dp(if (large) 100 else 88)
        setPadding(0, ui.dp(16), 0, ui.dp(16))
        background = RippleDrawable(ColorStateList.valueOf(ui.border), ui.shape(ui.paper, 0), null)
        isClickable = true
        isFocusable = true
        val name = post.optString("author_name").ifBlank { "가족" }
        val preview = post.optString("caption").replace(Regex("\\s+"), " ").trim().ifBlank { "사진으로 전한 소식" }
        contentDescription = "$name, $preview. 원문 보기"
        setOnClickListener { openPost() }

        val tones = listOf(
            Color.rgb(235, 226, 237) to Color.rgb(133, 104, 139),
            Color.rgb(226, 235, 240) to ui.skyDeep,
            Color.rgb(232, 236, 223) to Color.rgb(105, 117, 81),
            ui.coral to ui.coralDeep,
            Color.rgb(247, 235, 213) to Color.rgb(145, 115, 66),
        )
        val (backgroundColor, foregroundColor) = tones[Math.floorMod(post.optInt("author_id", name.hashCode()), tones.size)]
        addView(ui.text(name.take(1), if (large) 21f else 18f, true, foregroundColor).apply {
            gravity = Gravity.CENTER
            setSingleLine(true)
            background = ui.shape(backgroundColor, 32)
            importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
        }, LayoutParams(ui.dp(if (large) 52 else 46), ui.dp(if (large) 52 else 46)))

        val labels = ui.column().apply {
            setPadding(ui.dp(14), 0, ui.dp(12), 0)
            importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS
        }
        ui.label(labels, name, if (large) 22f else 18f, true).apply {
            setSingleLine(true)
            ellipsize = TextUtils.TruncateAt.END
        }
        ui.gap(labels, 6)
        ui.label(labels, preview, if (large) 19f else 16f, color = ui.muted).apply {
            setSingleLine(true)
            ellipsize = TextUtils.TruncateAt.END
        }
        addView(labels, LayoutParams(0, LayoutParams.WRAP_CONTENT, 1f))
        addView(IconView(context, "back", ui.hintGray).apply {
            rotation = 180f
            importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
        }, LayoutParams(ui.dp(20), ui.dp(20)))
    }

    override fun onInitializeAccessibilityNodeInfo(info: AccessibilityNodeInfo) {
        super.onInitializeAccessibilityNodeInfo(info)
        info.className = "android.widget.Button"
    }
}
