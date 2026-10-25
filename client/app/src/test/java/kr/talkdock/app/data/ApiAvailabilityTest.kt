package kr.talkdock.app.data

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.io.File
import java.io.InterruptedIOException
import java.net.ServerSocket

/** Real loopback HTTP; no deployed server, account, or external AI calls. */
class ApiAvailabilityTest {
    private class Server(val status: Int, val body: String, val delayMillis: Long = 0) : AutoCloseable {
        private val socket = ServerSocket(0)
        val base = "http://127.0.0.1:${socket.localPort}/api/"
        private val worker = Thread {
            runCatching {
                socket.accept().use { client ->
                    client.soTimeout = 2000
                    val reader = client.getInputStream().bufferedReader()
                    reader.readLine()
                    var length = 0
                    while (true) {
                        val line = reader.readLine() ?: break
                        if (line.isEmpty()) break
                        if (line.startsWith("Content-Length:", true)) length = line.substringAfter(':').trim().toInt()
                    }
                    repeat(length) { reader.read() }
                    if (delayMillis > 0) Thread.sleep(delayMillis)
                    val bytes = body.toByteArray(Charsets.UTF_8)
                    client.getOutputStream().apply {
                        write("HTTP/1.1 $status Test\r\nContent-Length: ${bytes.size}\r\nConnection: close\r\n\r\n".toByteArray())
                        write(bytes); flush()
                    }
                }
            }
        }.apply { isDaemon = true; start() }
        override fun close() { socket.close(); worker.join(3000) }
    }

    @Test fun htmlServerFailuresShowUnavailableNoticeInsteadOfParseError() {
        for (status in listOf(500, 502, 503, 504)) Server(status, "<html>Maintenance</html>").use { server ->
            val error = assertThrows(ApiException::class.java) { ApiClient(baseUrl = server.base).request("posts/") }
            assertEquals(status, error.status)
            assertEquals(ApiFailureMessages.UNAVAILABLE, error.message)
        }
    }

    @Test fun emptyAndUnstructuredMaintenanceResponsesHaveTheSameNotice() {
        for (body in listOf("", "{}", "{\"error\":\"\"}", "{\"error\":null}")) Server(503, body).use { server ->
            val error = assertThrows(ApiException::class.java) { ApiClient(baseUrl = server.base).request("posts/") }
            assertEquals(503, error.status)
            assertEquals(ApiFailureMessages.UNAVAILABLE, error.message)
        }
    }

    @Test fun usefulApplicationErrorsAndAuthenticationStatusArePreserved() {
        for (status in listOf(400, 401, 409, 503)) Server(status, "{\"error\":\"구체적인 안내\"}").use { server ->
            val error = assertThrows(ApiException::class.java) { ApiClient(baseUrl = server.base).request("posts/") }
            assertEquals(status, error.status)
            assertEquals("구체적인 안내", error.message)
        }
    }

    @Test fun malformedUnauthorizedResponseKeeps401AndLoginNotice() {
        Server(401, "Unauthorized").use { server ->
            val error = assertThrows(ApiException::class.java) { ApiClient(baseUrl = server.base).request("posts/") }
            assertEquals(401, error.status)
            assertEquals(ApiFailureMessages.http(401), error.message)
        }
    }

    @Test fun successfulJsonIsUnchanged() {
        Server(200, "{\"text\":\"가족 소식\"}").use { server ->
            assertEquals("가족 소식", ApiClient(baseUrl = server.base).request("posts/").getString("text"))
        }
    }

    @Test fun malformedSuccessIsNotMislabelledAsMaintenance() {
        Server(200, "not-json").use { server ->
            val error = assertThrows(ApiException::class.java) { ApiClient(baseUrl = server.base).request("posts/") }
            assertEquals(200, error.status)
            assertTrue(error.message!!.contains("서버 응답을 읽지 못했어요"))
        }
    }

    @Test fun refusedConnectionShowsConnectionNoticeWithoutLoggingOut() {
        val port = ServerSocket(0).use { it.localPort }
        val client = ApiClient("saved-token", "http://127.0.0.1:$port/api/")
        val error = assertThrows(ApiException::class.java) { client.request("posts/") }
        assertEquals(0, error.status)
        assertEquals(ApiFailureMessages.CONNECTION, error.message)
        assertEquals("saved-token", client.token)
    }

    @Test fun slowResponseShowsTimeoutNotice() {
        Server(200, "{}", 300).use { server ->
            val error = assertThrows(ApiException::class.java) {
                ApiClient(baseUrl = server.base).request("posts/", readTimeoutMillis = 50)
            }
            assertEquals(ApiFailureMessages.TIMEOUT, error.message)
            assertEquals(0, error.status)
        }
    }

    @Test fun photoUploadUsesTheMaintenanceNotice() {
        val photo = File.createTempFile("availability-", ".jpg").apply { writeText("photo") }
        try {
            Server(503, "<html>Maintenance</html>").use { server ->
                val error = assertThrows(ApiException::class.java) {
                    ApiClient(baseUrl = server.base).uploadPost(listOf(photo), "draft")
                }
                assertEquals(ApiFailureMessages.UNAVAILABLE, error.message)
            }
        } finally { photo.delete() }
    }

    @Test fun speechAndImageFailuresUseTheMaintenanceNotice() {
        Server(503, "<html>Maintenance</html>").use { server ->
            val error = assertThrows(ApiException::class.java) { ApiClient(baseUrl = server.base).speech("hello") }
            assertEquals(ApiFailureMessages.UNAVAILABLE, error.message)
        }
        Server(503, "unavailable").use { server ->
            val error = assertThrows(ApiException::class.java) { ApiClient(baseUrl = server.base).image(server.base + "photo/") }
            assertEquals(503, error.status)
            assertEquals(ApiFailureMessages.UNAVAILABLE, error.message)
        }
    }

    @Test fun cancelledRequestIsNotReportedAsAnOutage() {
        val cancellation = RequestCancellation().apply { cancel() }
        assertThrows(InterruptedIOException::class.java) {
            ApiClient(baseUrl = "http://127.0.0.1:1/api/").request("posts/", cancellation = cancellation)
        }
    }
}
