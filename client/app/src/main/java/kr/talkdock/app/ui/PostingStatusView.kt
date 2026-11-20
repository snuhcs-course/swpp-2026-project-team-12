package kr.talkdock.app.ui

import android.content.res.ColorStateList
import android.graphics.Color
import android.text.TextUtils
import android.view.Gravity
import android.view.View
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ProgressBar
import kr.talkdock.app.data.OutgoingPosts

internal class PostingStatusView(
    private val ui: Ui,
    large: Boolean,
    retry: (OutgoingPosts.Upload) -> Unit,
    dismiss: (OutgoingPosts.Upload) -> Unit
) : LinearLayout(ui.context) {
    private var current: OutgoingPosts.Upload? = null
    private val ink = Color.rgb(55, 55, 60)
    private val muted = Color.rgb(91, 91, 98)
    private val thumbnail = ImageView(context).apply {
        scaleType = ImageView.ScaleType.CENTER_CROP
        background = ui.shape(Color.TRANSPARENT, 8)
        clipToOutline = true
        importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
    }
    private val title = ui.text("", if (large) 19f else 15f, true, ink).apply {
        accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
    }
    private val detail = ui.text("", if (large) 16f else 13f, color = muted).apply {
        maxLines = 1
        ellipsize = TextUtils.TruncateAt.END
    }
    private val percent = ui.text("", if (large) 16f else 13f, true, muted)
    private val progress = ProgressBar(context, null, android.R.attr.progressBarStyleHorizontal).apply {
        progressTintList = ColorStateList.valueOf(Color.rgb(104, 104, 113))
        progressBackgroundTintList = ColorStateList.valueOf(Color.rgb(206, 206, 212))
        importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
    }
    private val actions = ui.row()

    init {
        tag = "posting-status"
        visibility = GONE
        orientation = VERTICAL
        background = ui.shape(Color.argb(227, 236, 236, 239), 14)
        setPadding(ui.dp(12), ui.dp(8), ui.dp(12), ui.dp(8))
        val row = ui.row()
        row.addView(thumbnail, LayoutParams(ui.dp(42), ui.dp(42)).apply { marginEnd = ui.dp(10) })
        row.addView(ui.column().apply { addView(title); addView(detail) }, LayoutParams(0, -2, 1f))
        row.addView(percent, LayoutParams(-2, -2).apply { marginStart = ui.dp(8) })
        addView(row)
        addView(progress, LayoutParams(-1, ui.dp(5)).apply { topMargin = ui.dp(5) })
        actions.gravity = Gravity.END or Gravity.CENTER_VERTICAL
        ui.ghost(actions, "다시 시도") { current?.let(retry) }.layoutParams = LayoutParams(-2, ui.dp(48))
        actions.addView(ui.iconButton("close", "전송 상태 닫기") { current?.let(dismiss) })
        addView(actions)
    }

    fun bind(items: List<OutgoingPosts.Upload>) {
        val next = items.firstOrNull { it.running } ?: items.firstOrNull()
        if (current !== next) {
            current = next
            thumbnail.setImageBitmap(next?.thumbnail)
        }
        visibility = if (next == null) GONE else VISIBLE
        if (next == null) return
        val post = next.kind == OutgoingPosts.Kind.POST
        val status = when {
            next.error != null -> if (post) "게시글을 올리지 못했어요" else "댓글을 보내지 못했어요"
            post && next.progress == 100 -> "게시 확인 중"
            post -> "게시글 업로드 중"
            else -> "댓글 전송 중"
        }
        if (title.text != status) title.text = status
        val preview = next.text.ifBlank { "사진 ${next.files.size}장" }
        detail.text = if (items.size == 1) preview else "+${items.size - 1} · $preview"
        thumbnail.visibility = if (next.thumbnail == null) GONE else VISIBLE
        percent.visibility = if (post && next.running && next.progress < 100) VISIBLE else GONE
        percent.text = "${next.progress}%"
        progress.visibility = if (post && next.running) VISIBLE else GONE
        progress.progress = next.progress
        actions.visibility = if (next.error != null) VISIBLE else GONE
    }
}
