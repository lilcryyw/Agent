package ai.jarvis.device

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import android.text.InputType
import android.view.Gravity
import android.widget.*

/** Экран настройки: подключение по коду и разрешения. Слушание работает и без этого экрана. */
class MainActivity : Activity() {
    private lateinit var link: Link
    private lateinit var status: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        link = Link(applicationContext) {}
        val root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(48, 64, 48, 48) }
        status = TextView(this).apply { textSize = 17f; gravity = Gravity.CENTER; setPadding(0, 0, 0, 32) }
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
        val mic = Button(this).apply { text = "Разрешить микрофон (слушать «Джарвис»)" }
        val battery = Button(this).apply { text = "Не выключать в фоне (важно)" }
        val perms = Button(this).apply { text = "Включить управление (спец. возможности)" }

        connect.setOnClickListener {
            val s = server.text.toString().trim()
            val c = code.text.toString().trim()
            if (s.isEmpty() || c.isEmpty()) { toast("Впиши адрес и код"); return@setOnClickListener }
            connect.isEnabled = false
            connect.text = "Подключаю…"
            Thread {
                link.pair(s, c, name.text.toString().trim().ifEmpty { android.os.Build.MODEL }) { ok, info ->
                    runOnUiThread {
                        connect.isEnabled = true
                        connect.text = "Подключить"
                        if (ok) {
                            LinkService.start(this)
                            refresh()
                        } else toast("Не вышло: $info")
                    }
                }
            }.start()
        }
        mic.setOnClickListener {
            requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO, Manifest.permission.POST_NOTIFICATIONS), 1)
        }
        battery.setOnClickListener {
            startActivity(Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName")))
        }
        perms.setOnClickListener {
            startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
            toast("Найди «Джарвис» и включи — тогда он сможет управлять телефоном")
        }
        for (v in listOf(status, server, code, name, connect, mic, battery, perms)) root.addView(v)
        setContentView(ScrollView(this).apply { addView(root) })
        refresh()
        if (link.deviceId() != null) LinkService.start(this)
    }

    private fun refresh() {
        val id = link.deviceId()
        val hasMic = checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED
        status.text = (if (id != null) "Подключено ✓ ($id)" else "Не подключено") + "\n" +
            (if (hasMic) "Слушаю слово «Джарвис» — работает и с закрытым приложением"
             else "Микрофон выключен — нажми «Разрешить микрофон»")
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        refresh()
        if (link.deviceId() != null) LinkService.start(this)  // службе нужен микрофон — переобъявить тип
    }

    private fun toast(s: String) = Toast.makeText(this, s, Toast.LENGTH_LONG).show()
}
