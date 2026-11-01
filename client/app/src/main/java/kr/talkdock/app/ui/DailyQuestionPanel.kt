package kr.talkdock.app.ui

import android.content.Context
import android.content.res.ColorStateList
import android.graphics.Typeface
import android.os.Bundle
import android.text.InputFilter
import android.view.Gravity
import android.view.View
import android.view.inputmethod.InputMethodManager
import android.widget.*
import kr.talkdock.app.data.ApiClient
import org.json.JSONObject
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.util.concurrent.ExecutorService

/** A question owns one answer per person and an ordinary, shared post discussion. */
class DailyQuestionPanel(
    context: Context, private val ui: Ui, private val large: Boolean,
    private val api: ApiClient, private val executor: ExecutorService, private val userId: Int,
    private val roomId: Int, private val serverUrl: String,
    private val restored: Bundle? = null, openToday: Boolean = false, private val onSeen: (JSONObject) -> Unit,
    private val onVoice: (Int, String) -> Unit,
) : LinearLayout(context) {
    private var question: JSONObject? = null
    private var generation = 0
    private var working = false
    private var editing = restored?.getBoolean("editing", true) ?: true
    private var choice = restored?.getString("choice").orEmpty()
    private var otherText = restored?.getString("otherText").orEmpty()
    private var otherInput: EditText? = null
    private var tiers = JSONObject(restored?.getString("tiers") ?: "{}")
    private var source = restored?.getString("source") ?: "text"
    private var draftText = restored?.getString("draftText").orEmpty()
    private var commentDraft = restored?.getString("commentDraft").orEmpty()
    private var input: EditText? = null
    private var composer: CommentComposer? = null
    private var error: TextView? = null
    private var restoredApplied = false
    private val bodySize get() = if (large) 23f else 16f

    init {
        orientation = VERTICAL
        // A feed preview always resolves today's question first, including after
        // midnight. Historic/voice navigation can explicitly restore its question.
        post { load(if (openToday) null else restored?.getInt("questionId", 0)?.takeIf { it > 0 }) }
    }

    private fun objects(data: JSONObject, key: String): List<JSONObject> {
        val rows = data.optJSONArray(key) ?: return emptyList()
        return (0 until rows.length()).map { rows.getJSONObject(it) }
    }

    fun snapshot(): Bundle {
        capture()
        return Bundle().apply {
            putInt("userId", userId); putInt("roomId", roomId); putString("server", serverUrl)
            putInt("questionId", question?.optInt("id") ?: restored?.getInt("questionId", 0) ?: 0)
            putString("title", question?.optString("title").orEmpty())
            putBoolean("editing", editing); putString("choice", choice); putString("tiers", tiers.toString())
            putString("otherText", otherText)
            putString("draftText", draftText); putString("source", source)
            putString("commentDraft", commentDraft)
        }
    }

    private fun capture() {
        input?.let { draftText = it.text.toString() }
        otherInput?.let { otherText = it.text.toString() }
        composer?.let { commentDraft = it.input.text.toString() }
    }

    private fun resetViews() {
        input = null; otherInput = null; composer = null; error = null
        removeAllViews()
    }

    private fun hideKeyboard() {
        (context.getSystemService(Context.INPUT_METHOD_SERVICE) as InputMethodManager).hideSoftInputFromWindow(windowToken, 0)
    }

    private fun <T> request(work: () -> T, done: (T) -> Unit, failed: ((String) -> Unit)? = null) {
        if (working) return
        working = true
        val current = ++generation
        executor.execute {
            val result = runCatching(work)
            post {
                if (!isAttachedToWindow || current != generation) return@post
                working = false
                result.fold(done) { problem ->
                    val message = problem.message ?: "질문을 불러오지 못했어요. 다시 시도해 주세요."
                    if (failed != null) failed(message) else {
                        resetViews(); ui.note(this, message, large)
                        ui.ghost(this, "다시 불러오기") { load(question?.optInt("id")) }
                    }
                }
            }
        }
    }

    private fun load(id: Int? = null) {
        resetViews(); ui.label(this, "질문을 불러오고 있어요.", bodySize, color = ui.muted)
        request({ api.request(if (id == null) "daily-questions/today/" else "daily-questions/$id/") }, { data ->
            question = data
            val mine = objects(data, "answers").firstOrNull { it.optInt("author_id") == userId }
            val restoreDraft = !restoredApplied && restored?.getInt("questionId", 0) == data.getInt("id")
            if (!restoreDraft) {
                editing = mine == null; choice = mine?.optString("choice").orEmpty()
                otherText = mine?.optString("other_text").orEmpty()
                draftText = mine?.optString("text").orEmpty(); tiers = mine?.optJSONObject("tiers") ?: JSONObject()
                source = mine?.optString("source") ?: "text"
                commentDraft = ""
            }
            restoredApplied = true
            onSeen(data); render()
        })
    }

    private fun choiceChip(parent: LinearLayout, selected: String) =
        ui.label(parent, selected, if (large) 20f else 14f, true, ui.coralDeep).apply {
                tag = "daily-answer-choice"; contentDescription = "선택한 답변: $selected"
                background = ui.shape(ui.coral, 10)
                setPadding(ui.dp(8), ui.dp(4), ui.dp(8), ui.dp(4))
                maxWidth = ui.dp(if (large) 180 else 160)
        }

    private fun choiceLabel(answer: JSONObject): String = answer.optString("choice").let { selected ->
        if (selected == "기타" && answer.optString("other_text").isNotBlank()) "기타 · ${answer.optString("other_text")}" else selected
    }

    private fun renderAnswer(parent: LinearLayout, answer: JSONObject, includeChoice: Boolean = true) {
        choiceLabel(answer).takeIf { includeChoice && it.isNotBlank() }?.let { selected ->
            choiceChip(parent, selected); ui.gap(parent, 5)
        }
        val ranked = mutableListOf<String>()
        answer.optJSONObject("tiers")?.let { values ->
            val options = question?.optJSONArray("options")
            if (options != null) for (grade in listOf("S", "A", "B", "C")) {
                val items = (0 until options.length()).map { options.getString(it) }.filter { values.optString(it) == grade }
                if (items.isNotEmpty()) ranked.add("$grade · ${items.joinToString(", ")}")
            }
        }
        if (ranked.isNotEmpty()) { ui.label(parent, ranked.joinToString("\n"), bodySize, true, ui.coralDeep); ui.gap(parent, 5) }
        answer.optString("text").takeIf { it.isNotBlank() }?.let { ui.label(parent, it, bodySize) }
    }

    private fun textAction(parent: LinearLayout, title: String, action: () -> Unit): TextView =
        ui.label(parent, title, if (large) 19f else 14f, color = ui.muted).apply {
            gravity = Gravity.CENTER; minHeight = ui.dp(48); minWidth = ui.dp(48)
            setPadding(ui.dp(8), 0, ui.dp(8), 0)
            isClickable = true; isFocusable = true; contentDescription = title
            setOnClickListener { action() }
        }

    private fun renderChoices(parent: LinearLayout, data: JSONObject) {
        val options = data.getJSONArray("options")
        val mine = objects(data, "answers").firstOrNull { it.optInt("author_id") == userId }
        val selected = if (editing) choice else mine?.optString("choice").orEmpty()
        val radios = mutableListOf<RadioButton>()
        fun updateOtherField() {
            otherInput?.let { field ->
                field.visibility = if (choice == "기타") VISIBLE else GONE
                if (choice != "기타" && field.hasFocus()) { field.clearFocus(); hideKeyboard() }
            }
        }
        for (i in 0 until options.length()) {
            val option = options.getString(i)
            val row = ui.row().apply { setPadding(ui.dp(4), 0, ui.dp(8), 0) }
            val radio = RadioButton(context).apply {
                id = View.generateViewId(); tag = "daily-question-option"
                text = option; textSize = bodySize; typeface = ui.font
                setTextColor(ColorStateList.valueOf(ui.ink))
                buttonTintList = ColorStateList(arrayOf(intArrayOf(android.R.attr.state_checked), intArrayOf()), intArrayOf(ui.coralDeep, ui.muted))
                minHeight = ui.dp(if (large) 60 else 48); setPadding(ui.dp(6), ui.dp(6), ui.dp(8), ui.dp(6))
                fun style(checked: Boolean) {
                    row.background = ui.shape(if (checked) ui.blush else ui.paper, 12, stroke = true).apply {
                        if (checked) setStroke(ui.dp(1), ui.coralDeep)
                    }
                    typeface = Typeface.create(ui.font, if (checked) Typeface.BOLD else Typeface.NORMAL)
                    contentDescription = "선택지: $option" + if (checked) ", 내 선택" else ""
                }
                isChecked = option == selected; isEnabled = editing; style(isChecked)
                setOnCheckedChangeListener { button, checked ->
                    if (checked && editing) {
                        radios.filter { it !== button }.forEach { it.isChecked = false }
                        choice = option; updateOtherField()
                        if (option == "기타") otherInput?.post {
                            otherInput?.requestFocus()
                            (context.getSystemService(Context.INPUT_METHOD_SERVICE) as InputMethodManager)
                                .showSoftInput(otherInput, InputMethodManager.SHOW_IMPLICIT)
                        }
                    }
                    style(checked)
                }
            }
            radios.add(radio)
            row.addView(radio, LayoutParams(if (option == "기타") -2 else -1, -2))
            if (option == "기타") {
                if (editing) {
                    otherInput = EditText(context).apply {
                        contentDescription = "기타 내용 입력"; hint = "직접 입력"; textSize = bodySize; typeface = ui.font
                        isSingleLine = true; setTextColor(ui.ink); setHintTextColor(ui.muted)
                        background = ui.shape(ui.paper, 8, stroke = true)
                        setPadding(ui.dp(10), ui.dp(8), ui.dp(10), ui.dp(8))
                        filters = arrayOf(InputFilter.LengthFilter(100)); setText(otherText)
                        visibility = if (choice == "기타") VISIBLE else GONE
                    }.also { row.addView(it, LayoutParams(0, ui.dp(if (large) 52 else 40), 1f).apply {
                        marginStart = ui.dp(6); topMargin = ui.dp(4); bottomMargin = ui.dp(4)
                    }) }
                } else if (selected == "기타") {
                    row.addView(ui.text(mine?.optString("other_text").orEmpty(), bodySize, true, ui.coralDeep),
                        LayoutParams(0, -2, 1f).apply { marginStart = ui.dp(6) })
                }
            }
            parent.addView(row, LayoutParams(-1, -2).apply { topMargin = ui.dp(6) })
        }
    }

    private fun render() {
        val data = question ?: return
        resetViews()
        val mine = objects(data, "answers").firstOrNull { it.optInt("author_id") == userId }
        val dateRow = ui.row()
        val date = runCatching { LocalDate.parse(data.getString("date")).format(DateTimeFormatter.ofPattern("M월 d일")) }.getOrDefault(data.getString("date"))
        dateRow.addView(ui.text(date, if (large) 18f else 14f, color = ui.muted), LayoutParams(0, -2, 1f))
        textAction(dateRow, "지난 질문") { history() }.text = "지난 질문 ›"
        addView(dateRow)
        val card = ui.card(this, ui.sheet, padding = 14, stroke = false).apply { background = ui.shape(ui.sheet, 16) }
        val labels = mapOf("choice" to "밸런스 게임", "text" to "한 줄 답변", "weather" to "오늘의 마음 날씨", "tier" to "티어 리스트")
        ui.label(card, labels[data.getString("kind")] ?: "오늘의 질문", if (large) 17f else 12f, true, ui.coralDeep).apply {
            layoutParams = LayoutParams(-2, -2)
            background = ui.shape(ui.coral, 10); setPadding(ui.dp(8), ui.dp(4), ui.dp(8), ui.dp(4))
        }
        ui.gap(card, 8); ui.label(card, data.getString("title"), if (large) 28f else 22f, true)
        if (data.getString("kind") in listOf("choice", "weather")) {
            ui.gap(card, 6); renderChoices(card, data)
        }
        if (editing) { ui.gap(card, 12); renderEditor(card, data) } else {
            val ownRow = ui.row()
            ownRow.addView(ui.text("내 답변" + mine?.let { choiceLabel(it) }.orEmpty().takeIf { it.isNotBlank() }?.let { " · $it" }.orEmpty(),
                if (large) 19f else 14f, true, ui.skyDeep), LayoutParams(0, -2, 1f))
            textAction(ownRow, "내 답변 수정") { capture(); editing = true; render() }.text = "수정"
            card.addView(ownRow)
            if (data.getString("kind") in listOf("text", "tier")) mine?.let { renderAnswer(card, it) }
            else mine?.optString("text")?.takeIf { it.isNotBlank() }?.let { ui.label(card, it, bodySize) }
        }
        ui.gap(this, 18)
        val answers = objects(data, "answers")
        ui.label(this, "가족 답변 ${answers.size}", if (large) 24f else 18f, true); ui.gap(this, 8)
        if (answers.isEmpty()) ui.label(this, "가족의 첫 이야기를 기다리고 있어요.", bodySize, color = ui.muted)
        answers.forEach { answer ->
            val box = ui.card(this, ui.blush, padding = 12, stroke = false).apply { background = ui.shape(ui.blush, 12) }
            val row = ui.row().apply { gravity = Gravity.TOP }
            val avatarSize = if (large) 40 else 32
            row.addView(ui.text(answer.getString("author_name").take(1), if (large) 15f else 12f, true, ui.skyDeep).apply {
                gravity = Gravity.CENTER; background = ui.shape(ui.coral, avatarSize / 2)
                importantForAccessibility = IMPORTANT_FOR_ACCESSIBILITY_NO
            }, LayoutParams(ui.dp(avatarSize), ui.dp(avatarSize)))
            val words = ui.column()
            val name = answer.getString("author_name") + if (answer.optInt("author_id") == userId) " · 나" else ""
            val answerHeading = ui.row()
            answerHeading.addView(ui.text(name, if (large) 21f else 15f, true), LayoutParams(0, -2, 1f).apply { marginEnd = ui.dp(8) })
            choiceLabel(answer).takeIf { it.isNotBlank() }?.let { choiceChip(answerHeading, it) }
            words.addView(answerHeading); ui.gap(words, 4)
            renderAnswer(words, answer, includeChoice = false)
            row.addView(words, LayoutParams(0, -2, 1f).apply { marginStart = ui.dp(10) })
            box.addView(row); ui.gap(this, 8)
        }
        ui.gap(this, 8); ui.line(this); ui.gap(this, 12)
        val comments = objects(data, "comments")
        ui.label(this, "댓글 ${comments.size}", if (large) 24f else 18f, true); ui.gap(this, 8)
        comments.forEach { comment ->
            val bubble = ui.card(this, ui.blush, padding = 12, stroke = false).apply { background = ui.shape(ui.blush, 12) }
            ui.label(bubble, comment.getString("author_name"), if (large) 20f else 14f, true)
            ui.gap(bubble, 4); ui.label(bubble, comment.getString("text"), bodySize); ui.gap(this, 8)
        }
        val field = CommentComposer(context, ui, large, title = "", hintText = "댓글 남기기", compact = true,
            compactFieldHeight = if (large) 80 else 56,
            onVoice = { capture(); onVoice(data.getInt("post_id"), "comment") }) { text ->
            if (!working) {
                capture()
                if (text.length > 2000) composer?.showError("댓글은 2,000자까지 남길 수 있어요.") else {
                    composer?.setSending(true)
                    request({
                        val accepted = api.request("posts/${data.getInt("post_id")}/comments/", "POST", JSONObject().put("text", text))
                        // An accepted comment is not resent when only its refresh fails.
                        runCatching { api.request("daily-questions/${data.getInt("id")}/", readTimeoutMillis = 10_000) }.getOrElse {
                            JSONObject(data.toString()).apply {
                                getJSONArray("comments").put(JSONObject().put("id", accepted.getInt("id"))
                                    .put("author_id", userId).put("author_name", "나").put("text", text).put("source", "text"))
                            }
                        }
                    }, { updated ->
                        question = updated; commentDraft = ""; onSeen(updated); hideKeyboard(); render()
                    }, { message -> composer?.showError(message) })
                }
            }
        }
        composer = field; field.input.setText(commentDraft); addView(field, LayoutParams(-1, -2))
    }

    private fun renderEditor(parent: LinearLayout, data: JSONObject) {
        val inputRow = ui.row()
        inputRow.addView(ui.text("내 답변", bodySize, true), LayoutParams(0, -2, 1f))
        inputRow.addView(ui.iconButton("mic", "말로 답하기") { capture(); onVoice(data.getInt("post_id"), "answer") })
        parent.addView(inputRow)
        val options = data.getJSONArray("options")
        val kind = data.getString("kind")
        if (kind == "tier") {
            ui.label(parent, "눌러서 등급을 골라 주세요. 같은 등급에 여러 개를 넣어도 괜찮아요.", if (large) 20f else 16f, color = ui.muted)
            ui.label(parent, "S 꼭 하고 싶어요 · A 좋아요 · B 괜찮아요 · C 다음에", if (large) 18f else 12f, color = ui.muted)
            for (i in 0 until options.length()) {
                val option = options.getString(i)
                val row = ui.row()
                row.addView(ui.text(option, bodySize), LayoutParams(0, -2, 1f))
                row.addView(Spinner(context).apply {
                    contentDescription = "$option 등급"
                    adapter = object : ArrayAdapter<String>(context, android.R.layout.simple_spinner_item, listOf("선택", "S", "A", "B", "C")) {
                        override fun getView(position: Int, convertView: View?, parent: android.view.ViewGroup): View =
                            super.getView(position, convertView, parent).also { (it as TextView).textSize = bodySize; it.setTextColor(ui.ink) }
                        override fun getDropDownView(position: Int, convertView: View?, parent: android.view.ViewGroup): View =
                            super.getDropDownView(position, convertView, parent).also {
                                (it as TextView).textSize = bodySize; it.typeface = ui.font; it.setTextColor(ui.ink)
                                it.minHeight = ui.dp(if (large) 64 else 48); it.gravity = Gravity.CENTER_VERTICAL
                            }
                    }.also { it.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item) }
                    setSelection(listOf("", "S", "A", "B", "C").indexOf(tiers.optString(option)).coerceAtLeast(0))
                    onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
                        override fun onItemSelected(parent: AdapterView<*>?, view: View?, position: Int, id: Long) {
                            if (position == 0) tiers.remove(option) else tiers.put(option, listOf("", "S", "A", "B", "C")[position])
                        }
                        override fun onNothingSelected(parent: AdapterView<*>?) = Unit
                    }
                }, LayoutParams(ui.dp(112), ui.dp(if (large) 64 else 52)))
                parent.addView(row)
            }
        }
        input = ui.input(parent, if (kind == "text") "가족에게 내 이야기를 들려주세요" else "이유 한마디 (선택)",
            if (kind == "text") "짧은 이야기부터 편하게 적어 주세요." else "왜 그렇게 생각했나요?", multiline = true, initial = draftText).apply {
            layoutParams = layoutParams.apply { height = ui.dp(if (large) 112 else 84) }
            textSize = bodySize; filters = arrayOf(InputFilter.LengthFilter(1000)); contentDescription = "오늘의 질문 답변 입력"
        }
        val send = ui.button(parent, if (objects(data, "answers").any { it.optInt("author_id") == userId }) "답변 수정하기" else "답변 남기기", height = if (large) 64 else 48) {
            if (!working) {
                capture()
                if (choice == "기타" && otherText.isBlank()) {
                    otherInput?.error = "기타 내용을 입력해 주세요."; otherInput?.requestFocus(); return@button
                }
                val payload = JSONObject().put("choice", choice).put("other_text", if (choice == "기타") otherText else "")
                    .put("text", draftText).put("tiers", tiers).put("source", source)
                request({ api.request("daily-questions/${data.getInt("id")}/answer/", "PUT", payload) }, { updated ->
                    question = updated; editing = false
                    otherText = objects(updated, "answers").firstOrNull { it.optInt("author_id") == userId }?.optString("other_text").orEmpty()
                    onSeen(updated); hideKeyboard(); render()
                }, { message -> error?.text = message; error?.visibility = VISIBLE })
            }
        }
        send.contentDescription = "오늘의 질문 답변 저장"
        error = ui.label(parent, "", if (large) 20f else 16f, color = ui.coralDeep).apply { visibility = GONE; accessibilityLiveRegion = ACCESSIBILITY_LIVE_REGION_POLITE }
        ui.gap(parent, 8); ui.label(parent, "답변은 우리 가족에게 보여요. 나중에 수정할 수 있어요.", if (large) 18f else 12f, color = ui.muted)
    }

    private fun history(before: String? = null) {
        capture()
        resetViews(); ui.label(this, "지난 질문을 불러오고 있어요.", bodySize)
        request({ api.request("daily-questions/history/" + if (before == null) "" else "?before=$before") }, { result ->
            resetViews()
            ui.ghost(this, "오늘의 질문으로") { choice = ""; otherText = ""; tiers = JSONObject(); draftText = ""; commentDraft = ""; load() }
            objects(result, "questions").forEach { row ->
                ui.ghost(this, "${row.getString("date")}\n${row.getString("title")}", if (large) 100 else 80) {
                    choice = ""; otherText = ""; tiers = JSONObject(); draftText = ""; commentDraft = ""; load(row.getInt("id"))
                }
            }
            result.optString("next_before").takeIf { it.isNotBlank() && it != "null" }?.let { next ->
                ui.ghost(this, "이전 질문 더 보기") { history(next) }
            }
        })
    }

    override fun onDetachedFromWindow() {
        capture(); generation++; working = false
        super.onDetachedFromWindow()
    }
}
