package kr.talkdock.app

import android.app.Notification
import android.app.NotificationManager
import android.content.Context
import android.graphics.Bitmap
import android.os.Build
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import kr.talkdock.app.notifications.PushRegistration
import kr.talkdock.app.notifications.TodakNotifications
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

/** Exercises the real Android notification pipeline, without external Firebase credentials. */
@RunWith(AndroidJUnit4::class)
class PushNotificationTest {
    private val test = InstrumentationRegistry.getInstrumentation()
    private val context get() = test.targetContext
    private val manager get() = context.getSystemService(NotificationManager::class.java)
    private val sessionPrefs get() = context.getSharedPreferences(if (BuildConfig.DEBUG) "talkdock-session" else "talkdock-public-session", Context.MODE_PRIVATE)
    private var originalSession: String? = null
    private var originalBinding: String? = null
    private val pushPrefs get() = context.getSharedPreferences("talkdock-push", Context.MODE_PRIVATE)
    private val seenPrefs get() = context.getSharedPreferences("talkdock-push-seen", Context.MODE_PRIVATE)
    private var originalSeen = emptySet<String>()
    private fun sample(kind: String, id: String = kind) = mapOf(
        "event_id" to id, "binding" to "test-binding", "user_id" to "91001", "room_id" to "1",
        "post_id" to "2", "question_id" to if (kind in listOf("answer", "question_comment", "reminder")) "3" else "",
        "kind" to kind,
        "title" to when (kind) { "post" -> "토닥이 · 새 소식"; "reminder" -> "토닥이 · 오늘의 질문"; else -> "할머니 경자" },
        "body" to when (kind) {
            "post" -> "손녀 정아님이 게시글을 올렸어요!"
            "comment" -> "사진이 참 예쁘구나! 다음에는 할머니도 같이 가자 💛"
            "answer" -> "오늘의 질문에 답했어요!\nQ. 오늘 가장 고마웠던 일은 무엇인가요?"
            "question_comment" -> "같이 산책해서 참 좋았어 💛\nQ. 오늘 가장 고마웠던 일은 무엇인가요?"
            else -> "아직 오늘의 이야기를 들려주지 않으셨어요 💛\nQ. 오늘 가장 고마웠던 일은 무엇인가요?"
        })

    @Before fun prepare() {
        originalSession = sessionPrefs.getString("current", null)
        originalBinding = pushPrefs.getString("binding", null)
        originalSeen = seenPrefs.getStringSet("events", emptySet()).orEmpty().toSet()
        sessionPrefs.edit().putString("current", JSONObject().put("user_id", 91001).put("token", "test-only").toString()).commit()
        pushPrefs.edit().putString("binding", "test-binding").commit()
        seenPrefs.edit().clear().commit()
        if (Build.VERSION.SDK_INT >= 33) test.uiAutomation.grantRuntimePermission(context.packageName, "android.permission.POST_NOTIFICATIONS")
        manager.cancelAll()
        Thread.sleep(600)
    }

    @After fun restore() {
        manager.cancelAll()
        sessionPrefs.edit().putString("current", originalSession).commit()
        pushPrefs.edit().putString("binding", originalBinding).commit()
        seenPrefs.edit().putStringSet("events", originalSeen).commit()
        test.uiAutomation.executeShellCommand("cmd statusbar collapse").close()
    }

    private fun awaitNotification(id: String): Notification {
        repeat(50) {
            manager.activeNotifications.firstOrNull { it.tag == id }?.let { return it.notification }
            Thread.sleep(50)
        }
        error("Notification $id not displayed")
    }

    @Test fun displaysContentChannelsAndDestination() {
        for (kind in listOf("post", "comment", "answer", "question_comment", "reminder")) {
            val data = sample(kind)
            TodakNotifications.receive(context, data)
            val notification = awaitNotification(kind)
            assertEquals(data["title"], notification.extras.getString(Notification.EXTRA_TITLE))
            assertEquals(data["body"], notification.extras.getCharSequence(Notification.EXTRA_BIG_TEXT).toString())
            assertEquals(if (kind == "reminder") TodakNotifications.REMINDERS else TodakNotifications.ACTIVITY, notification.channelId)
            assertNotNull(notification.contentIntent)
            assertEquals(Notification.VISIBILITY_PRIVATE, notification.visibility)
            manager.cancelAll()
        }
    }

    @Test fun ignoresOtherAccountsOldBindingsAndDuplicateDelivery() {
        TodakNotifications.receive(context, sample("comment") + ("user_id" to "999"))
        TodakNotifications.receive(context, sample("comment") + ("binding" to "old-binding"))
        assertTrue(manager.activeNotifications.isEmpty())
        TodakNotifications.receive(context, sample("comment"))
        awaitNotification("comment")
        manager.cancelAll(); Thread.sleep(150)
        TodakNotifications.receive(context, sample("comment"))
        assertTrue(manager.activeNotifications.isEmpty())
        PushRegistration.invalidate(context)
        assertFalse(TodakNotifications.matchesAccount(context, sample("answer")))
    }

    @Test fun captureNotificationExamples() {
        if (InstrumentationRegistry.getArguments().getString("pushScreenshots") != "true") return
        val directory = File(context.getExternalFilesDir(null), "push-previews").apply { mkdirs() }
        test.uiAutomation.executeShellCommand("input keyevent KEYCODE_WAKEUP").close()
        test.uiAutomation.executeShellCommand("wm dismiss-keyguard").close()
        for (kind in listOf("post", "comment", "answer", "question_comment", "reminder")) {
            manager.cancelAll()
            test.uiAutomation.executeShellCommand("cmd statusbar collapse").close()
            Thread.sleep(400)
            val data = sample(kind, "preview-$kind-${System.nanoTime()}")
            TodakNotifications.show(context, data)
            awaitNotification(data.getValue("event_id"))
            Thread.sleep(1200)
            test.uiAutomation.executeShellCommand("cmd statusbar expand-notifications").close()
            // Reopen after the first heads-up animation before capturing the shade.
            Thread.sleep(1200)
            test.uiAutomation.executeShellCommand("cmd statusbar collapse").close()
            Thread.sleep(800)
            test.uiAutomation.executeShellCommand("cmd statusbar expand-notifications").close()
            Thread.sleep(1500)
            val screenshot = requireNotNull(test.uiAutomation.takeScreenshot())
            File(directory, "$kind.png").outputStream().use { screenshot.compress(Bitmap.CompressFormat.PNG, 100, it) }
            screenshot.recycle()
        }
    }
}
