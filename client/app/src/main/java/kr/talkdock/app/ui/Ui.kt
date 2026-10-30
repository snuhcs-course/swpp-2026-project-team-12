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
    // White backgrounds with the original warm coral, peach and beige palette.
    // Keep legacy aliases so every screen follows the shared resource palette.
    val coral = context.getColor(R.color.todak_accent_soft)
    val coralDeep = context.getColor(R.color.todak_accent)
    val sky = context.getColor(R.color.todak_surface_muted)
    val skyDeep = context.getColor(R.color.todak_text_supporting)
    val milk = context.getColor(R.color.todak_background)
    val blush = context.getColor(R.color.todak_blush)
    val paper = context.getColor(R.color.todak_surface)
    val green = coralDeep
    val ink = context.getColor(R.color.todak_text)
    val muted = context.getColor(R.color.todak_text_secondary)
    val hintGray = context.getColor(R.color.todak_text_hint)
    val sage = sky
    val border = context.getColor(R.color.todak_border)
    val sheet = context.getColor(R.color.todak_sheet)
    val photoScrim = context.getColor(R.color.todak_photo_scrim)
    val overlayScrim = context.getColor(R.color.todak_overlay_scrim)
    val font: Typeface = context.resources.getFont(R.font.pretendard_medium)
    val titleFont: Typeface = context.resources.getFont(R.font.dunggeunmiso_regular)
    fun dp(n: Int) = (n * context.resources.displayMetrics.density).toInt()
    fun shape(color: Int = sage, radius: Int = 16, stroke: Boolean = false) = GradientDrawable().apply {
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
        includeFontPadding = false
        setLineSpacing(dp(3).toFloat(), 1.15f)
    }
    fun label(parent: LinearLayout, value: String, size: Float = 18f, bold: Boolean = false, color: Int = ink): TextView {
        return text(value, size, bold, color).also { parent.addView(it) }
    }
    fun gap(parent: LinearLayout, height: Int = 16) { parent.addView(View(context), LinearLayout.LayoutParams(1, dp(height))) }
    fun line(parent: LinearLayout) { parent.addView(View(context).apply { setBackgroundColor(border) }, LinearLayout.LayoutParams(-1, dp(1))) }
    fun button(parent: LinearLayout, title: String, primary: Boolean = true, height: Int = 56, action: () -> Unit): Button {
        return Button(context).apply {
            text = title; isAllCaps = false; textSize = if (height >= 76) 22f else 18f; typeface = Typeface.create(font, Typeface.BOLD)
            elevation = 0f; stateListAnimator = null
            setTextColor(if (primary) ink else skyDeep)
            background = RippleDrawable(ColorStateList.valueOf(Color.argb(35, 0, 0, 0)),
                shape(if (primary) coral else sky, 28), null)
            setPadding(dp(12), 0, dp(12), 0); minHeight = dp(height)
            setOnClickListener { action() }
            parent.addView(this, LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(8) })
        }
    }
    fun action(parent: LinearLayout, title: String, symbol: String, large: Boolean = false, action: () -> Unit): View {
        val row = row().apply {
            gravity = Gravity.CENTER; minimumHeight = dp(if (large) 76 else 64)
            background = RippleDrawable(ColorStateList.valueOf(coral), shape(coralDeep, 36), null)
            isClickable = true; isFocusable = true; contentDescription = title
            setPadding(dp(20), dp(12), dp(20), dp(12)); setOnClickListener { action() }
        }
        row.addView(IconView(context, symbol, Color.WHITE), LinearLayout.LayoutParams(dp(28), dp(28)))
        row.addView(text(title, if (large) 23f else 20f, true, Color.WHITE),
            LinearLayout.LayoutParams(-2, -2).apply { marginStart = dp(10) })
        parent.addView(row, LinearLayout.LayoutParams(-1, -2))
        return row
    }
    fun ghost(parent: LinearLayout, title: String, height: Int = 56, action: () -> Unit): Button =
        button(parent, title, false, height, action).apply {
            setTextColor(ink)
            background = RippleDrawable(ColorStateList.valueOf(border), shape(paper, 28, stroke = true), null)
        }
    fun card(parent: LinearLayout, color: Int = paper, padding: Int = 16, stroke: Boolean = true): LinearLayout =
        column(padding).apply {
            background = shape(color, 20, stroke)
            parent.addView(this, LinearLayout.LayoutParams(-1, -2))
        }
    fun art(parent: LinearLayout, name: String = "together", width: Int = 300): View =
        TodakArtView(context, name, width).also {
            parent.addView(it, LinearLayout.LayoutParams(-2, -2).apply { gravity = Gravity.CENTER_HORIZONTAL })
        }
    fun input(parent: LinearLayout, title: String, hintText: String, password: Boolean = false, multiline: Boolean = false, initial: String = "", identifier: Boolean = false): EditText {
        label(parent, title, 16f, true); gap(parent, 8)
        val input = EditText(context).apply {
            hint = hintText; textSize = 18f; typeface = font
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
        if (password) {
            input.transformationMethod = android.text.method.PasswordTransformationMethod.getInstance()
            // Never save passwords in the view hierarchy state across recreation.
            input.isSaveEnabled = false
            parent.addView(CheckBox(context).apply {
                text = "$title 보기"; textSize = 16f; typeface = font
                setTextColor(ink); buttonTintList = ColorStateList.valueOf(coralDeep)
                minHeight = dp(48)
                setOnCheckedChangeListener { _, checked ->
                    val start = input.selectionStart.coerceAtLeast(0)
                    val end = input.selectionEnd.coerceAtLeast(0)
                    input.transformationMethod = if (checked) null else android.text.method.PasswordTransformationMethod.getInstance()
                    input.setSelection(minOf(start, input.text.length), minOf(end, input.text.length))
                }
            })
            gap(parent, 8)
        }
        return input
    }
    fun iconButton(symbol: String, description: String, action: () -> Unit): View = IconView(context, symbol, ink, true).apply {
        contentDescription = description; isClickable = true; isFocusable = true
        background = RippleDrawable(ColorStateList.valueOf(border), shape(if (symbol == "write") blush else milk, 12), null)
        setOnClickListener { action() }; layoutParams = LinearLayout.LayoutParams(dp(48), dp(48))
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
        return label(box, value, if (large) 23f else 17f, color = skyDeep)
    }
}

