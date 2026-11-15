package kr.talkdock.app.data

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject

class SessionStore(private val context: Context) {
    private val prefs = context.getSharedPreferences(
        if (kr.talkdock.app.BuildConfig.DEBUG) "talkdock-session" else "talkdock-public-session", Context.MODE_PRIVATE)
    fun serverUrl(): String = prefs.getString("server", kr.talkdock.app.BuildConfig.API_URL)!!
    fun changeServer(url: String) {
        if (url != serverUrl()) {
            kr.talkdock.app.notifications.PushRegistration.invalidate(context)
            prefs.edit().remove("current").remove("accounts").putString("server", url).apply()
        }
    }
    fun current(): JSONObject? = prefs.getString("current", null)?.let { JSONObject(it) }
    fun all(): List<JSONObject> {
        val list = JSONArray(prefs.getString("accounts", "[]"))
        return (0 until list.length()).map { list.getJSONObject(it) }
    }
    fun save(session: JSONObject, large: Boolean) {
        if (current()?.optString("token") != session.optString("token"))
            kr.talkdock.app.notifications.PushRegistration.invalidate(context)
        session.put("large", large)
        val items = all().filter { it.getInt("user_id") != session.getInt("user_id") } + session
        prefs.edit().putString("current", session.toString())
            .putString("accounts", JSONArray(items).toString()).apply()
    }
    fun removeCurrent() {
        val selected = current() ?: return
        kr.talkdock.app.notifications.PushRegistration.invalidate(context)
        val remaining = all().filter { it.getInt("user_id") != selected.getInt("user_id") }
        prefs.edit().remove("current").putString("accounts", JSONArray(remaining).toString()).apply()
    }
}
