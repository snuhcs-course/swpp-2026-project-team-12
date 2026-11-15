package kr.talkdock.app.notifications

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.net.Uri
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import kr.talkdock.app.MainActivity
import kr.talkdock.app.R
import kr.talkdock.app.data.SessionStore

object TodakNotifications {
    const val ACTIVITY = "family_activity"
    const val REMINDERS = "daily_question_reminders"
    const val EXTRA = "todak_push"

    fun channels(context: Context) {
        val manager = context.getSystemService(NotificationManager::class.java)
        manager.createNotificationChannels(listOf(
            NotificationChannel(ACTIVITY, "가족 소식과 댓글", NotificationManager.IMPORTANCE_HIGH).apply {
                description = "새 게시글, 내 글의 댓글, 오늘의 질문 답변과 댓글"
            },
            NotificationChannel(REMINDERS, "오늘의 질문 알림", NotificationManager.IMPORTANCE_DEFAULT).apply {
                description = "한국 시간 오후 8시, 아직 답하지 않은 오늘의 질문"
            }))
    }

    fun matchesAccount(context: Context, data: Map<String, String>): Boolean {
        val account = SessionStore(context).current() ?: return false
        val binding = PushRegistration.binding(context)
        return binding.isNotBlank() && binding == data["binding"] &&
            account.optInt("user_id").toString() == data["user_id"]
    }

    fun receive(context: Context, data: Map<String, String>) {
        if (!matchesAccount(context, data)) return
        val event = data["event_id"] ?: return
        val prefs = context.getSharedPreferences("talkdock-push-seen", Context.MODE_PRIVATE)
        val key = "${data["binding"]}:$event"
        val seen = prefs.getStringSet("events", emptySet()).orEmpty()
        if (key in seen) return
        if (show(context, data)) prefs.edit().putStringSet("events", (seen.toList().takeLast(199) + key).toSet()).apply()
    }

    fun show(context: Context, data: Map<String, String>): Boolean {
        channels(context)
        if (!NotificationManagerCompat.from(context).areNotificationsEnabled()) return false
        if (Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(context,
                Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) return false
        val event = data["event_id"] ?: return false
        val reminder = data["kind"] == "reminder"
        val intent = Intent(context, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP
            this.data = Uri.parse("todak://push/${data["binding"]}/$event")
            putExtra(EXTRA, true)
            data.forEach { (key, value) -> putExtra(key, value) }
        }
        val pending = PendingIntent.getActivity(context, 0, intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val notification = NotificationCompat.Builder(context, if (reminder) REMINDERS else ACTIVITY)
            .setSmallIcon(R.drawable.ic_notification)
            .setColor(Color.rgb(235, 120, 105)).setContentTitle(data["title"])
            .setContentText(data["body"]).setStyle(NotificationCompat.BigTextStyle().bigText(data["body"]))
            .setCategory(if (reminder) NotificationCompat.CATEGORY_REMINDER else NotificationCompat.CATEGORY_MESSAGE)
            .setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
            .setContentIntent(pending).setAutoCancel(true).setOnlyAlertOnce(true)
            .build()
        NotificationManagerCompat.from(context).notify(event, 0, notification)
        return true
    }
}