class IconView(context: Context, private val symbol: String, private val color: Int, private val buttonInset: Boolean = false) : View(context) {
    constructor(context: Context) : this(context, "feed", Color.rgb(166, 78, 68))
    private val artwork = FigmaIcons.picture(context, symbol, color)
    private val tint = Paint().apply { colorFilter = android.graphics.PorterDuffColorFilter(this@IconView.color, android.graphics.PorterDuff.Mode.SRC_IN) }
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = this@IconView.color; style = Paint.Style.STROKE; strokeWidth = 1.8f; strokeCap = Paint.Cap.ROUND; strokeJoin = Paint.Join.ROUND }
    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        artwork?.let { picture ->
            val side = minOf(width, height) * if (buttonInset) .5f else 1f
            val scale = minOf(side / picture.width.coerceAtLeast(1), side / picture.height.coerceAtLeast(1))
            canvas.save()
            canvas.translate((width - picture.width * scale) / 2, (height - picture.height * scale) / 2)
            canvas.scale(scale, scale)
            val layer = canvas.saveLayer(0f, 0f, picture.width.toFloat(), picture.height.toFloat(), tint)
            canvas.drawPicture(picture); canvas.restoreToCount(layer); canvas.restore()
            return
        }
        val size = Math.min(width, height) * .48f
        canvas.save(); canvas.translate((width - size) / 2, (height - size) / 2); canvas.scale(size / 24, size / 24)
        val p = paint
        fun line(x: Float, y: Float, x2: Float, y2: Float) = canvas.drawLine(x, y, x2, y2, p)
        when (symbol) {
            "write" -> {
                line(5f, 17f, 17f, 5f); line(17f, 5f, 21f, 9f)
                line(21f, 9f, 9f, 21f); line(9f, 21f, 3f, 21f)
                line(3f, 21f, 5f, 17f); line(14f, 8f, 18f, 12f)
                line(3f, 4f, 10f, 4f)
            }
            "more" -> { p.style = Paint.Style.FILL; for (y in listOf(5f, 12f, 19f)) canvas.drawCircle(12f, y, 1.7f, p); p.style = Paint.Style.STROKE }
            "play" -> { p.style = Paint.Style.FILL; canvas.drawPath(android.graphics.Path().apply { moveTo(7f, 3f); lineTo(21f, 12f); lineTo(7f, 21f); close() }, p); p.style = Paint.Style.STROKE }
            "back" -> { line(15f, 4f, 7f, 12f); line(7f, 12f, 15f, 20f) }
            "up" -> { line(12f, 20f, 12f, 4f); line(5f, 11f, 12f, 4f); line(12f, 4f, 19f, 11f) }
            "down" -> { line(12f, 4f, 12f, 20f); line(5f, 13f, 12f, 20f); line(12f, 20f, 19f, 13f) }
            "plus" -> { line(12f, 3f, 12f, 21f); line(3f, 12f, 21f, 12f) }
            "camera" -> { canvas.drawRoundRect(2f, 6f, 22f, 21f, 3f, 3f, p); canvas.drawCircle(12f, 13f, 4f, p); line(7f, 6f, 9f, 3f); line(9f, 3f, 15f, 3f); line(15f, 3f, 17f, 6f) }
            "refresh" -> { canvas.drawArc(4f, 4f, 20f, 20f, 45f, 285f, false, p); line(17f, 3f, 20f, 8f); line(20f, 8f, 15f, 8f) }
            "mic" -> { canvas.drawRoundRect(8f, 2f, 16f, 15f, 4f, 4f, p); canvas.drawArc(4f, 6f, 20f, 19f, 0f, 180f, false, p); line(12f, 19f, 12f, 23f) }
            "stop" -> canvas.drawRect(5f, 5f, 19f, 19f, p)
            "listen" -> { line(3f, 9f, 7f, 9f); line(7f, 9f, 12f, 4f); line(12f, 4f, 12f, 20f); line(12f, 20f, 7f, 15f); line(7f, 15f, 3f, 15f); line(3f, 15f, 3f, 9f); canvas.drawArc(12f, 4f, 22f, 20f, -60f, 120f, false, p) }
            "family" -> { canvas.drawCircle(8f, 7f, 3f, p); canvas.drawCircle(17f, 8f, 2.5f, p); canvas.drawArc(1f, 12f, 15f, 26f, 180f, 180f, false, p); canvas.drawArc(12f, 13f, 23f, 25f, 180f, 180f, false, p) }
            "digest" -> { canvas.drawRoundRect(4f, 2f, 20f, 22f, 2f, 2f, p); line(8f, 8f, 16f, 8f); line(8f, 12f, 16f, 12f); line(8f, 16f, 13f, 16f) }
            else -> { canvas.drawRoundRect(2f, 3f, 22f, 21f, 3f, 3f, p); line(2f, 9f, 22f, 9f) }
        }
        canvas.restore()
    }
}
