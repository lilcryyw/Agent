package ai.jarvis.device

import android.content.Context
import android.media.AudioAttributes
import android.media.MediaPlayer
import android.speech.tts.TextToSpeech
import java.io.File
import java.util.Locale

/** Произнести ответ: голос Джарвиса с сервера (WAV), иначе системный синтез Android. */
object Speech {
    private var tts: TextToSpeech? = null

    fun speak(ctx: Context, text: String, audioB64: String?) {
        if (!audioB64.isNullOrEmpty()) {
            try {
                val bytes = android.util.Base64.decode(audioB64, android.util.Base64.DEFAULT)
                val f = File.createTempFile("jarvis", ".wav", ctx.cacheDir).apply { writeBytes(bytes) }
                MediaPlayer().apply {
                    setAudioAttributes(AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_ASSISTANT)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
                    setDataSource(f.absolutePath); prepare(); start()
                    setOnCompletionListener { release(); f.delete() }
                }
                return
            } catch (_: Exception) {}
        }
        if (tts == null) tts = TextToSpeech(ctx) { if (it == TextToSpeech.SUCCESS) tts?.language = Locale("ru") }
        tts?.speak(text, TextToSpeech.QUEUE_FLUSH, null, "jarvis")
    }
}
