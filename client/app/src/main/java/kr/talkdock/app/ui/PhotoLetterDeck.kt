package kr.talkdock.app.ui

import android.content.Context
import android.graphics.Color
import android.os.Bundle
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewConfiguration
import android.view.accessibility.AccessibilityNodeInfo
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import org.json.JSONObject
import java.time.OffsetDateTime
import java.time.format.DateTimeFormatter
import kotlin.math.abs

/** Only the open letter is mounted. Horizontal gestures change posts, never photos. */
class PhotoLetterDeck(
    context: Context, private val ui: Ui, private val posts: List<JSONObject>, private val large: Boolean,
    selectedId: Int?, private val load: (ImageView, JSONObject, String) -> Unit,
    private val release: (ImageView) -> Unit, private val open: (JSONObject) -> Unit,
    private val reply: (JSONObject) -> Unit, private val changed: (JSONObject) -> Unit,
) : LinearLayout(context) {
    var currentIndex = posts.indexOfFirst { it.optInt("id") == selectedId }.coerceAtLeast(0)
        private set
    val letterCount get() = posts.size
    val currentPost get() = posts[currentIndex]
    val currentCard = FrameLayout(context)
    val botPocket = FrameLayout(context)
    private var assistantOnLeft = false
    private var metadata: LinearLayout? = null
    private val stack = object : FrameLayout(context) {
        private val paperPaint = android.graphics.Paint(android.graphics.Paint.ANTI_ALIAS_FLAG)
        private val edgePaint = android.graphics.Paint(android.graphics.Paint.ANTI_ALIAS_FLAG).apply {
            color = ui.border; style = android.graphics.Paint.Style.STROKE; strokeWidth = ui.dp(1).toFloat()
        }
        init { clipChildren = false; clipToPadding = false }
        override fun dispatchDraw(canvas: android.graphics.Canvas) {
            val layers = (images(currentPost).size - 1).coerceIn(0, 2)
            for (index in layers downTo 1) {
                // The small, staggered top edges belong to this post's photos, not other posts.
                paperPaint.color = if (index == 2) ui.sheet else ui.paper
                val sheet = android.graphics.RectF(ui.dp(index * 7).toFloat(),
                    ui.dp((layers - index) * 8 + 2).toFloat(), (width - ui.dp(index * 4)).toFloat(),
                    (height - ui.dp(index * 4)).toFloat())
                canvas.save(); canvas.rotate(if (index == 2) 1.2f else -.8f, width / 2f, height / 2f)
                canvas.drawRoundRect(sheet, ui.dp(28).toFloat(), ui.dp(28).toFloat(), paperPaint)
                canvas.drawRoundRect(sheet, ui.dp(28).toFloat(), ui.dp(28).toFloat(), edgePaint)
                canvas.restore()
            }
            super.dispatchDraw(canvas)
        }
    }
    private val previous = ui.iconButton("back", "이전 소식") { show(currentIndex - 1) }
    private val next = ui.iconButton("next", "다음 소식") { show(currentIndex + 1) }
    private val count = ui.text("", if (large) 19f else 16f, color = ui.muted).apply {
        gravity = Gravity.CENTER; accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
    }
    private val photo = ImageView(context).apply { scaleType = ImageView.ScaleType.CENTER_CROP }
    private var startX = 0f
    private var startY = 0f
    private var horizontal = false
    private val slop = ViewConfiguration.get(context).scaledTouchSlop
    private val photoHeight: Int get() = ui.dp((resources.displayMetrics.heightPixels /
        resources.displayMetrics.density - if (large) 570 else 490).toInt().coerceIn(210, 430))

    init {
        require(posts.isNotEmpty())
        orientation = VERTICAL; clipChildren = false; clipToPadding = false
        tag = "photo-letter-deck"
        currentCard.background = ui.shape(ui.paper, 28, stroke = true)
        currentCard.clipToOutline = true; currentCard.elevation = ui.dp(2).toFloat()
        stack.addView(currentCard, FrameLayout.LayoutParams(-1, -2).apply { bottomMargin = ui.dp(4) })
        addView(stack, LayoutParams(-1, -2))
        val pagination = ui.row()
        pagination.addView(previous, LayoutParams(ui.dp(48), ui.dp(48)))
        pagination.addView(count, LayoutParams(0, -2, 1f))
        pagination.addView(next, LayoutParams(ui.dp(48), ui.dp(48)))
        addView(pagination, LayoutParams(-1, -2))
        ui.action(this, "말로 답장하기", "mic", large) { reply(currentPost) }
        render()
    }

    private fun images(post: JSONObject): List<String> {
        val array = post.optJSONArray("images")
        if (array != null) return (0 until array.length()).mapNotNull {
            array.optJSONObject(it)?.optString("url")?.takeIf { url -> url.isNotBlank() }
        }
        return listOfNotNull(post.optString("image_url").takeIf { it.isNotBlank() && it != "null" })
    }

    fun setAssistantOnLeft(onLeft: Boolean) {
        if (assistantOnLeft == onLeft) return
        assistantOnLeft = onLeft
        metadata?.layoutParams = metadataLayoutParams()
    }

    private fun metadataLayoutParams() = FrameLayout.LayoutParams(-1, -1).apply {
        if (assistantOnLeft) marginStart = ui.dp(54) else marginEnd = ui.dp(54)
    }

    fun show(index: Int) {
        val safe = index.coerceIn(0, posts.lastIndex)
        if (safe == currentIndex) return
        release(photo)
        val forward = safe > currentIndex
        currentIndex = safe; render(); changed(currentPost)
        if (android.animation.ValueAnimator.areAnimatorsEnabled()) {
            currentCard.translationX = ui.dp(if (forward) 14 else -14).toFloat(); currentCard.alpha = .8f
            currentCard.animate().translationX(0f).alpha(1f).setDuration(140).start()
        }
        announceForAccessibility("${currentIndex + 1}번째 소식, ${currentPost.optString("author_name")}")
    }

    private fun render() {
        currentCard.removeAllViews()
        val post = currentPost
        val body = ui.column()
        currentCard.addView(body, FrameLayout.LayoutParams(-1, -2))
        val photos = images(post)
        val topInset = ui.dp(4 + (photos.size - 1).coerceIn(0, 2) * 10)
        currentCard.layoutParams = (currentCard.layoutParams as FrameLayout.LayoutParams).apply { topMargin = topInset }
        stack.invalidate()
        val picture = FrameLayout(context).apply {
            // Only the outer letter clips its top corners; the photo meets the paper on a straight edge.
            setBackgroundColor(ui.blush)
            isClickable = true; isFocusable = true
            contentDescription = "${post.optString("author_name")}님의 소식, 사진 ${photos.size}장. 누르면 상세 보기"
            setOnClickListener { open(post) }
        }
        body.addView(picture, LayoutParams(-1, photoHeight))
        (photo.parent as? android.view.ViewGroup)?.removeView(photo)
        if (photos.isNotEmpty()) {
            picture.addView(photo, FrameLayout.LayoutParams(-1, -1))
            load(photo, post, photos.first())
        } else {
            picture.addView(ui.text("글로 전한 마음", if (large) 30f else 27f, true, ui.skyDeep).apply {
                gravity = Gravity.CENTER
            }, FrameLayout.LayoutParams(-1, -1))
        }
        if (photos.size > 1) picture.addView(ui.text("사진 ${photos.size}장", 14f, true, Color.WHITE).apply {
            setPadding(ui.dp(10), ui.dp(6), ui.dp(10), ui.dp(6))
            background = ui.shape(ui.photoScrim, 16)
        }, FrameLayout.LayoutParams(-2, -2, Gravity.BOTTOM or Gravity.END).apply {
            bottomMargin = ui.dp(12); marginEnd = ui.dp(12)
        })
        val words = ui.column().apply { setPadding(ui.dp(22), ui.dp(18), ui.dp(18), 0) }
        body.addView(words, LayoutParams(-1, -2))
        ui.label(words, post.optString("caption").ifBlank { "사진으로 남긴 오늘의 하루" }, if (large) 28f else 25f, true).apply {
            maxLines = 3; ellipsize = android.text.TextUtils.TruncateAt.END
            isClickable = true; isFocusable = true; contentDescription = "소식과 댓글 자세히 보기"
            setOnClickListener { open(post) }
        }
        // Keep author and date together, reserving space on the bot's current edge.
        (botPocket.parent as? android.view.ViewGroup)?.removeView(botPocket)
        botPocket.removeAllViews()
        val time = runCatching { OffsetDateTime.parse(post.optString("created_at"))
            .format(DateTimeFormatter.ofPattern("M월 d일 a h:mm", java.util.Locale.KOREAN)) }.getOrDefault("")
        val name = post.optString("author_name").ifBlank { "가족" }
        val authorRow = ui.row()
        val avatarSize = if (large) 38 else 32
        authorRow.addView(ui.text(name.takeLast(2), if (large) 15f else 13f, true, ui.skyDeep).apply {
            gravity = Gravity.CENTER; background = ui.shape(ui.coral, avatarSize / 2)
            contentDescription = "$name 프로필"
        }, LayoutParams(ui.dp(avatarSize), ui.dp(avatarSize)))
        authorRow.addView(ui.text(name, if (large) 17f else 15f, true).apply {
            maxLines = 1; ellipsize = android.text.TextUtils.TruncateAt.END
        }, LayoutParams(0, -2, 1f).apply { marginStart = ui.dp(8) })
        authorRow.addView(ui.text(time, if (large) 14f else 13f, color = ui.muted).apply {
            gravity = Gravity.END or Gravity.CENTER_VERTICAL; maxLines = 2
        }, LayoutParams(ui.dp(if (large) 120 else 112), -2).apply { marginStart = ui.dp(10) })
        metadata = authorRow
        botPocket.addView(authorRow, metadataLayoutParams())
        words.addView(botPocket, LayoutParams(-1, ui.dp(76)))
        previous.isEnabled = currentIndex > 0; next.isEnabled = currentIndex < posts.lastIndex
        previous.alpha = if (previous.isEnabled) .7f else .18f
        next.alpha = if (next.isEnabled) .7f else .18f
        count.text = "${currentIndex + 1} / ${posts.size}"
    }

    override fun onInterceptTouchEvent(event: MotionEvent): Boolean {
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> { startX = event.x; startY = event.y; horizontal = false }
            MotionEvent.ACTION_MOVE -> if (abs(event.x - startX) > slop && abs(event.x - startX) > abs(event.y - startY) * 1.3f) {
                horizontal = true; parent.requestDisallowInterceptTouchEvent(true); return true
            }
        }
        return super.onInterceptTouchEvent(event)
    }
    override fun onTouchEvent(event: MotionEvent): Boolean {
        if (!horizontal) return super.onTouchEvent(event)
        if (event.actionMasked == MotionEvent.ACTION_UP || event.actionMasked == MotionEvent.ACTION_CANCEL) {
            if (event.actionMasked == MotionEvent.ACTION_UP && abs(event.x - startX) > maxOf(ui.dp(48).toFloat(), width * .13f))
                show(currentIndex + if (event.x < startX) 1 else -1)
            horizontal = false; parent.requestDisallowInterceptTouchEvent(false)
        }
        return true
    }
    override fun onInitializeAccessibilityNodeInfo(info: AccessibilityNodeInfo) {
        super.onInitializeAccessibilityNodeInfo(info)
        info.isScrollable = posts.size > 1
        if (currentIndex < posts.lastIndex) info.addAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_SCROLL_FORWARD)
        if (currentIndex > 0) info.addAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_SCROLL_BACKWARD)
    }
    override fun performAccessibilityAction(action: Int, arguments: Bundle?): Boolean {
        when (action) {
            AccessibilityNodeInfo.ACTION_SCROLL_FORWARD -> if (currentIndex < posts.lastIndex) { show(currentIndex + 1); return true }
            AccessibilityNodeInfo.ACTION_SCROLL_BACKWARD -> if (currentIndex > 0) { show(currentIndex - 1); return true }
        }
        return super.performAccessibilityAction(action, arguments)
    }
    override fun onDetachedFromWindow() { release(photo); super.onDetachedFromWindow() }
}
