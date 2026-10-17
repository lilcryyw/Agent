package ai.jarvis.device

import android.content.Context
import org.json.JSONObject
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/** Результат действия на устройстве. */
data class Result(val ok: Boolean, val output: String, val image: String? = null)

/**
 * Выполнение того, о чём просит Джарвис:
 *   run        — команда shell;
 *   screenshot — снимок экрана (через спец. возможности);
 *   input      — нажатия/ввод (через спец. возможности): click, swipe, type, key;
 *   ui_tree    — дерево элементов экрана (дёшево, без картинки).
 */
object Actions {
    /** Выполняющиеся команды: id вызова → процесс (чтобы «Джарвис, стоп» мог их остановить). */
    private val procs = java.util.concurrent.ConcurrentHashMap<String, Process>()
    private val cancelled = java.util.Collections.newSetFromMap(java.util.concurrent.ConcurrentHashMap<String, Boolean>())

    fun run(ctx: Context, action: String, args: JSONObject, id: String = "", timeoutS: Long = 120): Result = try {
        when (action) {
            "run" -> shell(args.optString("code"), args.optJSONObject("env"), id, timeoutS)
            "ui_tree" -> uiTree()
            "screenshot" -> screenshot()
            "input" -> input(args)
            else -> Result(false, "неизвестное действие $action")
        }
    } catch (e: Exception) { Result(false, "${e.javaClass.simpleName}: ${e.message}") }

    fun cancel(id: String) {
        procs[id]?.let { cancelled.add(id); it.destroyForcibly() }
    }

    private fun shell(code: String, env: JSONObject?, id: String, timeoutS: Long): Result {
        val pb = ProcessBuilder("sh", "-c", code).redirectErrorStream(true)
        env?.keys()?.forEach { k -> pb.environment()[k] = env.optString(k) }
        val proc = pb.start()
        if (id.isNotEmpty()) procs[id] = proc
        // Вывод читаем в отдельном потоке: иначе зависшая команда держала бы нас вечно и тайм-аут не работал.
        val buf = StringBuilder()
        val reader = Thread {
            try { proc.inputStream.bufferedReader().forEachLine { synchronized(buf) { buf.append(it).append('\n') } } }
            catch (_: Exception) {}
        }.apply { isDaemon = true; start() }
        val finished = proc.waitFor(timeoutS, TimeUnit.SECONDS)
        if (!finished) proc.destroyForcibly()
        reader.join(2000)
        procs.remove(id)
        val out = synchronized(buf) { buf.toString() }.takeLast(50000)
        if (cancelled.remove(id)) return Result(false, "остановлено по просьбе человека\n$out")
        if (!finished) return Result(false, "превышено время $timeoutS с (процесс остановлен)\n$out")
        val exit = proc.exitValue()
        return Result(exit == 0, "код выхода $exit\n$out")
    }

    private fun acc(): JarvisAccessibility? = JarvisAccessibility.instance

    private fun uiTree(): Result {
        val a = acc() ?: return Result(false, "Служба спец. возможностей не включена.")
        return Result(true, a.uiTree())
    }

    private fun screenshot(): Result {
        val a = acc() ?: return Result(false, "Служба спец. возможностей не включена.")
        val latch = CountDownLatch(1); var img: String? = null
        a.screenshot { img = it; latch.countDown() }
        latch.await(15, TimeUnit.SECONDS)
        return if (img != null) Result(true, "снимок экрана (координаты — в пикселях снимка)", img)
        else Result(false, "снимок недоступен (нужен Android 11+)")
    }

    private fun input(args: JSONObject): Result {
        val a = acc() ?: return Result(false, "Служба спец. возможностей не включена.")
        val x = args.optDouble("x", -1.0).toInt(); val y = args.optDouble("y", -1.0).toInt()
        val x2 = args.optDouble("x2", -1.0).toInt(); val y2 = args.optDouble("y2", -1.0).toInt()
        val ms = args.optDouble("ms", 300.0).toLong().coerceIn(50L, 5000L)
        val ok = when (args.optString("action")) {
            "click" -> a.tap(x, y)
            "double_click" -> a.tap(x, y).also { a.tap(x, y) }
            "right_click", "long_press" -> a.tap(x, y, longPress = true)
            "drag", "swipe" -> a.swipe(x, y, x2, y2, ms)
            "type" -> a.typeText(args.optString("text"))
            "key" -> a.global(args.optString("keys").trim().lowercase())
            "scroll" -> {
                val amt = args.optDouble("amount", -5.0).toInt()
                val cx = if (x >= 0) x else 540; val cy = if (y >= 0) y else 1200
                a.swipe(cx, cy, cx, cy + amt * 60)
            }
            "move" -> true
            else -> return Result(false, "неизвестный ввод")
        }
        return Result(ok, if (ok) "сделано" else "не удалось (проверь, что служба включена и элемент в фокусе)")
    }
}
