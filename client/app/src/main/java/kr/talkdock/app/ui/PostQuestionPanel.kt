package kr.talkdock.app.ui

import android.app.Activity
import android.content.Context
import android.graphics.Rect
import android.text.InputFilter
import android.view.View
import android.view.inputmethod.InputMethodManager
import android.widget.LinearLayout
import kr.talkdock.app.data.ApiClient
import kr.talkdock.app.data.ApiException
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.ExecutorService
import java.util.concurrent.Future

/** Post-scoped QA, kept separate from the public comment composer and its requests. */
class PostQuestionPanel(
    private val activity: Activity,
    private val ui: Ui,
    private val postId: Int,
    private val large: Boolean,
    private val client: ApiClient,
    private val executor: ExecutorService
) : LinearLayout(activity) {
    private val turns = mutableListOf<Pair<String, String>>()
    private var generation = 0
    private var pending = false
    private var task: Future<*>? = null
    private val body = ui.column().apply { visibility = GONE }
    private val dialogue = ui.column()
    private val status = ui.text("답변을 준비하고 있어요.", if (large) 20f else 16f, color = ui.skyDeep).apply {
        visibility = GONE
        accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
    }
    val composer = CommentComposer(activity, ui, large,
        title = "AI에게 질문하기", hintText = "이 소식에서 궁금한 점을 물어보세요",
        inputLabel = "추가 질문 입력", sendLabel = "질문 보내기", pendingLabel = "답변 준비 중",
        onSend = { ask(it) }
    )
    private val toggle = ui.button(this, "궁금한 점을 물어보세요", false, if (large) 76 else 56) {
        if (body.visibility == VISIBLE) {
            composer.input.clearFocus()
            keyboard().hideSoftInputFromWindow(windowToken, 0)
            body.visibility = GONE
            updateToggle()
        } else open(focus = true)
    }

    init {
        orientation = VERTICAL
        composer.input.filters = arrayOf(InputFilter.LengthFilter(1000))
        ui.gap(body, 12)
        ui.label(body, "질문과 답변은 가족 댓글로 등록되지 않아요.", if (large) 18f else 14f, color = ui.muted)
        ui.gap(body, 12)
        body.addView(dialogue, LayoutParams(-1, -2))
        body.addView(status, LayoutParams(-1, -2))
        body.addView(composer, LayoutParams(-1, -2))
        addView(body, LayoutParams(-1, -2))
    }

    private fun keyboard() = activity.getSystemService(Context.INPUT_METHOD_SERVICE) as InputMethodManager

    fun open(focus: Boolean = false) {
        body.visibility = VISIBLE
        updateToggle()
        if (focus) composer.input.post {
            if (isAttachedToWindow && body.visibility == VISIBLE && !activity.isDestroyed) {
                composer.input.requestFocus()
                keyboard().showSoftInput(composer.input, InputMethodManager.SHOW_IMPLICIT)
            }
        }
    }

    private fun updateToggle() {
        toggle.text = if (body.visibility == VISIBLE) "닫기" else "궁금한 점을 물어보세요"
    }

    private fun ask(question: String) {
        if (pending || question.isBlank()) return
        pending = true
        composer.setSending(true)
        status.visibility = VISIBLE
        val request = ++generation
        // The API accepts at most ten prior messages, each at most 1,000 characters.
        val prior = JSONArray()
        turns.takeLast(5).forEach { (asked, answered) ->
            prior.put(JSONObject().put("role", "user").put("text", asked.take(1000)))
            prior.put(JSONObject().put("role", "assistant").put("text", answered.take(1000)))
        }
        val input = JSONObject().put("question", question).put("prior_dialogue", prior)
        task = executor.submit {
            val result = runCatching {
                client.request("posts/$postId/questions/", "POST", input).getString("text").also {
                    check(it.isNotBlank()) { "Empty answer" }
                }
            }
            activity.runOnUiThread {
                if (request != generation || !isAttachedToWindow || activity.isDestroyed) return@runOnUiThread
                task = null; pending = false
                status.visibility = GONE
                result.fold({ answer ->
                    turns.add(question to answer)
                    if (turns.size > 1) ui.gap(dialogue, 16)
                    ui.label(dialogue, "나의 질문", if (large) 20f else 16f, true)
                    ui.note(dialogue, question, large)
                    val answerHeading = ui.label(dialogue, "AI 답변", if (large) 20f else 16f, true, ui.skyDeep)
                    ui.note(dialogue, answer, large).accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
                    ui.gap(dialogue, 16)
                    composer.input.setText("")
                    composer.setSending(false)
                    composer.input.clearFocus()
                    keyboard().hideSoftInputFromWindow(windowToken, 0)
                    answerHeading.post {
                        if (isAttachedToWindow && body.visibility == VISIBLE) {
                            answerHeading.requestRectangleOnScreen(Rect(0, 0, answerHeading.width, answerHeading.height), true)
                        }
                    }
                }, { error ->
                    val message = if (error is ApiException && error.status == 401)
                        "로그인이 만료되었어요. 질문은 유지돼요. 다시 로그인해 주세요."
                    else (error as? ApiException)?.message ?: "답변을 불러오지 못했어요. 질문은 유지돼요. 다시 시도해 주세요."
                    composer.showError(message)
                })
            }
        }
    }

    override fun onDetachedFromWindow() {
        generation++; task?.cancel(true); task = null
        pending = false
        composer.setSending(false)
        super.onDetachedFromWindow()
    }
}
