package kr.talkdock.app.ui

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.RippleDrawable
import android.content.res.ColorStateList
import android.text.InputType
import android.view.Gravity
import android.view.View
import android.widget.*
import kr.talkdock.app.R

class Ui(val context: Context) {
    val green = Color.rgb(47, 93, 75)
    val ink = Color.rgb(36, 40, 36)
    val muted = Color.rgb(108, 116, 110)
    val sage = Color.rgb(242, 245, 242)
    val border = Color.rgb(230, 233, 230)
    val font: Typeface = context.resources.getFont(R.font.noto_kr)
    fun dp(n: Int) = (n * context.resources.displayMetrics.density).toInt()
    fun shape(color: Int = sage, radius: Int = 12, stroke: Boolean = false) = GradientDrawable().apply {
        setColor(color); cornerRadius = dp(radius).toFloat()
        if (stroke) setStroke(dp(1), border)
    }
    fun column(padding: Int = 0) = LinearLayout(context).apply {
        orientation = LinearLayout.VERTICAL
        setPadding(dp(padding), dp(padding), dp(padding), dp(padding))
    }
    fun row() = LinearLayout(context).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
    fun text(value: String, size: Float = 18f, bold: Boolean = false, color: Int = ink) = TextView(context).apply {
        text = value; textSize = size; setTextColor(color); typeface = Typeface.create(font, if (bold) Typeface.BOLD else Typeface.NORMAL)
        fontVariationSettings = if (bold) "'wght' 650" else "'wght' 400"
        includeFontPadding = false
        setLineSpacing(dp(3).toFloat(), 1.08f)
    }
    fun label(parent: LinearLayout, value: String, size: Float = 18f, bold: Boolean = false, color: Int = ink): TextView {
        return text(value, size, bold, color).also { parent.addView(it) }
    }
    fun gap(parent: LinearLayout, height: Int = 16) { parent.addView(View(context), LinearLayout.LayoutParams(1, dp(height))) }
    fun line(parent: LinearLayout) { parent.addView(View(context).apply { setBackgroundColor(border) }, LinearLayout.LayoutParams(-1, dp(1))) }
    fun button(parent: LinearLayout, title: String, primary: Boolean = true, height: Int = 64, action: () -> Unit): Button {
        return Button(context).apply {
            text = title; isAllCaps = false; textSize = if (height >= 76) 22f else 19f; typeface = Typeface.create(font, Typeface.BOLD)
            fontVariationSettings = "'wght' 600"
            elevation = 0f; stateListAnimator = null
            setTextColor(if (primary) Color.WHITE else green)
            background = RippleDrawable(ColorStateList.valueOf(Color.argb(35, 0, 0, 0)),
                shape(if (primary) green else sage), null)
            setPadding(dp(12), 0, dp(12), 0); minHeight = dp(height)
            setOnClickListener { action() }
            parent.addView(this, LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(8) })
        }
    }
    fun input(parent: LinearLayout, title: String, hintText: String, password: Boolean = false, multiline: Boolean = false, initial: String = "", identifier: Boolean = false): EditText {
        label(parent, title, 16f, true); gap(parent, 8)
        return EditText(context).apply {
            hint = hintText; textSize = 18f; typeface = font
            fontVariationSettings = "'wght' 400"
            setTextColor(ink); setHintTextColor(muted)
            inputType = when {
                password -> InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
                identifier -> InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS
                multiline -> InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_MULTI_LINE
                else -> InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_CAP_SENTENCES
            }
            isSingleLine = !multiline; gravity = Gravity.TOP or Gravity.START
            setPadding(dp(16), dp(15), dp(16), dp(15))
            background = shape(Color.WHITE, stroke = true)
            setText(initial)
            parent.addView(this, LinearLayout.LayoutParams(-1, if (multiline) dp(128) else -2))
            gap(parent)
        }
    }
    fun iconButton(symbol: String, description: String, action: () -> Unit): View = IconView(context, symbol, green).apply {
        contentDescription = description; isClickable = true; isFocusable = true
        background = RippleDrawable(ColorStateList.valueOf(border), null, shape(Color.WHITE, 24))
        setOnClickListener { action() }; layoutParams = LinearLayout.LayoutParams(dp(52), dp(52))
    }
    fun photo(parent: LinearLayout, height: Int = 236, square: Boolean = false): ImageView {
        val image = if (square) object : ImageView(context) {
            override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
                val side = View.MeasureSpec.getSize(widthMeasureSpec)
                super.onMeasure(widthMeasureSpec, View.MeasureSpec.makeMeasureSpec(side, View.MeasureSpec.EXACTLY))
            }
        } else ImageView(context)
        return image.apply {
            scaleType = ImageView.ScaleType.FIT_CENTER; background = shape(sage)
            clipToOutline = true; contentDescription = "가족이 올린 사진"
            parent.addView(this, LinearLayout.LayoutParams(-1, if (square) -2 else dp(height)))
        }
    }
    fun note(parent: LinearLayout, value: String, large: Boolean = false): TextView {
        val box = column(16).apply { background = shape(sage) }
        parent.addView(box, LinearLayout.LayoutParams(-1, -2))
        return label(box, value, if (large) 23f else 17f)
    }
}

