package ai.jarvis.device

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.provider.Settings
import android.text.InputType
import android.view.Gravity
import android.widget.*

/** Единственный экран: подключение по коду от Джарвиса и включение нужных разрешений. */
class MainActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val link = Link(applicationContext) {}
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; setPadding(48, 64, 48, 48)
        }
        val status = TextView(this).apply {
            text = if (link.deviceId() != null) "Подключено ✓ (${link.deviceId()})" else "Не подключено"
            textSize = 18f; gravity = Gravity.CENTER; setPadding(0, 0, 0, 32)
        }
        val server = EditText(this).apply {
            hint = "Адрес сервера (wss://…/devices) — от Джарвиса"
            setText(link.servers().firstOrNull() ?: "")
        }
        val code = EditText(this).apply {
            hint = "Код подключения (ABCD-EFGH)"
            inputType = InputType.TYPE_TEXT_FLAG_CAP_CHARACTERS
        }
        val name = EditText(this).apply { hint = "Имя устройства"; setText(android.os.Build.MODEL) }
        val connect = Button(this).apply { text = "Подключить" }
        val perms = Button(this).apply { text = "Включить управление (спец. возможности)" }

        connect.setOnClickListener {
            val s = server.text.toString().trim(); val c = code.text.toString().trim()
            if (s.isEmpty() || c.isEmpty()) { toast("Впиши адрес и код"); return@setOnClickListener }
            connect.isEnabled = false; connect.text = "Подключаю…"
            Thread {
                link.pair(s, c, name.text.toString().trim().ifEmpty { android.os.Build.MODEL }) { ok, info ->
                    runOnUiThread {
                        connect.isEnabled = true; connect.text = "Подключить"
                        if (ok) { status.text = "Подключено ✓ ($info)"; LinkService.start(this) }
                        else toast("Не вышло: $info")
                    }
                }
            }.start()
        }
        perms.setOnClickListener {
            startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
            toast("Найди «Джарвис» и включи — тогда он сможет управлять телефоном")
        }
        for (v in listOf(status, server, code, name, connect, perms)) root.addView(v)
        setContentView(ScrollView(this).apply { addView(root) })
        if (link.deviceId() != null) LinkService.start(this)
    }

    private fun toast(s: String) = Toast.makeText(this, s, Toast.LENGTH_LONG).show()
}
