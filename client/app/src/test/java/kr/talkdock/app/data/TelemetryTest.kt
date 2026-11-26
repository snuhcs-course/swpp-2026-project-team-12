package kr.talkdock.app.data

import com.sun.net.httpserver.HttpServer
import org.junit.After
import org.junit.Assert.*
import org.junit.Test
import java.net.InetSocketAddress

class TelemetryTest {
    @After fun cleanup() { Telemetry.sink = null }

    @Test fun retriesKeepOperationAndCountHttpAttemptsWithoutContent() {
        val records = mutableListOf<Pair<String, Map<String, Any>>>()
        Telemetry.sink = { name, fields -> records.add(name to fields) }
        val observedIds = mutableListOf<String>()
        val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        server.createContext("/api/posts/") { exchange ->
            observedIds.add(exchange.requestHeaders.getFirst("X-Operation-ID"))
            exchange.responseHeaders.add("X-Request-ID", "server-request-${observedIds.size}")
            val body = "{\"text\":\"PRIVATE family text\"}".toByteArray()
            exchange.sendResponseHeaders(200, body.size.toLong())
            exchange.responseBody.use { it.write(body) }
        }
        server.start()
        try {
            val operation = Telemetry.start("photo_post")
            val client = ApiClient("PRIVATE-token", "http://127.0.0.1:${server.address.port}/api/").tracked(operation)
            repeat(3) { client.request("posts/?query=PRIVATE") }
            assertEquals(listOf(operation.id, operation.id, operation.id), observedIds)
            assertEquals(1, records.count { it.first == "feature_used" })
            val attempts = records.filter { it.first == "api_result" }.map { it.second }
            assertEquals(listOf(1,2,3), attempts.map { it["attempt"] })
            assertEquals("server-request-3", attempts.last()["request_id"])
            assertTrue(attempts.all { it["result"] == "success" })
            assertFalse(records.toString().contains("PRIVATE"))
        } finally { server.stop(0) }
    }

    @Test fun failedHttpAndUnknownFieldsAreReportedSafely() {
        val records = mutableListOf<Map<String, Any>>()
        Telemetry.sink = { _, fields -> records.add(fields) }
        Telemetry.event("feature_stage", mapOf("stage" to "stt", "body" to "PRIVATE", "token" to "PRIVATE"))
        assertFalse(records.last().containsKey("body"))
        assertFalse(records.last().containsKey("token"))
        val server = HttpServer.create(InetSocketAddress("127.0.0.1",0),0)
        server.createContext("/api/posts/") { exchange ->
            val body = "{\"error\":\"PRIVATE message\"}".toByteArray()
            exchange.sendResponseHeaders(503, body.size.toLong())
            exchange.responseBody.use { it.write(body) }
        }
        server.start()
        try {
            val client = ApiClient(baseUrl="http://127.0.0.1:${server.address.port}/api/")
            assertThrows(ApiException::class.java) { client.request("posts/") }
            assertEquals("error", records.last()["result"])
            assertEquals(503, records.last()["http_status"])
            assertFalse(records.toString().contains("PRIVATE"))
        } finally { server.stop(0) }
    }
}
