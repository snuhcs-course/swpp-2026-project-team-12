package kr.talkdock.app.data

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.io.ByteArrayOutputStream
import java.net.ServerSocket

class MemorySearchResultTest {
    private fun post(id: Int) = JSONObject().put("id", id).put("author_name", "테스트 가족")
        .put("caption", "가족 여행 소식").put("created_at", "2026-10-01T09:00:00+09:00")
        .put("relationship", "가족").put("comment_count", 0).put("images", JSONArray())
    private fun legacy() = JSONObject("""{"text":"부산 여행이에요.","memories":[{"sources":[
        {"id":"one","name":"post_12"},{"id":"two","name":"post_9"},
        {"id":"repeated","name":"post_12"},{"id":"relationship","name":"family_1"},
        {"id":"url","name":"https://example.com/post_1"},{"id":"negative","name":"post_-1"},
        {"id":"large","name":"post_99999999999999999999999"}]}]}""")

    @Test fun fullFeedPostsKeepImagesCaptionOrderAndSurviveSnapshotRoundTrip() {
        val first = post(12).put("images", JSONArray().put(JSONObject().put("id", 0).put("url", "/first/"))
            .put(JSONObject().put("id", 1).put("url", "/second/")))
            .put("comments", JSONArray().put(JSONObject().put("text", "댓글은 상세 화면에서 불러와요.")))
        val result = MemorySearchResult.fromJson(JSONObject().put("text", "부산 여행이에요.")
            .put("evidence_kind", "cited").put("evidence_posts", JSONArray().put(first).put(post(9)).put(first)))
        assertEquals(listOf(12, 9), result.posts.map { it.getInt("id") })
        assertFalse(result.posts.first().has("comments"))
        assertEquals("/second/", result.posts.first().getJSONArray("images").getJSONObject(1).getString("url"))
        val restored = MemorySearchResult.fromJson(JSONObject(result.toJson().toString()))
        assertEquals(result.toJson().toString(), restored.toJson().toString())
        assertTrue(restored.cited)
    }

    @Test fun legacySourcesUseOnlyExactPostNamesAndDeduplicateWithoutGuessing() {
        assertEquals(listOf(12, 9), MemorySearchResult.legacyPostIds(legacy()))
        assertEquals(listOf(9), MemorySearchResult.legacyPostIds(legacy()
            .put("source_episode_ids", JSONArray().put("two").put("invented"))))
        assertTrue(MemorySearchResult.legacyPostIds(legacy().put("source_episode_ids", JSONArray())).isEmpty())
    }

    @Test fun emptyOrMalformedAnswersFailWithoutDiscardingTheCallersDraft() {
        for (body in listOf("{}", "{\"text\":null}", "{\"text\":3}", "{\"text\":\" \"}"))
            assertThrows(ApiException::class.java) { MemorySearchResult.fromJson(JSONObject(body)) }
    }

    private class Server(val reply: (String) -> Pair<Int, String>) : AutoCloseable {
        private val socket = ServerSocket(0)
        val base = "http://127.0.0.1:${socket.localPort}/api/"
        val requests = mutableListOf<List<String>>()
        private val worker = Thread {
            while (!socket.isClosed) {
                val client = runCatching { socket.accept() }.getOrNull() ?: break
                client.use {
                    val input = client.getInputStream()
                    val header = ByteArrayOutputStream()
                    while (true) {
                        val next = input.read()
                        if (next == -1) break
                        header.write(next)
                        if (header.toString("UTF-8").endsWith("\r\n\r\n")) break
                    }
                    val lines = header.toString("UTF-8").split("\r\n")
                    val path = lines.first().split(" ")[1]
                    val size = lines.firstOrNull { it.startsWith("Content-Length:", true) }
                        ?.substringAfter(':')?.trim()?.toInt() ?: 0
                    repeat(size) { input.read() }
                    requests.add(lines)
                    val (status, text) = reply(path)
                    val body = text.toByteArray(Charsets.UTF_8)
                    client.getOutputStream().apply {
                        write("HTTP/1.1 $status Test\r\nContent-Length: ${body.size}\r\nConnection: close\r\n\r\n".toByteArray())
                        write(body); flush()
                    }
                }
            }
        }.apply { isDaemon = true; start() }
        override fun close() { socket.close(); worker.join(1000) }
    }

    @Test fun deployedServerSourcesFetchAuthenticatedOriginalPostsInTheSameRoom() {
        Server { path -> 200 to if (path.endsWith("history/")) legacy().toString()
            else post(if (path.contains("12")) 12 else 9).put("comments", JSONArray().put("상세 댓글")).toString() }.use { server ->
            val result = ApiClient("token", server.base, 7).searchHistory("가족 여행", RequestCancellation())
            assertEquals(listOf(12, 9), result.posts.map { it.getInt("id") })
            assertFalse(result.cited)
            assertTrue(result.posts.all { !it.has("comments") })
            assertEquals(3, server.requests.size)
            assertTrue(server.requests.all { lines -> lines.any { it.equals("Authorization: Bearer token", true) }
                && lines.any { it.equals("X-Family-Room: 7", true) } })
        }
    }

    @Test fun explicitEmptyEvidenceDoesNotFallBackToUncitedSearchResults() {
        Server { 200 to legacy().put("evidence_posts", JSONArray()).put("evidence_kind", "cited").toString() }.use { server ->
            assertTrue(ApiClient(baseUrl = server.base).searchHistory("질문", RequestCancellation()).posts.isEmpty())
            assertEquals(1, server.requests.size)
        }
    }

    @Test fun deletedEvidenceIsSkippedButNetworkFailuresKeepTheAnswerWithNotice() {
        Server { path -> when {
            path.endsWith("history/") -> 200 to legacy().toString()
            path.contains("12") -> 404 to "{}"
            else -> 503 to "{}"
        } }.use { server ->
            val result = ApiClient(baseUrl = server.base).searchHistory("질문", RequestCancellation())
            assertEquals("부산 여행이에요.", result.text)
            assertTrue(result.posts.isEmpty()); assertTrue(result.unavailable)
        }
    }
}
