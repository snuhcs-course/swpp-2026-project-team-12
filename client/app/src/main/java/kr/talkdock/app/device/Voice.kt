package kr.talkdock.app.device

import android.content.Context
import kr.talkdock.app.data.Telemetry
import android.media.MediaPlayer
import android.media.MediaRecorder
import java.io.File

/** Playback uses server-generated ElevenLabs audio. */
class Speaker(private val error: (String) -> Unit) {
    private var player: MediaPlayer? = null
    private var operation: Telemetry.Operation? = null
    var nextOperation: Telemetry.Operation? = null
    private var file: File? = null
    fun play(audio: File, completed: () -> Unit = {}, failed: ((String) -> Unit)? = null) {
        stop()
        file = audio
        operation = nextOperation ?: Telemetry.start("read_aloud"); nextOperation = null
        try {
            val engine = MediaPlayer()
            player = engine
            engine.apply {
                setDataSource(audio.absolutePath)
                setOnPreparedListener { if (player === it) { it.start(); operation?.stage("playback_started") } }
                setOnCompletionListener { if (player === it) { operation?.stage("playback_completed"); operation = null; stop(); completed() } }
                setOnErrorListener { source, _, _ ->
                    if (player === source) { operation?.stage("playback_failed", "error"); operation = null; stop(); (failed ?: error)("소리를 재생하지 못했어요. 다시 시도해 주세요.") }
                    true
                }
                prepareAsync()
            }
        } catch (_: Exception) { operation?.stage("playback_failed", "error"); operation = null; stop(); (failed ?: error)("소리를 재생하지 못했어요. 다시 시도해 주세요.") }
    }
    fun stop() {
        operation?.stage("playback_stopped", "cancelled"); operation = null
        val previous = player
        player = null
        previous?.setOnPreparedListener(null)
        previous?.setOnCompletionListener(null)
        previous?.setOnErrorListener(null)
        previous?.release()
        file?.delete(); file = null
    }
    fun close() = stop()
}

/** Recording is sent only when the user explicitly finishes speaking. */
class Recorder(private val context: Context, private val feature: String = "voice_reply", private val limit: () -> Unit) {
    private var engine: MediaRecorder? = null
    private var file: File? = null
    var operation: Telemetry.Operation? = null
        private set
    var active = false
        private set
    private var recordingStarted = 0L
    @Suppress("DEPRECATION")
    fun start(existing: Telemetry.Operation? = null) {
        cancel()
        operation = existing ?: Telemetry.start(feature)
        recordingStarted = System.nanoTime()
        operation?.stage("recording_started")
        val output = File.createTempFile("reply-", ".m4a", context.cacheDir)
        file = output
        try {
            val recorder = if (android.os.Build.VERSION.SDK_INT >= 31) MediaRecorder(context) else MediaRecorder()
            engine = recorder
            recorder.apply {
                setAudioSource(MediaRecorder.AudioSource.MIC)
                setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
                setAudioEncoder(MediaRecorder.AudioEncoder.AAC)
                setAudioChannels(1); setAudioSamplingRate(16000); setAudioEncodingBitRate(64000)
                setMaxDuration(60_000); setOutputFile(output.absolutePath)
                setOnInfoListener { _, what, _ -> if (what == MediaRecorder.MEDIA_RECORDER_INFO_MAX_DURATION_REACHED) limit() }
                prepare(); start()
            }
            active = true
        } catch (error: Exception) { cancel(); throw error }
    }
    fun finish(): File {
        val output = file ?: throw IllegalStateException("No recording")
        try {
            engine?.stop()
            if (output.length() < 100) throw IllegalStateException("Recording too short")
            file = null
            operation?.stage("recording_completed", durationMs = (System.nanoTime() - recordingStarted) / 1_000_000, fields = mapOf("bytes" to output.length()))
            return output
        } catch (error: Exception) { output.delete(); file = null; throw error }
        finally { engine?.release(); engine = null; active = false }
    }
    fun cancel() { engine?.release(); engine = null; active = false; file?.delete(); file = null }
    fun close() = cancel()
}
