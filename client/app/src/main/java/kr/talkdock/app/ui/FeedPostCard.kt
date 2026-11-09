package kr.talkdock.app.ui

import android.content.Context
import android.view.Gravity
import android.view.View
import android.widget.LinearLayout
import android.widget.TextView
import org.json.JSONObject

/** A vertically scrolling post; expanding text never rebuilds or moves the feed. */
class FeedPostCard(
    context: Context, private val ui: Ui, val post: JSONObject, private val elder: Boolean,
    author: (LinearLayout, JSONObject) -> Unit,
    photos: (LinearLayout, JSONObject) -> Unit,
    val audio: InlinePostAudio,
    comment: () -> Unit, voice: () -> Unit, open: () -> Unit,
) : LinearLayout(context) {
    val comments = ui.column()
    var commentsLoaded = false
    var commentsLoading = false
    private val commentLabel = ui.text("", if (elder) 21f else 16f)

    init {
        isClickable = true; isFocusable = true; contentDescription = "소식과 댓글 자세히 보기"
        setOnClickListener { open() }
        orientation = VERTICAL
        tag = "feed-post:${post.getInt("id")}"; background = ui.shape(ui.paper, 24, stroke = true)
        setPadding(ui.dp(16), ui.dp(18), ui.dp(16), ui.dp(18))
        author(this, post); photos(this, post)
        val caption = ui.text(post.optString("caption"), if (elder) 23f else 18f).apply {
            setLineSpacing(ui.dp(3).toFloat(), 1.2f)
        }
        val actions = ui.row().apply { setPadding(0, ui.dp(12), 0, ui.dp(10)) }
        fun action(label: String, symbol: String, callback: () -> Unit): View {
            val box = ui.column(8).apply {
                gravity = Gravity.CENTER; minimumHeight = ui.dp(if (elder) 94 else 64)
                isClickable = true; isFocusable = true; contentDescription = label
                if (elder) background = ui.shape(if (symbol == "listen") ui.sky else ui.coral, 20)
                setOnClickListener { callback() }
            }
            box.addView(IconView(context, symbol, if (symbol == "listen") ui.skyDeep else ui.coralDeep),
                LayoutParams(ui.dp(if (elder) 34 else 26), ui.dp(if (elder) 34 else 26)))
            if (symbol == "comment") {
                commentLabel.text = label; commentLabel.gravity = Gravity.CENTER
                box.addView(commentLabel)
            } else box.addView(ui.text(label, if (elder) 21f else 16f).apply { gravity = Gravity.CENTER })
            actions.addView(box, LayoutParams(0, -2, 1f).apply { marginEnd = ui.dp(4) })
            return box
        }
        action(if (elder) "댓글 달기" else "댓글 ${post.optInt("comment_count")}", "comment", comment)
        if (!elder) action("말로 댓글", "mic", voice)
        action("소식 듣기", "listen") { audio.togglePlayback() }
        if (!elder) addView(actions)
        if (caption.text.isNotBlank()) {
            addView(caption, LayoutParams(-1, -2).apply { topMargin = ui.dp(12) })
            if (!elder && caption.text.length > 120) {
                caption.maxLines = 3; caption.ellipsize = android.text.TextUtils.TruncateAt.END
                ui.text("더보기", 17f, true, ui.coralDeep).apply {
                    minimumHeight = ui.dp(44); gravity = Gravity.CENTER_VERTICAL
                    isClickable = true; isFocusable = true; contentDescription = "게시글 전체 보기"
                    setOnClickListener { caption.maxLines = Int.MAX_VALUE; caption.ellipsize = null; visibility = GONE }
                    addView(this)
                }
            }
        }
        if (elder) addView(actions)
        addView(audio, LayoutParams(-1, -2))
        if (elder) {
            addView(comments, LayoutParams(-1, -2).apply { topMargin = ui.dp(14) })
            ui.label(comments, "가족의 댓글을 불러올게요.", 18f, color = ui.muted)
        }
    }

    fun showComments(items: List<JSONObject>) {
        commentsLoaded = true; commentsLoading = false; comments.removeAllViews()
        ui.label(comments, "가족의 댓글 ${items.size}", 20f, true)
        if (items.isEmpty()) ui.label(comments, "첫 댓글을 남겨 주세요.", 19f, color = ui.muted)
        items.forEach { item ->
            ui.gap(comments, 12)
            ui.label(comments, item.optString("author_name") + " · " + item.optString("relationship"), 17f, true, ui.coralDeep)
            ui.label(comments, item.optString("text"), 21f).setLineSpacing(ui.dp(3).toFloat(), 1.2f)
        }
        commentLabel.text = if (elder) "댓글 달기" else "댓글 ${items.size}"
    }

    fun commentsFailed(retry: () -> Unit) {
        commentsLoading = false; commentsLoaded = true; comments.removeAllViews()
        ui.label(comments, "댓글을 불러오지 못했어요.", 18f, color = ui.muted)
        ui.ghost(comments, "댓글 다시 불러오기") { commentsLoaded = false; retry() }
    }
}
