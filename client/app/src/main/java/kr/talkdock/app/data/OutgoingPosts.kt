package kr.talkdock.app.data

import android.graphics.Bitmap
import android.os.Handler
import android.os.Looper
import androidx.lifecycle.ViewModel
import org.json.JSONObject
import java.io.File
import java.util.concurrent.Executors

internal data class PostingScope(val server: String, val userId: Int, val roomId: Int)

internal class OutgoingPosts : ViewModel() {
    enum class Kind { POST, TEXT_COMMENT, VOICE_REPLY }

    class Upload(
        val scope: PostingScope,
        val kind: Kind,
        val text: String,
        val postId: Int? = null,
        val thumbnail: Bitmap? = null,
        val files: List<File> = emptyList(),
        val send: (ApiClient, (Int) -> Unit) -> JSONObject
    ) {
        var running = false
            internal set
        var progress = 0
            internal set
        var error: Throwable? = null
            internal set
    }

    private val main = Handler(Looper.getMainLooper())
    private val worker = Executors.newFixedThreadPool(2)
    private val uploads = mutableListOf<Upload>()
    private val completed = mutableListOf<Pair<Upload, JSONObject>>()
    private var cleared = false
    var onChange: (() -> Unit)? = null

    fun inScope(scope: PostingScope) = uploads.filter { it.scope == scope }

    fun takeCompleted(): List<Pair<Upload, JSONObject>> =
        completed.toList().also { completed.clear() }

    fun submit(upload: Upload, client: ApiClient) {
        uploads.add(upload)
        retry(upload, client)
    }

    fun retry(upload: Upload, client: ApiClient) {
        if (upload !in uploads || upload.running) return
        upload.running = true
        upload.progress = 0
        upload.error = null
        onChange?.invoke()
        worker.execute {
            val result = runCatching {
                upload.send(client) { progress ->
                    main.post {
                        upload.progress = progress
                        onChange?.invoke()
                    }
                }
            }
            main.post {
                if (cleared || result.isSuccess) {
                    uploads.remove(upload)
                    upload.files.forEach { it.delete() }
                }
                if (!cleared) {
                    upload.running = false
                    result.fold({ completed.add(upload to it) }, { upload.error = it })
                    onChange?.invoke()
                }
            }
        }
    }

    fun takeFailed(upload: Upload): Boolean {
        if (upload.running || upload.error == null || !uploads.remove(upload)) return false
        onChange?.invoke()
        return true
    }

    fun dismiss(upload: Upload) {
        if (takeFailed(upload)) upload.files.forEach { it.delete() }
    }

    override fun onCleared() {
        cleared = true
        onChange = null
        uploads.filterNot { it.running }.forEach { upload -> upload.files.forEach { it.delete() } }
        uploads.clear()
        completed.clear()
        worker.shutdown()
    }
}
