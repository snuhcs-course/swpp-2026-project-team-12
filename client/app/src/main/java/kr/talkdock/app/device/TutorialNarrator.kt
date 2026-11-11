package kr.talkdock.app.device

import android.content.Context
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioManager
import android.media.MediaDataSource
import android.media.MediaPlayer
import android.os.Handler
import android.os.Looper
import android.view.accessibility.AccessibilityManager
import kr.talkdock.app.R
import kr.talkdock.app.data.ApiClient
import kr.talkdock.app.data.RequestCancellation
import java.util.concurrent.Executors

enum class TutorialLine(val description: String, val spokenText: String, val clip: Int) {
    READ("안내: 소식 보기", "가족이 올린 소식이에요. 게시글을 눌러 읽어 보세요.", R.raw.guide_read_post),
    BACK("안내: 소식 목록으로 돌아가기", "다 읽으셨으면 왼쪽 위 화살표를 눌러 돌아가세요.", R.raw.guide_back),
    COMPOSE("안내: 소식 쓰기", "아래에 있는 소식 쓰기를 눌러 보세요.", R.raw.guide_compose),
    WRITE("안내: 소식 입력", "오늘 있었던 일을 여기에 적어 보세요.", R.raw.guide_write),
    REPLY("안내: 가족 글에 답장하기", "가족의 새 소식이에요. 이 글을 눌러 답장해 보세요.", R.raw.guide_reply_post),
    COMMENT("안내: 댓글 입력", "가족에게 하고 싶은 말씀을 여기에 적어 보세요.", R.raw.guide_comment),
    SEND_COMMENT("안내: 댓글 보내기", "댓글을 보내려면 오른쪽 화살표를 눌러 주세요.", R.raw.guide_send_comment),
    SEND_VOICE("안내: 가족에게 보내기", "내용을 확인하셨으면 가족에게 보내기를 누르세요.", R.raw.guide_send_voice)
}

/** The server resolves the signed-in listener's voice. Bundled clips keep the guide audible offline. */
class TutorialNarrator(
    private val context: Context,
    private val currentClient: () -> ApiClient,
    private val canPlay: () -> Boolean,
) {
    private val worker = Executors.newSingleThreadExecutor()
    private var pending: RequestCancellation? = null
    private val prefs = context.getSharedPreferences("tutorial-audio", Context.MODE_PRIVATE)
    private val access = context.getSystemService(AccessibilityManager::class.java)
    private val audio = context.getSystemService(AudioManager::class.java)
    private val handler = Handler(Looper.getMainLooper())
    private val attributes = AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA)
        .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build()
    private var player: MediaPlayer? = null
    private var focus: AudioFocusRequest? = null
    private var current: TutorialLine? = null
    private var announced = false
    private val playPending = Runnable { playCurrent() }

    val enabled get() = prefs.getBoolean("enabled", !access.isTouchExplorationEnabled)

    fun toggle() {
        val turnOn = !enabled
        prefs.edit().putBoolean("enabled", turnOn).apply()
        interrupt()
        if (turnOn) {
            announced = false
            playCurrent()
        }
    }

    fun present(line: TutorialLine) {
        if (line != current) {
            clear()
            current = line
            announced = false
        }
        if (!enabled || announced) return
        handler.removeCallbacks(playPending)
        // Let the keyboard settle; announce Send only after the user pauses typing.
        handler.postDelayed(playPending, if (line == TutorialLine.SEND_COMMENT) 1200L else 200L)
    }

    fun interrupt() {
        handler.removeCallbacks(playPending)
        announced = true
        val cancelled = pending
        pending = null
        cancelled?.cancel()
        releasePlayer()
        focus?.let(audio::abandonAudioFocusRequest)
        focus = null
    }

    fun clear() {
        interrupt()
        current = null
    }

    fun close() {
        clear()
        worker.shutdownNow()
    }

    private fun releasePlayer() {
        player?.release()
        player = null
    }

    private fun playCurrent() {
        val line = current ?: return
        announced = true
        if (!enabled || !canPlay()) return
        val client = currentClient()
        val request = RequestCancellation()
        pending = request
        worker.execute {
            val bytes = try {
                client.speech(line.spokenText, request, timeoutMillis = 8_000)
            } catch (_: Exception) { null }
            handler.post {
                if (pending !== request) return@post
                pending = null
                if (enabled && canPlay()) prepare(line, bytes)
            }
        }
    }

    private fun prepare(line: TutorialLine, bytes: ByteArray?) {
        val clip = MediaPlayer()
        player = clip
        fun failed() {
            if (player !== clip) return
            releasePlayer()
            if (bytes != null && enabled && canPlay()) prepare(line, null) else interrupt()
        }
        try {
            clip.setAudioAttributes(attributes)
            if (bytes != null) clip.setDataSource(GuideAudio(bytes))
            else context.resources.openRawResourceFd(line.clip).use { file ->
                clip.setDataSource(file.fileDescriptor, file.startOffset, file.length)
            }
            clip.setOnPreparedListener {
                if (player === clip) {
                    if (enabled && canPlay() && requestFocus()) clip.start() else interrupt()
                }
            }
            clip.setOnCompletionListener { if (player === it) interrupt() }
            clip.setOnErrorListener { _, _, _ -> failed(); true }
            clip.prepareAsync()
        } catch (_: Exception) {
            failed()
        }
    }

    private fun requestFocus(): Boolean {
        lateinit var request: AudioFocusRequest
        request = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK)
            .setAudioAttributes(attributes)
            .setOnAudioFocusChangeListener({ change ->
                if (focus === request && change < 0) interrupt()
            }, handler).build()
        if (audio.requestAudioFocus(request) != AudioManager.AUDIOFOCUS_REQUEST_GRANTED) return false
        focus = request
        return true
    }
}

/** MediaPlayer reads the short response directly, without writing account audio to disk. */
private class GuideAudio(private val bytes: ByteArray) : MediaDataSource() {
    override fun getSize(): Long = bytes.size.toLong()
    override fun readAt(position: Long, buffer: ByteArray, offset: Int, size: Int): Int {
        if (size == 0) return 0
        if (position < 0 || position >= bytes.size) return -1
        val start = position.toInt()
        val count = minOf(size, bytes.size - start)
        bytes.copyInto(buffer, offset, start, start + count)
        return count
    }
    override fun close() = Unit
}
