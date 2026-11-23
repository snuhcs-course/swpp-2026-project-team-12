package kr.talkdock.app.data

import android.content.Context
import android.content.SharedPreferences
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.security.MessageDigest

/**
 * Device-only drafts: the unfinished post, unsent comments and past questions to Todak.
 * Nothing here is sent to the server. Every entry belongs to one server, account and family room,
 * so switching accounts or rooms on a shared phone never shows another person's text.
 */
internal class LocalDrafts(context: Context) {
    data class PostDraft(val text: String, val photos: List<File>)

    private val prefs: SharedPreferences = context.getSharedPreferences("talkdock-local-drafts", Context.MODE_PRIVATE)

    fun post(scope: PostingScope): PostDraft? {
        val saved = prefs.getString("post:" + key(scope), null)?.let { runCatching { JSONObject(it) }.getOrNull() } ?: return null
        val photos = saved.optJSONArray("photos")?.let { list -> (0 until list.length()).map { File(list.getString(it)) } }
            .orEmpty().filter { it.isFile && it.length() > 0 }
        val text = saved.optString("text")
        return if (text.isBlank() && photos.isEmpty()) null else PostDraft(text, photos)
    }

    /** Photos stay where the composer keeps them (app storage), so only their paths are saved. */
    fun savePost(scope: PostingScope, text: String, photos: List<File>) {
        if (text.isBlank() && photos.isEmpty()) { clearPost(scope); return }
        val value = JSONObject().put("text", text.take(MAX_TEXT)).put("photos", JSONArray(photos.map { it.absolutePath }))
        prefs.edit().putString("post:" + key(scope), value.toString()).apply()
    }

    fun clearPost(scope: PostingScope) = prefs.edit().remove("post:" + key(scope)).apply()

    fun comment(scope: PostingScope, postId: Int): String? =
        prefs.getString("comment:" + key(scope) + ":" + postId, null)?.takeIf { it.isNotBlank() }

    fun saveComment(scope: PostingScope, postId: Int, text: String) {
        val name = "comment:" + key(scope) + ":" + postId
        if (text.isBlank()) prefs.edit().remove(name).apply() else prefs.edit().putString(name, text.take(MAX_TEXT)).apply()
    }

    /** A finished send removes the draft only if it is still the text that was sent. */
    fun clearCommentIfSent(scope: PostingScope, postId: Int, sent: String) {
        if (comment(scope, postId)?.trim() == sent.trim()) saveComment(scope, postId, "")
    }

    fun questions(scope: PostingScope, postId: Int): List<Pair<String, String>> {
        val turns = questionBook(scope).optJSONObject(postId.toString())?.optJSONArray("turns") ?: return emptyList()
        return (0 until turns.length()).mapNotNull { index ->
            turns.optJSONArray(index)?.takeIf { it.length() == 2 }?.let { it.getString(0) to it.getString(1) }
        }
    }

    /** Keeps the latest turns of the most recently asked posts; the oldest posts drop out first. */
    fun addQuestion(scope: PostingScope, postId: Int, question: String, answer: String) {
        val book = questionBook(scope)
        val turns = (questions(scope, postId) + (question.take(MAX_TEXT) to answer.take(MAX_ANSWER))).takeLast(MAX_TURNS)
        book.put(postId.toString(), JSONObject().put("at", System.currentTimeMillis())
            .put("turns", JSONArray(turns.map { JSONArray(listOf(it.first, it.second)) })))
        val posts = book.keys().asSequence().toList()
        posts.sortedByDescending { book.optJSONObject(it)?.optLong("at") ?: 0L }.drop(MAX_POSTS).forEach { book.remove(it) }
        prefs.edit().putString("questions:" + key(scope), book.toString()).apply()
    }

    /** Explicit logout: forget this account's drafts on this phone and return the post photos to delete. */
    fun clearAccount(server: String, userId: Int): List<File> {
        val prefix = hash(server) + ":" + userId + ":"
        val names = prefs.all.keys.filter { name -> name.substringAfter(':').startsWith(prefix) }
        val photos = names.filter { it.startsWith("post:") }.flatMap { name ->
            prefs.getString(name, null)?.let { runCatching { JSONObject(it) }.getOrNull() }?.optJSONArray("photos")
                ?.let { list -> (0 until list.length()).map { File(list.getString(it)) } }.orEmpty()
        }
        prefs.edit().apply { names.forEach(::remove) }.apply()
        return photos
    }

    private fun questionBook(scope: PostingScope) =
        prefs.getString("questions:" + key(scope), null)?.let { runCatching { JSONObject(it) }.getOrNull() } ?: JSONObject()

    private fun key(scope: PostingScope) = hash(scope.server) + ":" + scope.userId + ":" + scope.roomId

    private fun hash(value: String) = MessageDigest.getInstance("SHA-256").digest(value.toByteArray())
        .take(8).joinToString("") { "%02x".format(it) }

    companion object {
        const val MAX_TEXT = 2000
        const val MAX_ANSWER = 4000
        const val MAX_TURNS = 10
        const val MAX_POSTS = 30
    }
}
