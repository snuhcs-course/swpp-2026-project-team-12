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
import android.widget.ScrollView
import androidx.core.view.doOnLayout
import kr.talkdock.app.data.Telemetry
import kr.talkdock.app.data.ApiClient
import kr.talkdock.app.data.ApiException
import kr.talkdock.app.data.ApiFailureMessages
import kr.talkdock.app.data.RequestCancellation
import kr.talkdock.app.data.MemorySearchResult
import org.json.JSONObject
import java.util.concurrent.ExecutorService
import java.util.concurrent.Future

/** Microphone access for asking by voice; the activity owns the permission request. */
class MemoryVoiceAccess(
    val hasMicrophone: () -> Boolean,
    val requestMicrophone: (FamilyMemoryPanel) -> Unit,
    val beforeRecording: () -> Unit,
)

/** Family-wide, single-question search using the same endpoint as the web app. */
class FamilyMemoryPanel(
    private val activity: Activity,
    private val ui: Ui,
    private val large: Boolean,
    private val client: ApiClient,
    private val executor: ExecutorService,
    initial: Bundle? = null,
    private val renderPost: (LinearLayout, JSONObject) -> Unit,
    /** Elderly mode: one-tap questions shown above the input, so nothing has to be typed. */
    private val examples: List<String> = emptyList(),
    /** Elderly mode: adds a listen control for the answer. */
    private val listen: ((LinearLayout, String) -> Unit)? = null,
    /** Elderly mode: ask by speaking; the transcript fills the question and searches. */
    private val voice: MemoryVoiceAccess? = null,
    /** Searches made earlier on this device, newest first; reopening one does not ask the AI again. */
    history: List<Pair<String, JSONObject>> = emptyList(),
    private val remember: ((String, MemorySearchResult) -> Unit)? = null,
    onLogin: () -> Unit
) : LinearLayout(activity) {
    private val pastSearches = history.toMutableList()
    private val historyBox = ui.column().apply { tag = "memory-history" }
    private var historyOpen = false
    private val voiceArea = ui.column().apply { tag = "memory-voice" }
    private var recorder: kr.talkdock.app.device.Recorder? = null
    private var voiceTask: Future<*>? = null
    private var voiceGeneration = 0
    private var generation = 0
    private var pending = false
    private var telemetryOperation: Telemetry.Operation? = null
    private var telemetryQuestion: String? = null
    private var task: Future<*>? = null
    private var cancellation: RequestCancellation? = null
    private var answeredQuestion = initial?.getString("question").orEmpty()
    private var answer = initial?.getString("answer").orEmpty()
    private var evidence = initial?.getString("result")?.let {
        runCatching { MemorySearchResult.fromJson(JSONObject(it)) }.getOrNull()
    }
    // The elderly screen leads with voice and example questions, so the field needs no title.
    val input = ui.input(this, if (large) "" else "어떤 추억이 궁금하세요?",
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

    init {
        orientation = VERTICAL
        if (examples.isNotEmpty() || voice != null) {
            val choices = ui.column().apply { tag = "memory-examples" }
            if (voice != null) {
                choices.addView(voiceArea, LayoutParams(-1, -2))
                voiceIdle()
                ui.gap(choices, 20)
            }
            if (examples.isNotEmpty()) ui.label(choices, "이렇게 물어보세요", if (large) 22f else 18f, true)
            examples.forEach { question ->
                ui.ghost(choices, question, if (large) 70 else 56) {
                    if (!pending) { input.setText(question); search() }
                }.apply { contentDescription = "$question 물어보기"; isAllCaps = false; tag = "memory-example" }
            }
            ui.gap(choices, 20)
            ui.label(choices, "글로 물어보셔도 돼요", if (large) 20f else 16f, color = ui.muted)
            ui.gap(choices, 8)
            addView(choices, 0, LayoutParams(-1, -2))
        }
        addView(historyBox, LayoutParams(-1, -2))
        renderHistory()
        ui.gap(this, 16)
        addView(loading, LayoutParams(-1, -2))
        addView(error, LayoutParams(-1, -2))
        addView(result, LayoutParams(-1, -2))
        ui.gap(this, 20)
        ui.label(this, "AI 답변은 틀릴 수 있고,\n정리 중인 소식은 검색에서 빠질 수 있어요.",
            if (large) 20f else 15f, color = ui.muted)
        input.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) = Unit
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) { updateControls() }
            override fun afterTextChanged(s: Editable?) = Unit
        })
        if (answer.isNotBlank()) showAnswer()
        updateControls()
        post { scrollParent()?.scrollTo(0, initial?.getInt("scrollY", 0) ?: 0) }
    }

    private fun scrollParent(): ScrollView? = generateSequence(parent as? View) { it.parent as? View }
        .filterIsInstance<ScrollView>().firstOrNull()

    fun snapshot() = Bundle().apply {
        putString("draft", input.text.toString())
        putString("question", answeredQuestion)
        putString("answer", answer)
        putString("result", evidence?.toJson()?.toString())
        putInt("scrollY", scrollParent()?.scrollY ?: 0)
    }

    private fun updateControls() {
        input.isEnabled = !pending
        searchButton.isEnabled = !pending && input.text.isNotBlank()
        searchButton.alpha = if (searchButton.isEnabled) 1f else .45f
        searchButton.text = if (pending) "추억을 찾는 중이에요" else "추억 찾기"
        loading.visibility = if (pending) VISIBLE else GONE
    }

    private fun search() {
        val question = input.text.toString().trim()
        if (pending || question.isBlank() || !isAttachedToWindow) return
        if (telemetryOperation == null || telemetryQuestion != question) {
            telemetryOperation = Telemetry.start("family_history")
            telemetryQuestion = question
        }
        val operation = telemetryOperation!!
        pending = true
        error.visibility = GONE; login.visibility = GONE
        answeredQuestion = ""; answer = ""; evidence = null; result.removeAllViews()
        input.clearFocus()
        (activity.getSystemService(Context.INPUT_METHOD_SERVICE) as InputMethodManager)
            .hideSoftInputFromWindow(windowToken, 0)
        updateControls()
        val request = ++generation
        val cancel = RequestCancellation().also { cancellation = it }
        task = executor.submit {
            val response = runCatching { client.tracked(operation).searchHistory(question, cancel) }
            activity.runOnUiThread {
                if (generation != request || !isAttachedToWindow || activity.isDestroyed) return@runOnUiThread
                task = null; cancellation = null; pending = false
                response.fold({ found ->
                    operation.stage("answer_received")
                    post { operation.stage("screen_shown") }
                    telemetryOperation = null
                    answeredQuestion = question; answer = found.text; evidence = found
                    revealAnswer(showAnswer())
                    remember?.invoke(question, found)
                    pastSearches.removeAll { it.first.trim() == question }
                    pastSearches.add(0, question to found.toJson())
                    while (pastSearches.size > 20) pastSearches.removeAt(pastSearches.lastIndex)
                    renderHistory()
                }, { failure ->
                    operation.stage("answer_received", "error")
                    error.text = when {
                        failure is ApiException && failure.status == 401 -> "로그인이 만료되었어요. 다시 로그인해 주세요."
                        else -> ApiFailureMessages.failure(ApiFailureMessages.Task.MEMORY, failure)?.text
                            ?: (failure as? ApiException)?.message
                            ?: ApiFailureMessages.Task.MEMORY.let { it.title + "\n" + it.next }
                    }
                    error.visibility = VISIBLE
                    login.visibility = if (failure is ApiException && failure.status == 401) VISIBLE else GONE
                })
                updateControls()
            }
        }
    }

    /** One collapsed toggle with earlier searches; choosing one shows its saved answer and posts. */
    private fun renderHistory() {
        historyBox.removeAllViews()
        if (pastSearches.isEmpty()) return
        ui.gap(historyBox, 12)
        val label = "이전에 찾아본 추억 ${pastSearches.size}개 " + if (historyOpen) "닫기 ▴" else "보기 ▾"
        ui.ghost(historyBox, label) {
            historyOpen = !historyOpen
            renderHistory()
        }.apply { tag = "memory-history-toggle"; contentDescription = label; isAllCaps = false }
        if (!historyOpen) return
        val list = ui.column().apply { tag = "memory-history-list" }
        pastSearches.forEach { (question, saved) ->
            ui.gap(list, 8)
            ui.ghost(list, question, if (large) 64 else 52) {
                if (pending) return@ghost
                val found = runCatching { MemorySearchResult.fromJson(saved) }.getOrNull() ?: return@ghost
                input.setText(question)
                answeredQuestion = question; answer = found.text; evidence = found
                error.visibility = GONE; login.visibility = GONE
                historyOpen = false; renderHistory()
                revealAnswer(showAnswer())
            }.apply { contentDescription = "$question 다시 보기"; isAllCaps = false; tag = "memory-history-item" }
        }
        historyBox.addView(list, LayoutParams(-1, -2))
    }

    /** Only after a fresh search: bring the answer card to the top so the answer and first post are visible. */
    private fun revealAnswer(card: View) = card.doOnLayout {
        val scroll = scrollParent() ?: return@doOnLayout
        // Card position inside the scroll content, summed up to the ScrollView's single child.
        var top = 0; var view: View = card
        while (view.parent !== scroll) { top += view.top; view = view.parent as? View ?: return@doOnLayout }
        // An instant jump finishes inside this layout pass; an animated scroll would keep moving after
        // anything else (the reader or a test) scrolls next and override that position.
        scroll.scrollTo(0, (top - ui.dp(12)).coerceAtLeast(0))
    }

    private fun showAnswer(): View {
        result.removeAllViews()
        ui.gap(result, 16)
        val card = ui.card(result, ui.sky, stroke = false)
        ui.label(card, answer, if (large) 23f else 18f, color = ui.skyDeep).apply {
            tag = "memory-answer"
            setTextIsSelectable(true)
            accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
        }
        listen?.invoke(card, answer)
        ui.gap(result, 24)
        ui.label(result, "이 이야기가 담긴 소식", if (large) 24f else 20f, true)
        ui.gap(result, 12)
        val found = evidence
        if (found?.unavailable == true) {
            ui.label(result, "일부 소식을 불러오지 못했어요. 다시 추억 찾기를 누르면 재시도할 수 있어요.",
                if (large) 20f else 15f, color = ui.muted)
            ui.gap(result, 12)
        }
        if (found == null || found.posts.isEmpty()) {
            ui.label(result, "연결된 원문 게시글이 없어요.", if (large) 20f else 16f, color = ui.muted)
        } else {
            found.posts.forEach { post -> renderPost(result, post); ui.gap(result, 20) }
        }
        return card
    }

    private fun voiceIdle(message: String = "") {
        voiceArea.removeAllViews()
        ui.button(voiceArea, "말로 물어보기", true, if (large) 76 else 56) { startVoice() }.apply {
            tag = "memory-voice-start"; contentDescription = "말로 물어보기"
        }
        if (message.isNotBlank()) ui.label(voiceArea, message, if (large) 19f else 15f, color = ui.coralDeep).apply {
            accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
        }
    }

    /** Starts recording; the activity calls this again once the microphone is allowed. */
    fun startVoice() {
        val access = voice ?: return
        if (pending || voiceTask != null) return
        if (!access.hasMicrophone()) { access.requestMicrophone(this); return }
        cancelVoice()
        access.beforeRecording()
        val request = voiceGeneration
        val engine = kr.talkdock.app.device.Recorder(activity) {
            activity.runOnUiThread { if (request == voiceGeneration && recorder?.active == true) finishVoice() }
        }
        recorder = engine
        if (runCatching { engine.start() }.isFailure) {
            recorder = null; voiceIdle("녹음을 시작하지 못했어요. 마이크 사용을 확인해 주세요."); return
        }
        voiceArea.removeAllViews()
        ui.label(voiceArea, "듣고 있어요", if (large) 23f else 19f, true).accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
        ui.label(voiceArea, "궁금한 것을 말씀하신 뒤 아래 버튼을 눌러 주세요.", if (large) 18f else 15f, color = ui.muted)
        ui.button(voiceArea, "■ 다 말했어요", true, if (large) 76 else 56) { finishVoice() }.apply { tag = "memory-voice-finish" }
        ui.ghost(voiceArea, "취소", if (large) 64 else 48) { cancelVoice(); voiceIdle() }
    }

    fun microphoneDenied() = voiceIdle("말로 물어보려면 마이크 사용을 허용해 주세요.")

    private fun finishVoice() {
        val audio = runCatching { recorder?.finish() }.getOrNull()
        recorder = null
        if (audio == null) { voiceIdle("조금 더 길게 다시 말씀해 주세요."); return }
        voiceArea.removeAllViews()
        ui.waiting(voiceArea, "말씀을 글로 바꾸고 있어요.", large)
        val request = ++voiceGeneration
        voiceTask = executor.submit {
            val result = runCatching {
                try { client.transcribePost(audio).getString("recognized").trim() } finally { audio.delete() }
            }
            activity.runOnUiThread {
                if (request != voiceGeneration || !isAttachedToWindow || activity.isDestroyed) return@runOnUiThread
                voiceTask = null
                result.fold({ text ->
                    if (text.isBlank()) { voiceIdle("말씀을 알아듣지 못했어요. 다시 말씀해 주세요."); return@fold }
                    voiceIdle()
                    // The question stays editable in the field; searching publishes nothing.
                    input.setText(text.take(1000)); search()
                }, { failure ->
                    voiceIdle((failure as? ApiException)?.message ?: "말씀을 글로 바꾸지 못했어요. 다시 말씀해 주세요.")
                })
            }
        }
    }

    private fun cancelVoice() {
        voiceGeneration++
        voiceTask?.cancel(true); voiceTask = null
        recorder?.cancel(); recorder = null
    }

    override fun onDetachedFromWindow() {
        cancelVoice()
        generation++
        if (pending) telemetryOperation?.stage("screen_shown", "cancelled")
        cancellation?.cancel(); cancellation = null
        task?.cancel(true); task = null
        pending = false
        updateControls()
        super.onDetachedFromWindow()
    }
}
