package kr.talkdock.app

import android.content.Intent
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import kr.talkdock.app.device.Recorder
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

/** Exercises microphone permission, AAC/M4A recording and local cancellation. */
@RunWith(AndroidJUnit4::class)
class RecorderTest {
    @Test fun recordFinishAndCancel() {
        val test = InstrumentationRegistry.getInstrumentation()
        val context = test.targetContext
        test.uiAutomation.executeShellCommand("pm grant " + context.packageName + " android.permission.RECORD_AUDIO").close()
        val activity = test.startActivitySync(Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        test.waitForIdleSync()
        val recorder = Recorder(context) { fail("Unexpected recording limit") }
        var file: File? = null
        try {
            test.runOnMainSync { recorder.start() }
            assertTrue(recorder.active)
            Thread.sleep(800)
            test.runOnMainSync { file = recorder.finish() }
            assertFalse(recorder.active)
            assertTrue(file!!.length() > 100)
            assertEquals("ftyp", file!!.readBytes().copyOfRange(4, 8).toString(Charsets.US_ASCII))
            val before = context.cacheDir.listFiles()!!.filter { it.name.startsWith("reply-") }.toSet()
            test.runOnMainSync { recorder.start(); recorder.cancel() }
            assertFalse(recorder.active)
            assertEquals(before, context.cacheDir.listFiles()!!.filter { it.name.startsWith("reply-") }.toSet())
        } finally {
            test.runOnMainSync { recorder.close(); activity.finish() }
            file?.delete()
        }
    }
}
