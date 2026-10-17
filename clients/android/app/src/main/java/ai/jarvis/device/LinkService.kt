package ai.jarvis.device

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder

/**
 * Фоновая служба: живёт, пока телефон включён, даже если приложение закрыто.
 * Держит связь с сервером и слушает слово «Джарвис». Для микрофона в Android 14+ тип службы — «микрофон».
 */
class LinkService : Service() {
    private var voice: VoiceListener? = null
    private var notif: Notification? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        val id = "jarvis"
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val ch = NotificationChannel(id, "Джарвис", NotificationManager.IMPORTANCE_MIN)
            (getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager).createNotificationChannel(ch)
        }
        val n: Notification = Notification.Builder(this, id)
            .setContentTitle("Джарвис на связи")
            .setContentText(if (hasMic()) "Слушаю: скажите «Джарвис»" else "Связь активна")
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setOngoing(true)
            .build()
        notif = n
        startForegroundCompat(n)
        if (link == null) link = Link(applicationContext) { android.util.Log.i("Jarvis", it) }.also { it.start() }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        // После выдачи разрешения на микрофон переобъявляем службу с нужным типом.
        notif?.let { startForegroundCompat(it) }
        startVoice()
        return START_STICKY
    }

    private fun startForegroundCompat(n: Notification) {
        val mic = hasMic()
        when {
            Build.VERSION.SDK_INT >= 34 -> startForeground(1, n,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE or
                    (if (mic) ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE else 0))
            Build.VERSION.SDK_INT >= 30 -> startForeground(1, n,
                if (mic) ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE else 0)
            else -> startForeground(1, n)
        }
    }

    private fun hasMic() =
        checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED

    private fun startVoice() {
        if (voice != null || !hasMic() || link?.deviceId() == null) return
        voice = VoiceListener(applicationContext, { android.util.Log.i("Jarvis", it) }) { wav ->
            link?.sendUtterance(wav)
        }.also { it.start() }
    }

    override fun onDestroy() {
        voice?.stop()
        link?.stop()
        link = null
        super.onDestroy()
    }

    companion object {
        @Volatile var link: Link? = null

        fun start(ctx: Context) {
            val i = Intent(ctx, LinkService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) ctx.startForegroundService(i) else ctx.startService(i)
        }
    }
}
