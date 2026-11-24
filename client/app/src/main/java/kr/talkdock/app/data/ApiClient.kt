package kr.talkdock.app.data

import kr.talkdock.app.BuildConfig
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.nio.charset.StandardCharsets
import java.io.InterruptedIOException
import java.io.IOException
import java.io.FileNotFoundException
import java.io.OutputStream
import java.net.SocketTimeoutException

class ApiException(message: String, val status: Int = 0, cause: Throwable? = null,
                   val isMaintenance: Boolean = false, val field: String? = null) : Exception(message, cause)

/** A single request's connection, so leaving a slow AI screen also releases its worker. */
class RequestCancellation {
    private var cancelled = false
    private var connection: HttpURLConnection? = null

    @Synchronized fun attach(value: HttpURLConnection) {
        if (cancelled) throw InterruptedIOException("Request cancelled")
        connection = value
    }
    @Synchronized fun release(value: HttpURLConnection) {
        if (connection === value) connection = null
    }
    fun cancel() {
        val active = synchronized(this) {
            cancelled = true
            connection.also { connection = null }
        }
        active?.disconnect()
    }
}

/** [roomId] picks the family room for room-scoped endpoints such as the feed and digests. */
class ApiClient(var token: String = "", val baseUrl: String = BuildConfig.API_URL, val roomId: Int? = null,
                private val onMaintenance: (() -> Unit)? = null) {
    fun request(path: String, method: String = "GET", data: JSONObject? = null,
                readTimeoutMillis: Int = 80_000, cancellation: RequestCancellation? = null): JSONObject {
        val connection = open(baseUrl + path, method)
        try {
            connection.readTimeout = readTimeoutMillis
            cancellation?.attach(connection)
            if (data != null) {
                connection.doOutput = true
                connection.setRequestProperty("Content-Type", "application/json; charset=utf-8")
                connection.outputStream.use { it.write(data.toString().toByteArray(StandardCharsets.UTF_8)) }
            }
            return response(connection)
        } catch (error: IOException) { throw networkFailure(error) }
        finally { cancellation?.release(connection); connection.disconnect() }
    }

    fun searchHistory(question: String, cancellation: RequestCancellation): MemorySearchResult {
        val response = request("searching/history/", "POST", JSONObject().put("question", question.trim()),
            readTimeoutMillis = 150_000, cancellation = cancellation)
        val result = MemorySearchResult.fromJson(response)
        if (response.has("evidence_posts")) return result
        // Older servers already return source episode names. Use only those IDs,
        // never URLs/text invented by the answer. Every fetch is authenticated.
        val posts = mutableListOf<JSONObject>()
        var unavailable = false
        val started = System.nanoTime()
        for (id in MemorySearchResult.legacyPostIds(response)) {
            if ((System.nanoTime() - started) / 1_000_000_000 >= 30) { unavailable = true; break }
            try {
                val post = request("posts/$id/", readTimeoutMillis = 10_000, cancellation = cancellation)
                if (post.optInt("id") == id) posts.add(post) else unavailable = true
            } catch (error: Exception) {
                if (error is InterruptedIOException && error !is SocketTimeoutException) throw error
                if (error is ApiException && error.status == 401) throw error
                if (error !is ApiException || error.status !in listOf(403, 404)) unavailable = true
            }
        }
        val normalized = MemorySearchResult.fromJson(result.copy(posts = posts,
            cited = response.has("source_episode_ids"), unavailable = unavailable).toJson())
        return normalized.copy(unavailable = unavailable || normalized.posts.size != posts.size)
    }

    fun upload(photo: File, caption: String): JSONObject {
        return multipart("posts/", "image", "photo.jpg", "image/jpeg", photo, mapOf("caption" to caption))
    }

    fun uploadPost(photos: List<File>, caption: String, onProgress: ((Int) -> Unit)? = null): JSONObject =
        multipartParts("posts/",
            photos.mapIndexed { index, file -> UploadPart("images", "photo-$index.jpg", "image/jpeg", file) },
            mapOf("caption" to caption), onProgress)

    fun transcribe(postId: Int, audio: File): JSONObject =
        multipart("posts/$postId/replies/transcribe/", "audio", "recording.m4a", "audio/mp4", audio, emptyMap())

    fun transcribePost(audio: File): JSONObject =
        multipart("speech/transcribe/", "audio", "recording.m4a", "audio/mp4", audio, emptyMap())

    private fun multipart(path: String, field: String, filename: String, type: String, file: File, values: Map<String, String>): JSONObject {
        return multipartParts(path, listOf(UploadPart(field, filename, type, file)), values)
    }

    private data class UploadPart(val field: String, val filename: String, val type: String, val file: File)

    private fun multipartParts(path: String, files: List<UploadPart>, values: Map<String, String>,
                               onProgress: ((Int) -> Unit)? = null): JSONObject {
        val boundary = "TalkDock" + java.util.UUID.randomUUID().toString().replace("-", "")
        val connection = open(baseUrl + path, "POST")
        connection.doOutput = true
        val fields = values.entries.joinToString("") { (key, value) -> "--$boundary\r\nContent-Disposition: form-data; name=\"$key\"\r\n\r\n$value\r\n" }
        val fieldBytes = fields.toByteArray(StandardCharsets.UTF_8)
        val prefixes = files.map { part ->
            "--$boundary\r\nContent-Disposition: form-data; name=\"${part.field}\"; filename=\"${part.filename}\"\r\nContent-Type: ${part.type}\r\n\r\n".toByteArray(StandardCharsets.UTF_8)
        }
        val suffix = "--$boundary--\r\n".toByteArray(StandardCharsets.UTF_8)
        val length = fieldBytes.size.toLong() + suffix.size + files.indices.sumOf { prefixes[it].size.toLong() + files[it].file.length() + 2 }
        connection.setFixedLengthStreamingMode(length)
        connection.setRequestProperty("Content-Type", "multipart/form-data; boundary=" + boundary)
        try {
            val output = connection.outputStream
            val tracked = if (onProgress == null) output else object : OutputStream() {
                private var bytesSent = 0L
                private var lastProgress = 0

                override fun write(value: Int) {
                    output.write(value)
                    report(1)
                }

                override fun write(bytes: ByteArray, offset: Int, count: Int) {
                    output.write(bytes, offset, count)
                    report(count)
                }

                private fun report(count: Int) {
                    bytesSent += count
                    val percent = (bytesSent * 100 / length).toInt().coerceAtMost(99)
                    if (percent != lastProgress) {
                        lastProgress = percent
                        onProgress(percent)
                    }
                }

                override fun flush() = output.flush()
                override fun close() = output.close()
            }
            tracked.buffered().use { stream ->
                stream.write(fieldBytes)
                files.forEachIndexed { index, part ->
                    stream.write(prefixes[index])
                    part.file.inputStream().use { it.copyTo(stream) }
                    stream.write("\r\n".toByteArray(StandardCharsets.UTF_8))
                }
                stream.write(suffix)
            }
            onProgress?.invoke(100)
            return response(connection)
        } catch (error: IOException) { throw networkFailure(error) }
        finally { connection.disconnect() }
    }

    fun speech(text: String, cancellation: RequestCancellation? = null, timeoutMillis: Int? = null): ByteArray {
        val connection = open(baseUrl + "speech/", "POST")
        try {
            cancellation?.attach(connection)
            if (timeoutMillis != null) {
                connection.connectTimeout = timeoutMillis
                connection.readTimeout = timeoutMillis
            }
            connection.doOutput = true
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8")
            connection.outputStream.use { it.write(JSONObject().put("text", text).toString().toByteArray(StandardCharsets.UTF_8)) }
            if (connection.responseCode !in 200..299) response(connection)
            // Only audio is handed to the player: decoding other data can stall MediaPlayer and,
            // through release(), the main thread. The server always answers with audio/mpeg.
            if (connection.contentType?.lowercase()?.startsWith("audio/") != true)
                throw ApiException("음성을 준비하지 못했어요. 다시 시도해 주세요.", connection.responseCode)
            return connection.inputStream.use { it.readBytes() }
        } catch (error: IOException) { throw networkFailure(error) }
        finally { cancellation?.release(connection); connection.disconnect() }
    }

    fun maintenanceMessage(): String {
        val connection = open(URL(URL(baseUrl), "/maintenance/message.txt").toString(), "GET")
        connection.useCaches = false
        connection.readTimeout = 10_000
        try {
            if (connection.responseCode != 200) return ""
            return connection.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText() }
                .removePrefix("\uFEFF").trim()
        } finally { connection.disconnect() }
    }

    fun voiceSample(key: String): ByteArray {
        val connection = open(baseUrl + "speech/voices/" + URLEncoder.encode(key, "UTF-8") + "/sample/", "GET")
        try {
            if (connection.responseCode !in 200..299) response(connection)
            return connection.inputStream.use { it.readBytes() }
        } catch (error: IOException) { throw networkFailure(error) }
        finally { connection.disconnect() }
    }

    fun image(url: String): ByteArray {
        val connection = open(url, "GET")
        try {
            val status = connection.responseCode
            if (status == 503) response(connection)
            if (status != 200) throw ApiException(
                if (status in 500..599) ApiFailureMessages.UNAVAILABLE else "사진을 불러오지 못했어요.", status)
            return connection.inputStream.use { it.readBytes() }
        } catch (error: IOException) { throw networkFailure(error) }
        finally { connection.disconnect() }
    }

    private fun open(url: String, method: String): HttpURLConnection {
        val connection = URL(url).openConnection() as HttpURLConnection
        connection.requestMethod = method
        connection.connectTimeout = 10_000
        connection.readTimeout = 80_000
        if (token.isNotEmpty()) connection.setRequestProperty("Authorization", "Bearer " + token)
        if (roomId != null) connection.setRequestProperty("X-Family-Room", roomId.toString())
        return connection
    }

    private fun response(connection: HttpURLConnection): JSONObject {
        val code = connection.responseCode
        val stream = if (code in 200..299) connection.inputStream else connection.errorStream
        val raw = stream?.bufferedReader()?.use { it.readText() } ?: "{}"
        val json = runCatching { JSONObject(raw) }.getOrNull()
        if (code !in 200..299) {
            // Keep application-specific JSON errors (validation, AI availability, etc.).
            // Maintenance proxies often return HTML or an empty body instead of JSON.
            val message = json?.optString("error")?.takeIf { it.isNotBlank() && it != "null" }
            val maintenance = code == 503 && json?.optString("code") == "maintenance"
            if (maintenance) onMaintenance?.invoke()
            throw ApiException(message ?: ApiFailureMessages.http(code), code, isMaintenance = maintenance, field = json?.optString("field")?.takeIf { it.isNotBlank() })
        }
        return json ?: throw ApiException("서버 응답을 읽지 못했어요. 잠시 후 다시 시도해 주세요.", code)
    }

    private fun networkFailure(error: IOException): Exception = when (error) {
        is SocketTimeoutException -> ApiException(ApiFailureMessages.TIMEOUT, cause = error)
        // Navigation cancellation and local file access are not server outages.
        is InterruptedIOException, is FileNotFoundException -> error
        else -> ApiException(ApiFailureMessages.CONNECTION, cause = error)
    }
}
