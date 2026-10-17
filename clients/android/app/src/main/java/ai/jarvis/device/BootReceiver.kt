package ai.jarvis.device

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/** Запуск связи при включении телефона. */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        if (intent?.action == Intent.ACTION_BOOT_COMPLETED) LinkService.start(context)
    }
}
