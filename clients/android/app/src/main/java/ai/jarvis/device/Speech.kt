package ai.jarvis.device

import android.content.Context
import android.media.AudioAttributes
import android.media.MediaPlayer
import android.os.Handler
import android.os.Looper
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import java.io.File
import java.util.Locale

/** Произнести ответ: голос Джарвиса с сервера (WAV), иначе системный синтез Android. */
object Speech {
    /** Пока Джарвис говорит, микрофон не слушаем — чтобы он не услышал сам себя. */
    @Volatile var speaking = false
    private var tts: TextToSpeech? = null

    fun speak(ctx: Context, text: String, audioB64: String?) {
        speaking = true
        // Страховка: если звук не начался, микрофон всё равно откроется через время, оценённое по длине текста.
        Handler(Looper.getMainLooper()).postDelayed({ speaking = false }, maxOf(3000L, text.length * 90L + 3000L))
        if (!audioB64.isNullOrEmpty()) {
            try {
                val bytes = android.util.Base64.decode(audioB64, android.util.Base64.DEFAULT)
                val f = File.createTempFile("jarvis", ".wav", ctx.cacheDir).apply { writeBytes(bytes) }
                MediaPlayer().apply {
                    setAudioAttributes(AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_ASSISTANT)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
                    setDataSource(f.absolutePath)
                    setOnCompletionListener { speaking = false; release(); f.delete() }
                    prepare()
                    start()
                }
                return
            } catch (_: Exception) {}
        }
        val engine = tts ?: TextToSpeech(ctx) { status ->
            if (status == TextToSpeech.SUCCESS) {
                tts?.language = Locale("ru")
                tts?.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
                    override fun onStart(id: String?) {}
                    override fun onDone(id: String?) { speaking = false }
                    override fun onError(id: String?) { speaking = false }
                })
            }
        }.also { tts = it }
        engine.speak(text, TextToSpeech.QUEUE_FLUSH, null, "jarvis")
    }
}
