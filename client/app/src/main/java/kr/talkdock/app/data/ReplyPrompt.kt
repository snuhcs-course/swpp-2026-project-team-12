package kr.talkdock.app.data

import org.json.JSONObject

/**
 * Rule-based closing line spoken after an elderly listener hears a family post.
 * The relationship label is already resolved from the viewer's side by the server.
 */
object ReplyPrompt {
    private val generic = setOf("", "가족", "인척", "공동 부모 쪽 가족")
    private val none = setOf("나", "오늘의 질문")

    fun forPost(post: JSONObject, viewerId: Int?): String? {
        val author = post.optInt("author_id", -1)
        if (viewerId != null && author == viewerId) return null
        val relation = post.optString("relationship").trim()
        if (relation in none) return null
        val name = post.optString("author_name").trim()
        val subject = when {
            relation !in generic -> relation
            name.isNotEmpty() -> name + "님"
            else -> return null
        }
        return "${subject}의 소식에 답장해 보시는 건 어떨까요?"
    }

    /** Appends the closing as its own sentence. */
    fun spoken(text: String, closing: String?): String {
        val body = text.trim()
        if (closing.isNullOrBlank() || body.isEmpty()) return text
        val ended = body.last() in ".!?…。" || body.endsWith("요") || body.endsWith("다")
        return body + (if (ended) " " else ". ") + closing
    }
}