class IconView(context: Context, private val symbol: String, private val color: Int) : View(context) {
    constructor(context: Context) : this(context, "feed", Color.rgb(47, 93, 75))
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = this@IconView.color; style = Paint.Style.STROKE; strokeWidth = 1.8f; strokeCap = Paint.Cap.ROUND; strokeJoin = Paint.Join.ROUND }
    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val size = Math.min(width, height) * .48f
        canvas.save(); canvas.translate((width - size) / 2, (height - size) / 2); canvas.scale(size / 24, size / 24)
        val p = paint
        fun line(x: Float, y: Float, x2: Float, y2: Float) = canvas.drawLine(x, y, x2, y2, p)
        when (symbol) {
            "back" -> { line(15f, 4f, 7f, 12f); line(7f, 12f, 15f, 20f) }
            "up" -> { line(12f, 20f, 12f, 4f); line(5f, 11f, 12f, 4f); line(12f, 4f, 19f, 11f) }
            "down" -> { line(12f, 4f, 12f, 20f); line(5f, 13f, 12f, 20f); line(12f, 20f, 19f, 13f) }
            "plus" -> { line(12f, 3f, 12f, 21f); line(3f, 12f, 21f, 12f) }
            "camera" -> { canvas.drawRoundRect(2f, 6f, 22f, 21f, 3f, 3f, p); canvas.drawCircle(12f, 13f, 4f, p); line(7f, 6f, 9f, 3f); line(9f, 3f, 15f, 3f); line(15f, 3f, 17f, 6f) }
            "refresh" -> { canvas.drawArc(4f, 4f, 20f, 20f, 45f, 285f, false, p); line(17f, 3f, 20f, 8f); line(20f, 8f, 15f, 8f) }
            "mic" -> { canvas.drawRoundRect(8f, 2f, 16f, 15f, 4f, 4f, p); canvas.drawArc(4f, 6f, 20f, 19f, 0f, 180f, false, p); line(12f, 19f, 12f, 23f) }
            "listen" -> { line(3f, 9f, 7f, 9f); line(7f, 9f, 12f, 4f); line(12f, 4f, 12f, 20f); line(12f, 20f, 7f, 15f); line(7f, 15f, 3f, 15f); line(3f, 15f, 3f, 9f); canvas.drawArc(12f, 4f, 22f, 20f, -60f, 120f, false, p) }
            "family" -> { canvas.drawCircle(8f, 7f, 3f, p); canvas.drawCircle(17f, 8f, 2.5f, p); canvas.drawArc(1f, 12f, 15f, 26f, 180f, 180f, false, p); canvas.drawArc(12f, 13f, 23f, 25f, 180f, 180f, false, p) }
            "digest" -> { canvas.drawRoundRect(4f, 2f, 20f, 22f, 2f, 2f, p); line(8f, 8f, 16f, 8f); line(8f, 12f, 16f, 12f); line(8f, 16f, 13f, 16f) }
            else -> { canvas.drawRoundRect(2f, 3f, 22f, 21f, 3f, 3f, p); line(2f, 9f, 22f, 9f) }
        }
        canvas.restore()
    }
}
