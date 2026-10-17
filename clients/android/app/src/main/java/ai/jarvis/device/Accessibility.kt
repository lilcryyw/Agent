package ai.jarvis.device

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.graphics.Path
import android.os.Build
import android.os.Bundle
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/**
 * Служба специальных возможностей: Джарвис видит экран как дерево элементов и нажимает.
 * Это и есть «руки и глаза» на Android — через официальный системный механизм, без root.
 */
class JarvisAccessibility : AccessibilityService() {

    override fun onServiceConnected() { instance = this }
    override fun onDestroy() { if (instance === this) instance = null; super.onDestroy() }
    override fun onAccessibilityEvent(event: AccessibilityEvent?) {}
    override fun onInterrupt() {}

    /** Дерево видимых элементов экрана как текст: что нажимаемо, где находится, какой текст. */
    fun uiTree(): String {
        val sb = StringBuilder()
        for (window in windows) {
            val root = window.root ?: continue
            dump(root, 0, sb)
        }
        return if (sb.isEmpty()) "(экран пуст или недоступен)" else sb.toString()
    }

    private fun dump(node: AccessibilityNodeInfo?, depth: Int, sb: StringBuilder) {
        if (node == null || depth > 40) return
        val text = node.text?.toString()?.trim().orEmpty()
        val desc = node.contentDescription?.toString()?.trim().orEmpty()
        val label = (if (text.isNotEmpty()) text else desc)
        if (label.isNotEmpty() || node.isClickable) {
            val r = android.graphics.Rect(); node.getBoundsInScreen(r)
            val cx = (r.left + r.right) / 2; val cy = (r.top + r.bottom) / 2
            val kind = node.className?.toString()?.substringAfterLast('.') ?: "?"
            val flags = buildString {
                if (node.isClickable) append(" clickable")
                if (node.isEditable) append(" editable")
                if (node.isChecked) append(" checked")
            }
            sb.append("  ".repeat(depth.coerceAtMost(8)))
                .append("[$kind] \"$label\" @($cx,$cy)$flags\n")
        }
        for (i in 0 until node.childCount) dump(node.getChild(i), depth + 1, sb)
    }

    /** Нажатие/жест в точке экрана (в реальных пикселях). */
    fun tap(x: Int, y: Int, longPress: Boolean = false): Boolean {
        val path = Path().apply { moveTo(x.toFloat(), y.toFloat()) }
        val stroke = GestureDescription.StrokeDescription(path, 0, if (longPress) 600 else 50)
        return dispatch(GestureDescription.Builder().addStroke(stroke).build())
    }

    fun swipe(x1: Int, y1: Int, x2: Int, y2: Int, ms: Long = 300): Boolean {
        val path = Path().apply { moveTo(x1.toFloat(), y1.toFloat()); lineTo(x2.toFloat(), y2.toFloat()) }
        val stroke = GestureDescription.StrokeDescription(path, 0, ms)
        return dispatch(GestureDescription.Builder().addStroke(stroke).build())
    }

    private fun dispatch(gesture: GestureDescription): Boolean {
        val latch = CountDownLatch(1); var ok = false
        dispatchGesture(gesture, object : GestureResultCallback() {
            override fun onCompleted(d: GestureDescription?) { ok = true; latch.countDown() }
            override fun onCancelled(d: GestureDescription?) { latch.countDown() }
        }, null)
        latch.await(5, TimeUnit.SECONDS)
        return ok
    }

    /** Напечатать текст в поле, которое сейчас в фокусе. */
    fun typeText(text: String): Boolean {
        val node = findFocus(AccessibilityNodeInfo.FOCUS_INPUT) ?: return false
        val args = Bundle().apply { putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text) }
        return node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)
    }

    fun global(action: String): Boolean {
        val code = when (action) {
            "back" -> GLOBAL_ACTION_BACK
            "home" -> GLOBAL_ACTION_HOME
            "recents" -> GLOBAL_ACTION_RECENTS
            "notifications" -> GLOBAL_ACTION_NOTIFICATIONS
            else -> return false
        }
        return performGlobalAction(code)
    }

    /** Снимок экрана (Android 11+), PNG в base64; на старых версиях недоступен. */
    fun screenshot(cb: (String?) -> Unit) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) { cb(null); return }
        takeScreenshot(android.view.Display.DEFAULT_DISPLAY, mainExecutor,
            object : TakeScreenshotCallback {
                override fun onSuccess(res: ScreenshotResult) {
                    try {
                        val bmp = android.graphics.Bitmap.wrapHardwareBuffer(res.hardwareBuffer, res.colorSpace)!!
                            .copy(android.graphics.Bitmap.Config.ARGB_8888, false)
                        res.hardwareBuffer.close()
                        val scaled = scaleDown(bmp, 1280)
                        val out = java.io.ByteArrayOutputStream()
                        scaled.compress(android.graphics.Bitmap.CompressFormat.PNG, 90, out)
                        cb(android.util.Base64.encodeToString(out.toByteArray(), android.util.Base64.NO_WRAP))
                    } catch (e: Exception) { cb(null) }
                }
                override fun onFailure(code: Int) { cb(null) }
            })
    }

    private fun scaleDown(bmp: android.graphics.Bitmap, maxW: Int): android.graphics.Bitmap {
        if (bmp.width <= maxW) return bmp
        val h = bmp.height * maxW / bmp.width
        return android.graphics.Bitmap.createScaledBitmap(bmp, maxW, h, true)
    }

    companion object {
        @Volatile var instance: JarvisAccessibility? = null
    }
}
