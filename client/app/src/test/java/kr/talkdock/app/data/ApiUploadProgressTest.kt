package kr.talkdock.app.data

import com.sun.net.httpserver.HttpServer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.net.InetSocketAddress
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit.SECONDS
import java.util.concurrent.atomic.AtomicReference

class ApiUploadProgressTest {
    @get:Rule val files = TemporaryFolder()

    @Test fun countsTheWholeMultipartBodyAndReportsCompletionBeforeServerConfirmation() {
        val first = files.newFile("first.jpg").apply { writeText("a".repeat(16384)) }
        val second = files.newFile("second.jpg").apply { writeText("b".repeat(131072)) }
        val reportedComplete = CountDownLatch(1)
        val recordedBody = AtomicReference<Pair<Int, String>>()
        val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        server.createContext("/api/posts/") { exchange ->
            exchange.use {
                val body = exchange.requestBody.use { it.readBytes() }
                recordedBody.set(body.size to body.toString(Charsets.UTF_8))
                // Withhold the server response until the client finishes the request body.
                val response = """{"id":23}""".toByteArray()
                exchange.sendResponseHeaders(if (reportedComplete.await(5, SECONDS)) 201 else 500, response.size.toLong())
                exchange.responseBody.use { it.write(response) }
            }
        }
        server.start()
        try {
            val client = ApiClient(baseUrl = "http://127.0.0.1:${server.address.port}/api/")
            val progress = mutableListOf<Int>()
            val post = client.uploadPost(listOf(first, second), "가족 소식") {
                progress.add(it)
                if (it == 100) reportedComplete.countDown()
            }
            assertEquals(23, post.getInt("id"))
            assertEquals(100, progress.last())
            assertTrue(progress.first() in 1..99)
            assertTrue(progress.zipWithNext().all { (earlier, later) -> earlier < later })
            val (size, multipart) = recordedBody.get()
            assertTrue(size.toLong() > first.length() + second.length())
            assertTrue(multipart.contains("\r\n\r\n가족 소식\r\n"))
            assertTrue(multipart.contains("filename=\"photo-0.jpg\""))
            assertTrue(multipart.indexOf("filename=\"photo-0.jpg\"") < multipart.indexOf("filename=\"photo-1.jpg\""))
        } finally {
            server.stop(0)
        }
    }
}
