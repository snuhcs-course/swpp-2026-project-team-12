package kr.talkdock.app

import android.Manifest
import android.app.NotificationManager
import android.os.Build
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import kr.talkdock.app.notifications.TodakNotifications
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith

/** Explicit, opt-in physical-device preview. Leaves examples in the notification
 * shade for visual inspection without logging in or changing account preferences. */
@RunWith(AndroidJUnit4::class)
class PhoneNotificationPreviewTest {
    @Test fun showExamplesOnPhone() {
        assumeTrue(InstrumentationRegistry.getArguments().getString("phonePreview") == "true")
        val test = InstrumentationRegistry.getInstrumentation()
        val context = test.targetContext
        if (Build.VERSION.SDK_INT >= 33) test.uiAutomation.grantRuntimePermission(
            context.packageName, Manifest.permission.POST_NOTIFICATIONS)
        val manager = context.getSystemService(NotificationManager::class.java)
        val examples = listOf(
            Triple("post", "토닥 · 새 소식", "손녀 정아님이 게시글을 올렸어요!"),
            Triple("comment", "할머니 경자", "사진이 참 예쁘구나! 다음에는 할머니도 같이 가자 💛"),
            Triple("answer", "할머니 경자", "오늘의 질문에 답했어요!\nQ. 오늘 가장 고마웠던 일은 무엇인가요?"),
        )
        for ((kind, title, body) in examples) {
            val id = "phone-preview-$kind"
            manager.cancel(id, 0)
            assertTrue(TodakNotifications.show(context, mapOf(
                "event_id" to id, "kind" to kind, "title" to title, "body" to body,
                "binding" to "visual-preview-only", "user_id" to "0",
                "room_id" to "0", "post_id" to "0", "question_id" to "")))
            val deadline = android.os.SystemClock.uptimeMillis() + TestTiming.UI_TIMEOUT_MS
            while (manager.activeNotifications.none { it.tag == id } &&
                android.os.SystemClock.uptimeMillis() < deadline) Thread.sleep(100)
            assertNotNull(manager.activeNotifications.firstOrNull { it.tag == id })
            Thread.sleep(1000)
        }
    }
}
