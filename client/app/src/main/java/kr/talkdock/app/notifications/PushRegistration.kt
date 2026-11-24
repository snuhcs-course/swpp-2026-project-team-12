package kr.talkdock.app.notifications

import android.content.Context
import android.util.Log
import androidx.core.app.NotificationManagerCompat
import com.google.firebase.FirebaseApp
import com.google.firebase.messaging.FirebaseMessaging
import kr.talkdock.app.data.ApiClient
import kr.talkdock.app.data.SessionStore
import org.json.JSONObject
import java.util.UUID
import java.util.concurrent.Executors

/** One receiving account per installation, including this app's account switcher. */
object PushRegistration {
    private val executor = Executors.newSingleThreadExecutor()
    private fun prefs(context: Context) = context.getSharedPreferences("talkdock-push", Context.MODE_PRIVATE)
    private fun identity(context: Context): String {
        val store = SessionStore(context)
        return store.current()?.let { "${store.serverUrl()}|${it.optString("token")}" }.orEmpty()
    }

    fun binding(context: Context): String = prefs(context).getString("binding", "").orEmpty()

    fun invalidate(context: Context) {
        prefs(context).edit().remove("binding").remove("identity").apply()
        NotificationManagerCompat.from(context).cancelAll()
    }

    fun sync(context: Context, newToken: String? = null) {
        val app = context.applicationContext
        if (newToken != null) prefs(app).edit().putString("token", newToken).apply()
        val expected = identity(app)
        if (prefs(app).getString("identity", "") != expected) invalidate(app)
        if (expected.isBlank()) return
        if (!NotificationManagerCompat.from(app).areNotificationsEnabled()) {
            unregister(app)
            return
        }
        if (FirebaseApp.initializeApp(app) == null) return
        FirebaseMessaging.getInstance().token.addOnSuccessListener { token ->
            executor.execute {
                if (identity(app) != expected) return@execute
                val p = prefs(app)
                val installation = p.getString("installation", null) ?: UUID.randomUUID().toString().also {
                    p.edit().putString("installation", it).commit()
                }
                try {
                    val store = SessionStore(app)
                    val session = store.current() ?: return@execute
                    val result = ApiClient(session.getString("token"), store.serverUrl()).request(
                        "notifications/device/", "PUT", JSONObject().put("installation_id", installation).put("token", token),
                        readTimeoutMillis = 10_000)
                    if (identity(app) == expected) p.edit().putString("identity", expected)
                        .putString("binding", result.getString("binding")).apply()
                } catch (error: Exception) {
                    Log.w("TodakPush", "Registration will retry when the app resumes", error)
                }
            }
        }.addOnFailureListener { Log.w("TodakPush", "FCM token unavailable", it) }
    }

    private fun unregister(context: Context) {
        val store = SessionStore(context)
        val session = store.current() ?: return
        val installation = prefs(context).getString("installation", null) ?: return
        invalidate(context)
        executor.execute {
            runCatching { ApiClient(session.getString("token"), store.serverUrl()).request("notifications/device/", "DELETE",
                JSONObject().put("installation_id", installation), readTimeoutMillis = 10_000) }
        }
    }
}
