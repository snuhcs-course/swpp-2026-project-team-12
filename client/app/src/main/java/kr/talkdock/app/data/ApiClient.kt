package kr.talkdock.app.data

import kr.talkdock.app.BuildConfig
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.nio.charset.StandardCharsets
import java.io.InterruptedIOException

class ApiException(message: String, val status: Int = 0) : Exception(message)

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
class ApiClient(var token: String = "", val baseUrl: String = BuildConfig.API_URL, val roomId: Int? = null) {
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
        } finally { cancellation?.release(connection); connection.disconnect() }
    }

    fun searchHistory(question: String, cancellation: RequestCancellation): String {
        val text = request("searching/history/", "POST", JSONObject().put("question", question.trim()),
            readTimeoutMillis = 150_000, cancellation = cancellation).getString("text")
        if (text.isBlank()) throw ApiException("추억을 찾지 못했어요. 잠시 후 다시 시도해 주세요.")
        return text
    }

    fun upload(photo: File, caption: String): JSONObject {
        return multipart("posts/", "image", "photo.jpg", "image/jpeg", photo, mapOf("caption" to caption))
    }

    fun uploadPost(photos: List<File>, caption: String): JSONObject =
        multipartParts("posts/",
            photos.mapIndexed { index, file -> UploadPart("images", "photo-$index.jpg", "image/jpeg", file) },
            mapOf("caption" to caption))

    fun transcribe(postId: Int, audio: File): JSONObject =
        multipart("posts/$postId/replies/transcribe/", "audio", "recording.m4a", "audio/mp4", audio, emptyMap())

    private fun multipart(path: String, field: String, filename: String, type: String, file: File, values: Map<String, String>): JSONObject {
        return multipartParts(path, listOf(UploadPart(field, filename, type, file)), values)
    }

    private data class UploadPart(val field: String, val filename: String, val type: String, val file: File)

    private fun multipartParts(path: String, files: List<UploadPart>, values: Map<String, String>): JSONObject {
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
            connection.outputStream.buffered().use { stream ->
                stream.write(fieldBytes)
                files.forEachIndexed { index, part ->
                    stream.write(prefixes[index])
                    part.file.inputStream().use { it.copyTo(stream) }
                    stream.write("\r\n".toByteArray(StandardCharsets.UTF_8))
                }
                stream.write(suffix)
            }
            return response(connection)
        } finally { connection.disconnect() }
    }

    fun speech(text: String): ByteArray {
        val connection = open(baseUrl + "speech/", "POST")
        try {
            connection.doOutput = true
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8")
            connection.outputStream.use { it.write(JSONObject().put("text", text).toString().toByteArray(StandardCharsets.UTF_8)) }
            if (connection.responseCode !in 200..299) response(connection)
            return connection.inputStream.use { it.readBytes() }
        } finally { connection.disconnect() }
    }

    fun image(url: String): ByteArray {
        val connection = open(url, "GET")
        try {
            if (connection.responseCode != 200) throw ApiException("사진을 불러오지 못했어요.")
            return connection.inputStream.use { it.readBytes() }
        } finally { connection.disconnect() }
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
        val json = runCatching { JSONObject(raw) }.getOrElse {
            throw ApiException("서버 응답을 읽지 못했어요. 잠시 후 다시 시도해 주세요.", code)
        }
        if (code !in 200..299) throw ApiException(json.optString("error", "가족 방에 연결하지 못했어요. 다시 시도해 주세요."), code)
        return json
    }
}
