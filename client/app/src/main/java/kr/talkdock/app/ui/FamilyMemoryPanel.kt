package kr.talkdock.app.ui

import android.app.Activity
import android.content.Context
import android.content.res.ColorStateList
import android.os.Bundle
import android.text.Editable
import android.text.InputFilter
import android.text.TextWatcher
import android.view.View
import android.view.inputmethod.InputMethodManager
import android.widget.LinearLayout
import android.widget.ProgressBar
import kr.talkdock.app.data.ApiClient
import kr.talkdock.app.data.ApiException
import kr.talkdock.app.data.RequestCancellation
import java.net.SocketTimeoutException
import java.util.concurrent.ExecutorService
import java.util.concurrent.Future

/** Family-wide, single-question search using the same endpoint as the web app. */
class FamilyMemoryPanel(
    private val activity: Activity,
    private val ui: Ui,
    private val large: Boolean,
    private val client: ApiClient,
    private val executor: ExecutorService,
    initial: Bundle? = null,
    onLogin: () -> Unit
) : LinearLayout(activity) {
    private var generation = 0
    private var pending = false
    private var task: Future<*>? = null
    private var cancellation: RequestCancellation? = null
    private var answeredQuestion = initial?.getString("question").orEmpty()
    private var answer = initial?.getString("answer").orEmpty()
    val input = ui.input(this, "어떤 추억이 궁금하세요?",
        "예: 지난번 가족 여행은 어디로 갔었지?", multiline = true,
        initial = initial?.getString("draft").orEmpty()).apply {
        contentDescription = "가족 추억 질문 입력"
        filters = arrayOf(InputFilter.LengthFilter(1000))
        textSize = if (large) 23f else 18f
    }
    val searchButton = ui.button(this, "추억 찾기", height = if (large) 76 else 56) { search() }
    private val loading = ui.column(16).apply {
        visibility = GONE
        background = ui.shape(ui.sky)
        addView(ProgressBar(activity).apply {
            indeterminateTintList = ColorStateList.valueOf(ui.skyDeep)
        }, LayoutParams(ui.dp(32), ui.dp(32)))
        ui.gap(this, 12)
        ui.label(this, "가족의 추억을 찾고 있어요.", if (large) 23f else 18f, true, ui.skyDeep).apply {
            accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
        }
    }
    private val error = ui.text("", if (large) 21f else 17f, color = ui.coralDeep).apply {
        visibility = GONE
        accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
    }
    private val login = ui.button(this, "다시 로그인하기", false, if (large) 76 else 56, onLogin).apply { visibility = GONE }
    private val result = ui.column()
    private val suggestions = ui.column()

    init {
        orientation = VERTICAL
        ui.gap(this, 16)
        addView(loading, LayoutParams(-1, -2))
        addView(error, LayoutParams(-1, -2))
        addView(result, LayoutParams(-1, -2))
        ui.gap(this, 16)
        ui.label(suggestions, "이렇게 물어보세요", if (large) 21f else 17f, true)
        listOf("최근 가족 여행 이야기 찾아줘", "가족이 함께 먹은 음식이 궁금해", "생일에 있었던 일 알려줘").forEach { question ->
            ui.button(suggestions, question, false, if (large) 76 else 56) {
                if (!pending) { input.setText(question); input.setSelection(input.length()) }
            }
        }
        addView(suggestions, LayoutParams(-1, -2))
        ui.gap(this, 20)
        ui.label(this, "AI는 저장된 가족 기록을 참고해요. 아직 정리되지 않은 소식은 검색되지 않을 수 있어요.",
            if (large) 20f else 15f, color = ui.muted)
        input.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) = Unit
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) { updateControls() }
            override fun afterTextChanged(s: Editable?) = Unit
        })
        if (answer.isNotBlank()) showAnswer()
        updateControls()
    }

    fun snapshot() = Bundle().apply {
        putString("draft", input.text.toString())
        putString("question", answeredQuestion)
        putString("answer", answer)
    }

    private fun updateControls() {
        input.isEnabled = !pending
        searchButton.isEnabled = !pending && input.text.isNotBlank()
        searchButton.alpha = if (searchButton.isEnabled) 1f else .45f
        searchButton.text = if (pending) "추억을 찾는 중이에요" else "추억 찾기"
        loading.visibility = if (pending) VISIBLE else GONE
        suggestions.visibility = if (pending || answer.isNotBlank()) GONE else VISIBLE
    }

    private fun search() {
        val question = input.text.toString().trim()
        if (pending || question.isBlank() || !isAttachedToWindow) return
        pending = true
        error.visibility = GONE; login.visibility = GONE
        answeredQuestion = ""; answer = ""; result.removeAllViews()
        input.clearFocus()
        (activity.getSystemService(Context.INPUT_METHOD_SERVICE) as InputMethodManager)
            .hideSoftInputFromWindow(windowToken, 0)
        updateControls()
        val request = ++generation
        val cancel = RequestCancellation().also { cancellation = it }
        task = executor.submit {
            val response = runCatching { client.searchHistory(question, cancel) }
            activity.runOnUiThread {
                if (generation != request || !isAttachedToWindow || activity.isDestroyed) return@runOnUiThread
                task = null; cancellation = null; pending = false
                response.fold({ text ->
                    answeredQuestion = question; answer = text
                    showAnswer()
                }, { failure ->
                    error.text = when {
                        failure is ApiException && failure.status == 401 -> "로그인이 만료되었어요. 다시 로그인해 주세요."
                        failure is ApiException -> failure.message
                        failure is SocketTimeoutException -> "응답이 늦어지고 있어요. 질문은 유지돼요. 잠시 후 다시 시도해 주세요."
                        else -> "추억을 찾지 못했어요. 질문은 유지돼요. 연결 상태를 확인하고 다시 시도해 주세요."
                    }
                    error.visibility = VISIBLE
                    login.visibility = if (failure is ApiException && failure.status == 401) VISIBLE else GONE
                })
                updateControls()
            }
        }
    }

    private fun showAnswer() {
        result.removeAllViews()
        ui.gap(result, 16)
        val card = ui.card(result, ui.sky, stroke = false)
        ui.label(card, "토닥이 찾은 이야기", if (large) 24f else 20f, true, ui.skyDeep)
        ui.gap(card, 12)
        ui.label(card, answeredQuestion, if (large) 22f else 18f, true, ui.skyDeep)
        ui.gap(card, 16)
        ui.label(card, answer, if (large) 23f else 18f, color = ui.skyDeep).apply {
            setTextIsSelectable(true)
            accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
        }
        ui.gap(result, 12)
        ui.label(result, "가족 기록을 참고한 AI 답변이에요. 중요한 내용은 가족에게 확인해 주세요.",
            if (large) 20f else 15f, color = ui.muted)
    }

    override fun onDetachedFromWindow() {
        generation++
        cancellation?.cancel(); cancellation = null
        task?.cancel(true); task = null
        pending = false
        updateControls()
        super.onDetachedFromWindow()
    }
}
