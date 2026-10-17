package ai.jarvis.device

import android.content.Context
import android.os.Build
import org.java_websocket.client.WebSocketClient
import org.java_websocket.handshake.ServerHandshake
import org.json.JSONArray
import org.json.JSONObject
import java.net.URI

/**
 * Связь с сервером Джарвиса по тому же протоколу, что и клиент на ПК:
 * pair/hello → welcome, затем call → result; события — event.
 * Несколько адресов (основной, ретранслятор в России) перебираются при обрывах.
 */
class Link(private val ctx: Context, private val onLog: (String) -> Unit) {

    private val prefs = ctx.getSharedPreferences("jarvis", Context.MODE_PRIVATE)
    @Volatile private var ws: WebSocketClient? = null
    @Volatile private var running = false
    @Volatile private var serverIndex = 0

    fun servers(): List<String> =
        prefs.getString("servers", "")!!.split(",").map { it.trim() }.filter { it.isNotEmpty() }

    fun deviceId(): String? = prefs.getString("device_id", null)

    fun saveServers(csv: String) = prefs.edit().putString("servers", csv).apply()

    private fun capabilities(): JSONArray {
        val caps = JSONArray().put("ui_tree").put("input").put("speaker")
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) caps.put("screen")
        if (ctx.checkSelfPermission(android.Manifest.permission.RECORD_AUDIO) ==
            android.content.pm.PackageManager.PERMISSION_GRANTED) caps.put("microphone")
        return caps
    }

    /** Первое подключение по одноразовому коду: сервер вернёт device_id и токен. */
    fun pair(server: String, code: String, name: String, done: (Boolean, String) -> Unit) {
        connect(server, JSONObject().apply {
            put("type", "pair"); put("code", code); put("name", name); put("kind", "android")
            put("languages", JSONArray().put("shell")); put("capabilities", capabilities())
        }, oneShot = true) { welcome ->
            if (welcome?.optString("type") == "welcome") {
                prefs.edit()
                    .putString("servers", server)
                    .putString("device_id", welcome.getString("device_id"))
                    .putString("token", welcome.getString("token"))
                    .putString("name", name)
                    .apply()
                done(true, welcome.getString("device_id"))
            } else done(false, welcome?.optString("error") ?: "нет ответа")
        }
    }

    fun start() {
        if (running) return
        running = true
        Thread { loop() }.start()
    }

    fun stop() { running = false; ws?.close() }

    private fun loop() {
        var delay = 2000L
        while (running) {
            val servers = servers()
            if (servers.isEmpty() || deviceId() == null) { Thread.sleep(3000); continue }
            val server = servers[serverIndex % servers.size]
            val hello = JSONObject().apply {
                put("type", "hello"); put("device_id", deviceId()); put("token", prefs.getString("token", ""))
                put("name", prefs.getString("name", "Android")); put("kind", "android")
                put("languages", JSONArray().put("shell")); put("capabilities", capabilities())
            }
            val ok = runSession(server, hello)
            if (ok) delay = 2000L else { serverIndex++; onLog("нет связи с $server") }
            Thread.sleep(delay)
            delay = (delay * 2).coerceAtMost(60000L)
        }
    }

    private fun runSession(server: String, hello: JSONObject): Boolean {
        val latch = java.util.concurrent.CountDownLatch(1)
        var connectedOk = false
        connect(server, hello, oneShot = false) { connectedOk = it != null; latch.countDown() }
        latch.await()
        // Держим соединение, пока открыто.
        while (running && ws?.isOpen == true) Thread.sleep(500)
        return connectedOk
    }

    private fun connect(server: String, first: JSONObject, oneShot: Boolean, onFirst: (JSONObject?) -> Unit) {
        var gotFirst = false
        val client = object : WebSocketClient(URI(server)) {
            override fun onOpen(h: ServerHandshake?) { send(first.toString()) }
            override fun onMessage(message: String?) {
                val msg = JSONObject(message ?: "{}")
                if (!gotFirst) {
                    gotFirst = true
                    onFirst(msg)
                    if (oneShot) close()
                    return
                }
                if (msg.optString("type") == "call") handleCall(msg)
                else if (msg.optString("type") == "cancel") Actions.cancel(msg.optString("id"))
                else if (msg.optString("type") == "say") Speech.speak(ctx, msg.optString("text"), msg.optString("audio_b64", null))
            }
            override fun onClose(code: Int, reason: String?, remote: Boolean) { if (!gotFirst) onFirst(null) }
            override fun onError(ex: Exception?) { onLog("ошибка: ${ex?.message}") }
        }
        ws = client
        try { client.connectBlocking(15, java.util.concurrent.TimeUnit.SECONDS) }
        catch (e: Exception) { if (!gotFirst) onFirst(null) }
    }

    fun sendEvent(text: String, trust: String = "observed") {
        ws?.takeIf { it.isOpen }?.send(JSONObject().apply {
            put("type", "event"); put("text", text); put("trust", trust)
        }.toString())
    }

    /** Фраза с микрофона: сервер распознает, ответит, а ответ придёт обратно и прозвучит здесь. */
    fun sendUtterance(wav: ByteArray) {
        val sock = ws?.takeIf { it.isOpen } ?: run { onLog("нет связи — фраза не отправлена"); return }
        sock.send(JSONObject().apply {
            put("type", "utterance")
            put("audio_b64", android.util.Base64.encodeToString(wav, android.util.Base64.NO_WRAP))
        }.toString())
    }

    private fun handleCall(msg: JSONObject) {
        val id = msg.getString("id")
        val action = msg.getString("action")
        val args = msg.optJSONObject("args") ?: JSONObject()
        Thread {
            val timeout = msg.optDouble("timeout", 120.0).toLong().coerceIn(5L, 7200L)
            val result = Actions.run(ctx, action, args, id, timeout)
            ws?.takeIf { it.isOpen }?.send(JSONObject().apply {
                put("type", "result"); put("id", id)
                put("ok", result.ok); put("output", result.output)
                result.image?.let { put("image_b64", it) }
            }.toString())
        }.start()
    }
}
