package kr.talkdock.app.data

import org.json.JSONArray
import org.json.JSONObject

/** Full feed posts, not a second thumbnail representation of the same data. */
data class MemorySearchResult(
    val text: String,
    val posts: List<JSONObject> = emptyList(),
    val cited: Boolean = false,
    val unavailable: Boolean = false
) {
    fun toJson() = JSONObject().put("text", text).put("evidence_posts", JSONArray(posts))
        .put("evidence_kind", if (cited) "cited" else "retrieved").put("evidence_unavailable", unavailable)

    companion object {
        fun fromJson(value: JSONObject): MemorySearchResult {
            val text = (value.opt("text") as? String)?.takeUnless { it.isBlank() }
                ?: throw ApiException("추억을 찾지 못했어요. 잠시 후 다시 시도해 주세요.")
            val posts = value.optJSONArray("evidence_posts") ?: JSONArray()
            val unique = linkedMapOf<Int, JSONObject>()
            for (index in 0 until posts.length()) {
                val post = posts.optJSONObject(index) ?: continue
                // Legacy detail responses include all comments. The feed needs
                // only their count; do not put an unbounded thread in a Bundle.
                post.remove("comments")
                if (post.optInt("id") > 0 && post.has("author_name") && post.has("caption") && post.has("created_at")
                    && post.has("relationship") && post.has("comment_count"))
                    unique.putIfAbsent(post.getInt("id"), post)
            }
            return MemorySearchResult(text, unique.values.toList(), value.optString("evidence_kind") == "cited",
                value.optBoolean("evidence_unavailable"))
        }

        /** Compatibility with the deployed server's room-scoped Graphiti response. */
        fun legacyPostIds(value: JSONObject): List<Int> {
            val memories = value.optJSONArray("memories") ?: return emptyList()
            val citations = value.optJSONArray("source_episode_ids")
            val sources = linkedMapOf<String, String>()
            for (index in 0 until memories.length()) {
                val items = memories.optJSONObject(index)?.optJSONArray("sources") ?: continue
                for (sourceIndex in 0 until items.length()) {
                    val source = items.optJSONObject(sourceIndex) ?: continue
                    sources.putIfAbsent(source.optString("id"), source.optString("name"))
                }
            }
            val names = if (citations == null) sources.values.toList() else
                (0 until citations.length()).mapNotNull { sources[citations.optString(it)] }
            return names.mapNotNull { name ->
                Regex("^post_([1-9][0-9]*)$").matchEntire(name)?.groupValues?.get(1)?.toIntOrNull()
            }.distinct().take(20)
        }
    }
}
