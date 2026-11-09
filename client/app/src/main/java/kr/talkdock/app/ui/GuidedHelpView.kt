package kr.talkdock.app.ui

import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RectF
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.widget.*
import kr.talkdock.app.R

/** Entirely local practice. No API, microphone, account, or family data is touched. */
class GuidedHelpView(context: Context, private val ui: Ui, private val finish: () -> Unit) : FrameLayout(context) {
    private var step = 0
    private var recording = false
    private var completed = false
    private var down = false
    private var previousScroll = 0
    private var target: View? = null
    private var next: Button? = null
    private val shade = Spotlight(context)
    private val titles = listOf("반가워요! 저는 토닥이에요.", "소식을 위아래로 움직여 봐요.", "댓글로 마음을 전해요.", "소식을 소리로 들어봐요.", "하루와 추억도 여기 있어요.", "잘하셨어요!")
    private val copy = listOf("가족의 글과 별도로 준비한 연습용 소식으로 함께해요.", "아래로 내렸다가 위로도 한 번 올려보세요.", "댓글 달기를 누르고 글이나 말로 마음을 남겨보세요.", "도우미 메뉴의 음성으로 듣기를 눌러보세요.", "도우미 메뉴에서 오늘 가족의 하루를 열어보세요.", "도우미의 도움말에서 언제든 다시 연습할 수 있어요.")

    init { contentDescription = "토닥 사용 안내"; render() }

    private fun done() {
        if (completed) return
        completed = true; next?.isEnabled = true; next?.text = "다음"
        if (step in 1..2) {
            val expected = step
            postDelayed({ if (isAttachedToWindow && step == expected) { step++; render() } }, 700)
        }
    }

    private fun render() {
        removeAllViews(); completed = step == 0 || step == 5; recording = false
        val body = ui.column(18).apply { setBackgroundColor(ui.milk) }
        addView(body, LayoutParams(-1, -1))
        ui.label(body, "연습용 소식 · 실제 가족방에 저장되지 않아요", 17f, true, ui.coralDeep)
        val scroll = ScrollView(context).apply { isFillViewport = true }
        val article = ui.column(16); scroll.addView(article)
        body.addView(scroll, LinearLayout.LayoutParams(-1, 0, 1f))
        ui.label(article, "토닥 도우미 · 연습용", 22f, true)
        article.addView(ImageView(context).apply {
            setImageResource(R.drawable.assistant_character); scaleType = ImageView.ScaleType.FIT_CENTER
            contentDescription = "연습용 소식 사진"
        }, LinearLayout.LayoutParams(-1, ui.dp(250)))
        ui.label(article, "오늘은 따뜻한 차를 마시며 쉬고 있어요.\n가족 여러분도 좋은 하루 보내세요!", 24f)
        if (step == 1) {
            ui.gap(article, 160)
            ui.label(article, "가족이 올린 사진과 글, 그 아래 댓글을 천천히 읽어보세요.", 23f)
            ui.gap(article, 420)
            down = false; previousScroll = 0
            scroll.setOnScrollChangeListener { _, _, y, _, _ ->
                if (y > ui.dp(70)) down = true
                if (down && previousScroll - y > ui.dp(10)) done()
                previousScroll = y
            }
            target = scroll
        } else if (step == 2) {
            val comments = ui.column(); article.addView(comments)
            val open = ui.button(comments, "댓글 달기", height = 70) {
                comments.removeAllViews()
                val input = ui.input(comments, "연습 댓글", "다정한 한마디를 적어 주세요")
                val send = ui.button(comments, "댓글 남기기", height = 64) {
                    if (input.text.isBlank()) input.error = "댓글을 적어 주세요."
                    else { ui.label(comments, "연습 댓글을 남겼어요!", 21f, true); done() }
                }
                ui.ghost(comments, "말로 댓글 남기기", 64) {
                    if (!recording) {
                        recording = true; input.setText("맛있게 드시고 좋은 하루 보내세요!")
                        ui.label(comments, "연습용 음성 예시예요. 실제 녹음은 하지 않아요.", 17f, color = ui.muted)
                    }
                    send.performClick()
                }
                target = comments; shade.target = comments; shade.invalidate()
            }
            target = open
        } else if (step == 3 || step == 4) {
            val menu = ui.column(); article.addView(menu)
            val action = ui.button(menu, if (step == 3) "음성으로 듣기" else "오늘 가족의 하루", height = 70) {
                if (step == 3) ui.label(menu, "연습용 듣기예요. 실제 소식은 소식 듣기로 들을 수 있어요.", 21f)
                else menu.addView(CalendarView(context).apply { contentDescription = "연습용 하루 달력" })
                done()
            }
            target = action
        } else {
            target = ImageView(context).apply { setImageResource(R.drawable.assistant_character); contentDescription = "토닥 도우미" }
            addView(target, LayoutParams(ui.dp(92), ui.dp(108), Gravity.BOTTOM or Gravity.LEFT).apply { bottomMargin = ui.dp(30) })
        }
        addView(shade, LayoutParams(-1, -1)); shade.target = target
        val coach = ui.column(20).apply { background = ui.shape(ui.paper, 24); elevation = ui.dp(8).toFloat(); tag = "help-step:${step + 1}" }
        val row = ui.row()
        row.addView(ui.text("사용 안내 ${step + 1} / 6", 17f, true), LinearLayout.LayoutParams(0, -2, 1f))
        row.addView(ui.iconButton("close", "나중에 보기") { finish() }); coach.addView(row)
        ui.label(coach, titles[step], 23f, true); ui.gap(coach, 10); ui.label(coach, copy[step], 20f)
        next = ui.button(coach, if (step == 5) "가족 소식으로 돌아가기" else if (completed) "다음" else "직접 해보세요", height = 58) {
            if (step == 5) finish() else if (completed) { step++; render() }
        }.apply { isEnabled = completed }
        if (step > 0) ui.ghost(coach, "이전", 48) { step--; render() }
        addView(coach, LayoutParams(-1, -2, if (step in 2..4) Gravity.TOP else Gravity.BOTTOM).apply {
            leftMargin = ui.dp(16); rightMargin = ui.dp(16); topMargin = ui.dp(12); bottomMargin = ui.dp(150)
        })
        if (step in 2..4) scroll.post { scroll.smoothScrollTo(0, ui.dp(300)); shade.invalidate() }
        post { shade.invalidate() }
    }

    private class Spotlight(context: Context) : View(context) {
        var target: View? = null
        private val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = 0xB3221C19.toInt() }
        private fun hole(): RectF? = target?.takeIf { it.isAttachedToWindow }?.let {
            val a = IntArray(2); val b = IntArray(2); it.getLocationOnScreen(a); getLocationOnScreen(b)
            RectF((a[0] - b[0] - 4).toFloat(), (a[1] - b[1] - 4).toFloat(), (a[0] - b[0] + it.width + 4).toFloat(), (a[1] - b[1] + it.height + 4).toFloat())
        }
        override fun onDraw(canvas: Canvas) {
            val path = Path().apply { fillType = Path.FillType.EVEN_ODD; addRect(0f, 0f, width.toFloat(), height.toFloat(), Path.Direction.CW) }
            hole()?.let { path.addRoundRect(it, 20f, 20f, Path.Direction.CW) }
            canvas.drawPath(path, paint)
        }
        override fun onTouchEvent(event: MotionEvent): Boolean = hole()?.contains(event.x, event.y) != true
    }
}
