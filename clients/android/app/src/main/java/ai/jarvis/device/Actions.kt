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
    fun run(ctx: Context, action: String, args: JSONObject): Result = try {
        when (action) {
            "run" -> shell(args.optString("code"))
            "ui_tree" -> uiTree()
            "screenshot" -> screenshot()
            "input" -> input(args)
            else -> Result(false, "неизвестное действие $action")
        }
    } catch (e: Exception) { Result(false, "${e.javaClass.simpleName}: ${e.message}") }

    private fun shell(code: String): Result {
        val proc = ProcessBuilder("sh", "-c", code).redirectErrorStream(true).start()
        val out = proc.inputStream.bufferedReader().readText()
        val ok = proc.waitFor(120, TimeUnit.SECONDS)
        val exit = if (ok) proc.exitValue() else -9.also { proc.destroy() }
        return Result(exit == 0, "код выхода $exit\n${out.takeLast(50000)}")
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
        val x = args.optInt("x", -1); val y = args.optInt("y", -1)
        val ok = when (args.optString("action")) {
            "click" -> a.tap(x, y)
            "double_click" -> a.tap(x, y).also { a.tap(x, y) }
            "right_click" -> a.tap(x, y, longPress = true)
            "type" -> a.typeText(args.optString("text"))
            "key" -> a.global(args.optString("keys"))
            "scroll" -> {
                val amt = args.optInt("amount", -5)
                a.swipe(x.coerceAtLeast(300), 1000, x.coerceAtLeast(300), 1000 + amt * 60)
            }
            "move" -> true
            else -> return Result(false, "неизвестный ввод")
        }
        return Result(ok, if (ok) "сделано" else "не удалось (проверь, что служба включена)")
    }
}
