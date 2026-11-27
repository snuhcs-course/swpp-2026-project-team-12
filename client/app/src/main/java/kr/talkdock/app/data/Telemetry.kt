package kr.talkdock.app.data

import android.content.Context
import android.os.Bundle
import com.google.firebase.FirebaseApp
import com.google.firebase.analytics.FirebaseAnalytics
import com.google.firebase.crashlytics.FirebaseCrashlytics
import kr.talkdock.app.BuildConfig
import java.util.UUID
import java.util.concurrent.atomic.AtomicInteger

/** Only controlled metadata crosses this boundary. Never pass user text or exception messages. */
object Telemetry {
    private val operations = java.util.Collections.synchronizedMap(object : LinkedHashMap<String, Operation>() {
        override fun removeEldestEntry(eldest: MutableMap.MutableEntry<String, Operation>?) = size > 128
    })
    fun resume(id: String, feature: String) = if (id.isBlank()) start(feature) else operations[id] ?: Operation(feature, id)
    private var analytics: FirebaseAnalytics? = null
    private var crashlytics: FirebaseCrashlytics? = null
    var sink: ((String, Map<String, Any>) -> Unit)? = null
    private val allowed = setOf("feature", "operation_id", "stage", "result", "attempt", "duration_ms", "elapsed_ms",
        "route", "method", "http_status", "request_id", "error_code", "notification_id", "reason", "count", "bytes", "cache_hit", "draft_edited")

    fun initialize(context: Context) {
        // An unconfigured local APK remains fully usable and sends no Firebase telemetry.
        runCatching {
            if (FirebaseApp.initializeApp(context) == null) return
            analytics = FirebaseAnalytics.getInstance(context)
            crashlytics = FirebaseCrashlytics.getInstance()
            val enabled = !BuildConfig.DEBUG || context.packageName.endsWith(".memorydemo")
            analytics?.setAnalyticsCollectionEnabled(enabled)
            crashlytics?.setCrashlyticsCollectionEnabled(enabled)
            crashlytics?.setCustomKey("environment", if (BuildConfig.DEBUG) "test" else "production")
        }
    }

    fun event(name: String, fields: Map<String, Any>) {
        val safe = fields.filterKeys { it in allowed } + mapOf("schema_version" to 1,
            "event_id" to UUID.randomUUID().toString(), "environment" to if (BuildConfig.DEBUG) "test" else "production",
            "app_version" to BuildConfig.VERSION_NAME, "component" to "android")
        sink?.invoke(name, safe)
        runCatching {
            val params = Bundle()
            safe.forEach { (key, value) -> when (value) {
                is Long -> params.putLong(key, value)
                is Int -> params.putLong(key, value.toLong())
                is Double -> params.putDouble(key, value)
                is Boolean -> params.putString(key, value.toString())
                else -> params.putString(key, value.toString().take(100))
            } }
            analytics?.logEvent(name, params)
        }
    }

    fun screen(name: String) {
        runCatching { crashlytics?.setCustomKey("screen", name) }
        event("screen_view", mapOf("stage" to name))
    }

    fun start(feature: String): Operation = Operation(feature).also {
        operations[it.id] = it
        event("feature_used", mapOf("feature" to feature, "operation_id" to it.id))
        runCatching { crashlytics?.setCustomKey("feature", feature) }
    }

    class Operation(val feature: String, val id: String = UUID.randomUUID().toString()) {
        private val started = System.nanoTime()
        private val attempts = AtomicInteger()
        fun attempt() = attempts.incrementAndGet()
        fun stage(name: String, result: String = "success", durationMs: Long = 0, fields: Map<String, Any> = emptyMap()) {
            event("feature_stage", fields + mapOf("feature" to feature, "operation_id" to id, "stage" to name,
                "result" to result, "attempt" to attempts.get(), "duration_ms" to durationMs,
                "elapsed_ms" to (System.nanoTime() - started) / 1_000_000))
        }
    }
}
