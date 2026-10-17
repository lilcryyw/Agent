package ai.jarvis.device

import android.content.Context
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioRecord
import android.media.MediaRecorder
import android.media.ToneGenerator
import org.json.JSONObject
import org.vosk.Model
import org.vosk.Recognizer
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.FileOutputStream
import java.net.URL
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.zip.ZipInputStream
import kotlin.math.sqrt

/**
 * Слушает слово «Джарвис» офлайн. Работает внутри фоновой службы, поэтому — даже когда приложение закрыто.
 * Два этапа, как на ПК: быстрый поиск слова по узкой грамматике, затем проверка полной моделью
 * последних двух секунд — чтобы «жарко» или «джинсы» не запускали ассистента.
 * После подтверждения записывает фразу до паузы и отдаёт WAV серверу.
 */
class VoiceListener(
    private val ctx: Context,
    private val log: (String) -> Unit,
    private val onUtterance: (ByteArray) -> Unit,
) {
    @Volatile private var running = false
    private var thread: Thread? = null

    fun start() {
        if (running) return
        running = true
        thread = Thread({ loop() }, "jarvis-voice").apply { isDaemon = true; start() }
    }

    fun stop() { running = false }

    private fun modelDir() = File(ctx.filesDir, "vosk-ru")

    /** Модель распознавания русского (~45 МБ) скачивается один раз и хранится в памяти приложения. */
    private fun ensureModel(): Model? {
        val dir = modelDir()
        if (!File(dir, "am").exists()) {
            log("скачиваю модель голоса (~45 МБ, один раз)…")
            val zip = File(ctx.filesDir, "vosk.zip")
            URL(MODEL_URL).openStream().use { input -> FileOutputStream(zip).use { input.copyTo(it) } }
            ZipInputStream(zip.inputStream()).use { zin ->
                generateSequence { zin.nextEntry }.forEach { e ->
                    val out = File(ctx.filesDir, e.name)
                    if (e.isDirectory) out.mkdirs() else {
                        out.parentFile?.mkdirs()
                        FileOutputStream(out).use { zin.copyTo(it) }
                    }
                }
            }
            zip.delete()
            File(ctx.filesDir, "vosk-model-small-ru-0.22").renameTo(dir)
        }
        return if (File(dir, "am").exists()) Model(dir.absolutePath) else null
    }

    private fun loop() {
        try {
            val model = ensureModel() ?: run { log("модель голоса не найдена"); running = false; return }
            log("слушаю слово «Джарвис»")
            val spot = Recognizer(model, RATE.toFloat(), "[\"джарвис\", \"[unk]\"]")
            val bufSize = maxOf(AudioRecord.getMinBufferSize(RATE, AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT), 16000)
            val rec = AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION, RATE,
                AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, bufSize)
            rec.startRecording()
            val chunk = ByteArray(CHUNK)
            var recent = ByteArray(0)
            var noise = 300.0
            try {
                while (running) {
                    if (Speech.speaking) { spot.reset(); recent = ByteArray(0); Thread.sleep(100); continue }
                    val n = rec.read(chunk, 0, CHUNK)
                    if (n <= 0) continue
                    val merged = recent + chunk.copyOf(n)
                    recent = if (merged.size > RECENT) merged.copyOfRange(merged.size - RECENT, merged.size) else merged
                    val level = rms(chunk, n)
                    if (level < noise * 2.5 + 200) noise = 0.97 * noise + 0.03 * level
                    val hit = if (spot.acceptWaveForm(chunk, n)) hasWake(JSONObject(spot.result), "text")
                              else hasWake(JSONObject(spot.partialResult), "partial")
                    if (!hit) continue
                    spot.reset()
                    if (!confirmed(model, recent)) continue
                    beep()
                    val phrase = captureUtterance(rec, chunk, recent, noise)
                    if (phrase != null) onUtterance(wav(phrase))
                    recent = ByteArray(0)
                }
            } finally {
                rec.stop(); rec.release(); spot.close()
            }
        } catch (e: Exception) {
            log("голос остановлен: ${e.message}")
            running = false
        }
    }

    private fun hasWake(json: JSONObject, key: String) = json.optString(key).contains(WAKE)

    /** Полная модель перепроверяет последние 2 секунды: действительно ли сказано «Джарвис». */
    private fun confirmed(model: Model, pcm: ByteArray): Boolean {
        val full = Recognizer(model, RATE.toFloat())
        return try {
            full.setWords(true)
            full.acceptWaveForm(pcm, pcm.size)
            val words = JSONObject(full.finalResult).optJSONArray("result") ?: return false
            (0 until words.length()).any { i ->
                val w = words.getJSONObject(i)
                w.optString("word") in WAKE_FORMS && w.optDouble("conf", 0.0) > 0.5
            }
        } finally {
            full.close()
        }
    }

    /** Пишет фразу после пробуждения: до 1.5 с тишины после речи, не дольше 15 с. */
    private fun captureUtterance(rec: AudioRecord, chunk: ByteArray, head: ByteArray, noise: Double): ByteArray? {
        val out = ByteArrayOutputStream().apply { write(head) }
        val threshold = maxOf(300.0, noise * 2.5)
        var spoke = false
        var silent = 0
        var chunks = 0
        while (running && chunks < MAX_CHUNKS) {
            val n = rec.read(chunk, 0, CHUNK)
            if (n <= 0) continue
            out.write(chunk, 0, n)
            chunks++
            if (rms(chunk, n) > threshold) { spoke = true; silent = 0 } else silent++
            if (spoke && silent >= SILENCE_CHUNKS) break
            if (!spoke && chunks > 40) return null  // 5 с тишины — команды не было
        }
        return if (spoke) out.toByteArray() else null
    }

    private fun rms(b: ByteArray, n: Int): Double {
        var sum = 0.0
        var count = 0
        var i = 0
        while (i + 1 < n) {
            val s = ((b[i].toInt() and 0xff) or (b[i + 1].toInt() shl 8)).toShort().toDouble()
            sum += s * s
            count++
            i += 2
        }
        return if (count == 0) 0.0 else sqrt(sum / count)
    }

    private fun wav(pcm: ByteArray): ByteArray {
        val h = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN)
        h.put("RIFF".toByteArray()).putInt(36 + pcm.size).put("WAVE".toByteArray())
            .put("fmt ".toByteArray()).putInt(16).putShort(1).putShort(1).putInt(RATE).putInt(RATE * 2)
            .putShort(2).putShort(16).put("data".toByteArray()).putInt(pcm.size)
        return h.array() + pcm
    }

    private fun beep() {
        try { ToneGenerator(AudioManager.STREAM_MUSIC, 80).startTone(ToneGenerator.TONE_PROP_BEEP, 150) }
        catch (_: Exception) {}
    }

    companion object {
        const val RATE = 16000
        const val CHUNK = 4000          // 0.125 с
        const val RECENT = 64000        // последние 2 с
        const val SILENCE_CHUNKS = 12   // 1.5 с тишины — конец фразы
        const val MAX_CHUNKS = 120      // не больше 15 с
        const val MODEL_URL = "https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip"
        const val WAKE = "джарвис"
        val WAKE_FORMS = setOf("джарвис", "джервис", "жарвис", "джарвиз")
    }
}
