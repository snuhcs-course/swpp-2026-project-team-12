package kr.talkdock.app.ui

import android.content.Context
import android.view.Gravity
import android.view.View
import android.widget.*
import androidx.core.widget.doAfterTextChanged
import org.json.JSONObject
import kr.talkdock.app.R

/** All edits and sends in this view stay in the practice dialog. */
class GuidedHelpView(
    context: Context,
    private val ui: Ui,
    private val replyPost: JSONObject?,
    replyOnly: Boolean,
    private val onReplyShown: () -> Unit,
    private val finish: () -> Unit
) : FrameLayout(context) {
    private enum class Lesson(val title: String, val instruction: String) {
        INTRO("반가워요! 저는 토닥이에요.", "손가락이 가리키는 곳을 따라 해보세요."),
        READ("소식을 위아래로 움직여 봐요.", "글을 아래로 내렸다가 위로 올려보세요."),
        WRITE("가족에게 소식을 올려봐요.", "소식 쓰기를 누르고 글이나 연습 사진을 올려보세요."),
        LISTEN("소식을 소리로 들어봐요.", "토닥 도우미에서 음성으로 듣기를 찾아보세요."),
        DAY("하루 소식을 찾아봐요.", "토닥 도우미에서 오늘 가족의 하루를 열어보세요."),
        REPLY("가족 소식에 답장해 봐요.", "댓글을 글로 쓰거나 말로 답장하는 방법을 연습해요."),
        END("잘하셨어요!", "토닥 도우미의 도움말에서 다시 연습할 수 있어요.")
    }
    private val lessons = buildList {
        if (!replyOnly) addAll(listOf(Lesson.INTRO, Lesson.READ, Lesson.WRITE, Lesson.LISTEN, Lesson.DAY))
        if (replyPost != null) add(Lesson.REPLY)
        add(Lesson.END)
    }
    private var index = 0
    private var hand: View? = null
    private lateinit var next: Button
    private lateinit var article: LinearLayout
    private lateinit var scroll: ScrollView

    init { contentDescription = "토닥 사용 안내"; render() }

    // Reserve a gutter, so the pointer never covers a label or intercepts a tap.
    private fun withPointer(parent: LinearLayout, create: (LinearLayout) -> Unit): View {
        val row = ui.row()
        parent.addView(row)
        val finger = FrameLayout(context).apply {
            importantForAccessibility = IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS
            visibility = View.INVISIBLE
            addView(ImageView(context).apply {
                setImageResource(R.drawable.assistant_character)
                scaleType = ImageView.ScaleType.FIT_CENTER
            }, LayoutParams(ui.dp(30), ui.dp(36), Gravity.TOP or Gravity.LEFT))
            addView(ui.text("👉", 19f), LayoutParams(-2, -2, Gravity.BOTTOM or Gravity.RIGHT))
        }
        row.addView(finger, LinearLayout.LayoutParams(ui.dp(46), ui.dp(44)))
        val control = ui.column()
        row.addView(control, LinearLayout.LayoutParams(0, -2, 1f))
        create(control)
        return finger
    }

    private fun point(at: View) {
        hand?.visibility = View.INVISIBLE
        hand = at
        at.visibility = View.VISIBLE
    }

    private fun picture(parent: LinearLayout) {
        parent.addView(ImageView(context).apply {
            setImageResource(R.drawable.assistant_character)
            scaleType = ImageView.ScaleType.FIT_CENTER
            contentDescription = "연습 사진"
        }, LinearLayout.LayoutParams(-1, ui.dp(116)))
    }

    private fun render() {
        removeAllViews()
        hand = null
        val lesson = lessons[index]
        val page = ui.column(14).apply { setBackgroundColor(ui.paper) }
        addView(page)
        val header = ui.row()
        page.addView(header)
        header.addView(ui.text("사용 안내 ${index + 1} / ${lessons.size}", 17f, true),
            LinearLayout.LayoutParams(0, -2, 1f))
        header.addView(ui.iconButton("close", "나중에 보기") { finish() })
        scroll = ScrollView(context)
        article = ui.column(6)
        scroll.addView(article)
        page.addView(scroll, LinearLayout.LayoutParams(-1, 0, 1f))
        article.tag = "help-step:${index + 1}"
        ui.label(article, lesson.title, 24f, true)
        ui.label(article, lesson.instruction, 20f)
        ui.label(article, "연습용 · 실제 가족방에 저장되지 않아요", 16f, color = ui.muted)
        ui.gap(article)
        val nextHand = withPointer(page) { box ->
            next = ui.button(box, if (lesson == Lesson.END) "가족 소식으로 돌아가기" else "다음") {
                if (index == lessons.lastIndex) finish() else { index++; render() }
            }
        }
        next.isEnabled = false
        if (index > 0) ui.ghost(page, "이전", 48) { index--; render() }
        fun done() { next.isEnabled = true; point(nextHand) }
        when (lesson) {
            Lesson.INTRO, Lesson.END -> { picture(article); done() }
            Lesson.READ -> {
                point(withPointer(article) { ui.label(it, "오늘은 따뜻한 차를 마시며 쉬고 있어요.", 23f) })
                picture(article)
                ui.gap(article, 240)
                ui.label(article, "가족 여러분도 좋은 하루 보내세요!", 23f)
                // Always leave scrollable space, including on tablets.
                val readArticle = article
                scroll.post { if (readArticle.isAttachedToWindow) ui.gap(readArticle, (readArticle.height.coerceAtLeast(scroll.height) / resources.displayMetrics.density).toInt()) }
                var down = false
                val readScroll = scroll
                scroll.setOnScrollChangeListener { _, _, y, _, oldY ->
                    if (y > ui.dp(48)) down = true
                    if (down && y < oldY && scroll === readScroll && !next.isEnabled) {
                        done()
                        val current = index
                        postDelayed({ if (isAttachedToWindow && index == current) { index++; render() } }, 700)
                    }
                }
            }
            Lesson.WRITE, Lesson.REPLY -> {
                val reply = lesson == Lesson.REPLY
                if (reply && replyPost != null) {
                    onReplyShown()
                    val author = replyPost.optString("author_name").ifBlank { "가족" }
                    ui.label(article, "${author}님의 소식", 19f, true)
                    ui.label(article, replyPost.optString("caption").ifBlank { "사진으로 전한 소식이에요." }, 20f).apply {
                        maxLines = 3
                        ellipsize = android.text.TextUtils.TruncateAt.END
                    }
                }
                val panel = ui.column()
                article.addView(panel)
                point(withPointer(panel) {
                    ui.button(it, if (reply) "댓글 달기" else "소식 쓰기", height = 70) {
                        panel.removeAllViews()
                        practiceForm(panel, reply, ::done)
                    }
                })
            }
            Lesson.LISTEN, Lesson.DAY -> {
                val panel = ui.column()
                article.addView(panel)
                point(withPointer(panel) { box ->
                    ui.button(box, "토닥 도우미") {
                        panel.removeAllViews()
                        val listen = lesson == Lesson.LISTEN
                        point(withPointer(panel) {
                            ui.button(it, if (listen) "음성으로 듣기" else "오늘 가족의 하루") {
                                panel.removeAllViews()
                                if (listen) ui.label(panel, "연습용 듣기를 열었어요.", 20f)
                                else panel.addView(CalendarView(context))
                                done()
                            }
                        })
                    }
                })
            }
        }
    }

    private fun practiceForm(panel: LinearLayout, reply: Boolean, done: () -> Unit) {
        lateinit var input: EditText
        val inputHand = withPointer(panel) {
            input = ui.input(it, if (reply) "연습 댓글" else "연습 게시글", "여기에 적어 주세요")
        }
        var photo = false
        val preview = ui.column()
        lateinit var sendHand: View
        lateinit var alternate: Button
        alternate = ui.ghost(panel, if (reply) "말로 댓글 남기기" else "연습 사진 추가") {
            if (reply) {
                input.setText("좋은 하루 보내세요!")
                ui.label(preview, "음성 예시예요. 내용을 확인하고 보내세요.", 17f)
            } else {
                photo = true
                picture(preview)
            }
            alternate.isEnabled = false
            point(sendHand)
        }
        panel.addView(preview)
        sendHand = withPointer(panel) {
            ui.button(it, if (reply) "댓글 남기기" else "가족에게 전하기") {
                if (input.text.isBlank() && !photo) {
                    input.error = if (reply) "댓글을 적어 주세요." else "글이나 연습 사진을 넣어 주세요."
                } else {
                    panel.removeAllViews()
                    ui.label(panel, if (reply) "연습 댓글을 남겼어요." else "연습 소식을 올렸어요.", 21f, true)
                    if (photo) picture(panel)
                    if (input.text.isNotBlank()) ui.label(panel, input.text.toString(), 20f)
                    done()
                }
            }
        }
        fun guideForm() { point(if (input.text.isNotBlank() || photo) sendHand else inputHand) }
        input.doAfterTextChanged { guideForm() }
        guideForm()
    }
}
