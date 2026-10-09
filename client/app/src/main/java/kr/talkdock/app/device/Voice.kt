package kr.talkdock.app.device

import android.content.Context
import android.media.MediaPlayer
import android.media.MediaRecorder
import java.io.File

/** Playback uses server-generated ElevenLabs audio. */
class Speaker(private val error: (String) -> Unit) {
    private var player: MediaPlayer? = null
    private var file: File? = null
    fun play(audio: File) {
        stop()
        file = audio
        try {
            val engine = MediaPlayer()
            player = engine
            engine.apply {
                setDataSource(audio.absolutePath)
                setOnPreparedListener { it.start() }
                setOnCompletionListener { stop() }
                setOnErrorListener { _, _, _ -> stop(); error("소리를 재생하지 못했어요. 다시 시도해 주세요."); true }
                prepareAsync()
            }
        } catch (_: Exception) { stop(); error("소리를 재생하지 못했어요. 다시 시도해 주세요.") }
    }
    fun stop() { player?.release(); player = null; file?.delete(); file = null }
    fun close() = stop()
}

/** Recording is sent only when the user explicitly finishes speaking. */
class Recorder(private val context: Context, private val limit: () -> Unit) {
    private var engine: MediaRecorder? = null
    private var file: File? = null
    var active = false
        private set
    @Suppress("DEPRECATION")
    fun start() {
        cancel()
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
            return output
        } catch (error: Exception) { output.delete(); file = null; throw error }
        finally { engine?.release(); engine = null; active = false }
    }
    fun cancel() { engine?.release(); engine = null; active = false; file?.delete(); file = null }
    fun close() = cancel()
}
