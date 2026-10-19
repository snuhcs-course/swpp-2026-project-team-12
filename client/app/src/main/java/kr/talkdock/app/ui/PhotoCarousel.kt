package kr.talkdock.app.ui

import android.content.Context
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.widget.*
import kotlin.math.ceil
import kotlin.math.floor
import kotlin.math.roundToInt

/** Photos retain their original aspect ratio, with horizontal paging and thumbnails. */
class PhotoCarousel(
    context: Context,
    private val photoCount: Int,
    private val large: Boolean,
    initial: Int = 0,
    private val load: (ImageView, Int) -> Unit,
    private val open: ((Int) -> Unit)? = null,
    private val remove: ((Int) -> Unit)? = null,
    private val changed: (Int) -> Unit = {},
    private val loadThumbnail: ((ImageView, Int) -> Unit)? = null,
    private val release: (ImageView) -> Unit = { it.setImageDrawable(null) },
) : LinearLayout(context) {
    private val ui = Ui(context)
    private val cards = LinearLayout(context).apply { orientation = HORIZONTAL }
    private val indicator = ui.text("", if (large) 19f else 15f, color = ui.muted).apply {
        gravity = Gravity.CENTER; accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
        setPadding(0, ui.dp(8), 0, ui.dp(8))
    }
    private val dots = ui.text("", 13f, color = ui.green).apply {
        gravity = Gravity.CENTER; importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
    }
    private val thumbs = mutableListOf<FrameLayout>()
    private val photos = mutableListOf<ImageView>()
    private val loadedPages = mutableSetOf<Int>()
    private var previous: Button? = null
    private var next: Button? = null
    private var removeButton: Button? = null
    var currentIndex = initial.coerceIn(0, (photoCount - 1).coerceAtLeast(0))
        private set

    private val pager = object : HorizontalScrollView(context) {
        private var flung = false
        init { isHorizontalScrollBarEnabled = false; overScrollMode = View.OVER_SCROLL_NEVER }
        override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
            val side = View.MeasureSpec.getSize(widthMeasureSpec)
            super.onMeasure(widthMeasureSpec, View.MeasureSpec.makeMeasureSpec(side, View.MeasureSpec.EXACTLY))
        }
        override fun onSizeChanged(w: Int, h: Int, oldw: Int, oldh: Int) {
            val selected = currentIndex
            super.onSizeChanged(w, h, oldw, oldh)
            for (i in 0 until cards.childCount) {
                cards.getChildAt(i).layoutParams = LinearLayout.LayoutParams(w, w)
            }
            post { if (width > 0) { scrollTo(selected * width, 0); updateIndex(selected) } }
        }
        override fun onScrollChanged(l: Int, t: Int, oldl: Int, oldt: Int) {
            super.onScrollChanged(l, t, oldl, oldt)
            if (width > 0) updateIndex((l.toFloat() / width).roundToInt())
        }
        override fun fling(velocityX: Int) {
            flung = true
            if (width <= 0) return
            val position = scrollX.toDouble() / width
            val target = if (velocityX > 0) ceil(position).toInt() else floor(position).toInt()
            smoothScrollTo(target.coerceIn(0, photoCount - 1) * width, 0)
        }
        override fun onTouchEvent(event: MotionEvent): Boolean {
            if (event.actionMasked == MotionEvent.ACTION_DOWN) flung = false
            val handled = super.onTouchEvent(event)
            if ((event.actionMasked == MotionEvent.ACTION_UP && !flung) || event.actionMasked == MotionEvent.ACTION_CANCEL) {
                if (width > 0) smoothScrollTo((scrollX.toFloat() / width).roundToInt().coerceIn(0, photoCount - 1) * width, 0)
            }
            return handled
        }
    }

    init {
        require(photoCount > 0)
        orientation = VERTICAL
        for (index in 0 until photoCount) {
            val card = FrameLayout(context).apply { background = ui.shape(ui.paper); clipToOutline = true }
            val photo = ImageView(context).apply {
                scaleType = ImageView.ScaleType.FIT_CENTER
                contentDescription = "사진 ${index + 1} / $photoCount" + if (open != null) ", 누르면 크게 보기" else ""
                if (open != null) {
                    isClickable = true; isFocusable = true; setOnClickListener { open.invoke(index) }
                }
            }
            card.addView(photo, FrameLayout.LayoutParams(-1, -1))
            photos.add(photo)
            if (remove != null && !large) {
                // The visible circle is small; its 48dp touch target remains easy to hit.
                val close = FrameLayout(context).apply {
                    isClickable = true; isFocusable = true; contentDescription = "${index + 1}번째 사진 빼기"
                    setOnClickListener { remove.invoke(index) }
                }
                val glyph = ui.text("×", 23f, true, Color.WHITE).apply {
                    gravity = Gravity.CENTER
                    background = ui.shape(Color.argb(180, 35, 40, 35), 20)
                    importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
                }
                close.addView(glyph, FrameLayout.LayoutParams(ui.dp(28), ui.dp(28), Gravity.CENTER))
                card.addView(close, FrameLayout.LayoutParams(ui.dp(48), ui.dp(48), Gravity.TOP or Gravity.END))
            }
            cards.addView(card, LinearLayout.LayoutParams(ui.dp(280), ui.dp(280)))
        }
        pager.addView(cards, ViewGroup.LayoutParams(-2, -1))
        addView(pager, LinearLayout.LayoutParams(-1, -2))
        loadPages()
        if (photoCount > 1 || large || remove != null) addView(indicator, LinearLayout.LayoutParams(-1, -2))
        if (photoCount > 1) {
            addView(dots, LinearLayout.LayoutParams(-1, -2))
            val strip = HorizontalScrollView(context).apply { isHorizontalScrollBarEnabled = false }
            val row = ui.row().apply { setPadding(0, ui.dp(10), 0, ui.dp(8)) }
            for (index in 0 until photoCount) {
                val holder = FrameLayout(context).apply {
                    setPadding(ui.dp(3), ui.dp(3), ui.dp(3), ui.dp(3))
                    isClickable = true; isFocusable = true; contentDescription = "${index + 1}번째 사진으로 이동"
                    setOnClickListener { show(index) }
                }
                val thumbnail = ImageView(context).apply {
                    scaleType = ImageView.ScaleType.CENTER_CROP
                    importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
                }
                holder.addView(thumbnail, FrameLayout.LayoutParams(-1, -1))
                (loadThumbnail ?: load).invoke(thumbnail, index); thumbs.add(holder)
                row.addView(holder, LinearLayout.LayoutParams(ui.dp(if (large) 72 else 58), ui.dp(if (large) 72 else 58)).apply { marginEnd = ui.dp(6) })
            }
            strip.addView(row); addView(strip, LinearLayout.LayoutParams(-1, -2))
            // Explicit controls also support TalkBack and users who prefer buttons to swiping.
            val controls = ui.row(); addView(controls)
            previous = ui.button(controls, "이전 사진", false, if (large) 68 else 48) { show(currentIndex - 1) }
            next = ui.button(controls, "다음 사진", false, if (large) 68 else 48) { show(currentIndex + 1) }
            previous!!.layoutParams = LinearLayout.LayoutParams(0, -2, 1f).apply { marginEnd = ui.dp(4) }
            next!!.layoutParams = LinearLayout.LayoutParams(0, -2, 1f).apply { marginStart = ui.dp(4) }
        }
        if (remove != null && large) {
            removeButton = ui.button(this, "이 사진 빼기", false, 76) { remove.invoke(currentIndex) }
        }
        render()
    }

    private fun loadPages() {
        photos.forEachIndexed { index, view ->
            if (kotlin.math.abs(index - currentIndex) <= 1) {
                if (loadedPages.add(index)) load(view, index)
            } else if (loadedPages.remove(index)) release(view)
        }
    }

    private fun show(index: Int) {
        val target = index.coerceIn(0, photoCount - 1)
        updateIndex(target)
        if (pager.width > 0) pager.smoothScrollTo(target * pager.width, 0)
    }
    private fun updateIndex(index: Int) {
        val safe = index.coerceIn(0, photoCount - 1)
        if (safe != currentIndex) {
            currentIndex = safe; loadPages(); pager.requestLayout(); render(); changed(safe)
        }
    }
    private fun render() {
        indicator.text = "사진 ${currentIndex + 1} / $photoCount" + if (photoCount > 1) " · 좌우로 넘겨 보세요" else ""
        dots.text = (0 until photoCount).joinToString("  ") { if (it == currentIndex) "●" else "○" }
        previous?.isEnabled = currentIndex > 0
        next?.isEnabled = currentIndex < photoCount - 1
        previous?.alpha = if (currentIndex > 0) 1f else 0.4f
        next?.alpha = if (currentIndex < photoCount - 1) 1f else 0.4f
        removeButton?.contentDescription = "${currentIndex + 1}번째 사진 빼기"
        thumbs.forEachIndexed { index, view ->
            view.isSelected = index == currentIndex
            view.background = GradientDrawable().apply {
                setColor(ui.sage); cornerRadius = ui.dp(6).toFloat()
                setStroke(ui.dp(if (index == currentIndex) 2 else 1), if (index == currentIndex) ui.green else ui.border)
            }
        }
    }
}
