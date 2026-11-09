package kr.talkdock.app

import android.content.Intent
import android.graphics.Rect
import android.os.SystemClock
import android.os.ParcelFileDescriptor
import android.view.InputDevice
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.view.accessibility.AccessibilityNodeInfo
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import kr.talkdock.app.data.FamilyTreeDraft
import kr.talkdock.app.ui.FamilyTreeView
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

@RunWith(AndroidJUnit4::class)
class FamilyTreeViewTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val automation get() = instrumentation.uiAutomation
    private fun nodes(root: AccessibilityNodeInfo?): List<AccessibilityNodeInfo> =
        if (root == null) emptyList() else listOf(root) + (0 until root.childCount).flatMap { nodes(root.getChild(it)) }
    private fun waitNode(predicate: (AccessibilityNodeInfo) -> Boolean): AccessibilityNodeInfo {
        val until = SystemClock.uptimeMillis() + 8000
        do {
            nodes(automation.rootInActiveWindow).firstOrNull { it.isVisibleToUser && predicate(it) }?.let { return it }
            SystemClock.sleep(100)
        } while (SystemClock.uptimeMillis() < until)
        error("Expected control was not visible")
    }
    private fun screenshot(name: String) {
        val image = automation.takeScreenshot() ?: error("Screenshot unavailable")
        File(instrumentation.targetContext.filesDir, name).outputStream().use {
            image.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, it)
        }
        image.recycle()
    }

    private fun board(view: View): FamilyTreeView? = if (view is FamilyTreeView) view else
        (view as? ViewGroup)?.let { group -> (0 until group.childCount).firstNotNullOfOrNull { board(group.getChildAt(it)) } }

    private fun pinch(view: FamilyTreeView, from: Float, to: Float) {
        val down = SystemClock.uptimeMillis()
        val properties = Array(2) { id -> MotionEvent.PointerProperties().apply { this.id = id; toolType = MotionEvent.TOOL_TYPE_FINGER } }
        var time = down
        fun send(action: Int, count: Int, span: Float) {
            val points = Array(count) { index -> MotionEvent.PointerCoords().apply {
                x = view.width / 2f + (if (index == 0) -span else span) * view.resources.displayMetrics.density / 2f
                y = view.height / 2f; pressure = 1f; size = 1f
            } }
            val event = MotionEvent.obtain(down, time, action, count, properties, points,
                0, 0, 1f, 1f, 0, 0, InputDevice.SOURCE_TOUCHSCREEN, 0)
            view.dispatchTouchEvent(event); event.recycle(); time += 16
        }
        send(MotionEvent.ACTION_DOWN, 1, from)
        send(MotionEvent.ACTION_POINTER_DOWN or (1 shl MotionEvent.ACTION_POINTER_INDEX_SHIFT), 2, from)
        for (step in 1..12) send(MotionEvent.ACTION_MOVE, 2, from + (to - from) * step / 12f)
        send(MotionEvent.ACTION_POINTER_UP or (1 shl MotionEvent.ACTION_POINTER_INDEX_SHIFT), 2, to)
        send(MotionEvent.ACTION_UP, 1, to)
    }

    @Test fun familyTreeSupportsSelectionPanningPinchingAndReadOnlyViewing() {
        val context = instrumentation.targetContext
        context.getSharedPreferences("talkdock-session", 0).edit().clear().commit()
        val draft = FamilyTreeDraft(JSONObject("""{"version":0,"owner_id":"1","people":[
            {"id":"1","name":"김대협","gender":"male","generation":0,"user_id":1},
            {"id":"2","name":"함준하","gender":"male","generation":-1,"user_id":2},
            {"id":"3","name":"이장하","gender":"unknown","generation":-2,"user_id":3},
            {"id":"4","name":"홍정아","gender":"female","generation":-2,"user_id":4}],
            "parents":[{"parent_id":"1","child_id":"2"},{"parent_id":"2","child_id":"3"},{"parent_id":"2","child_id":"4"}],"partnerships":[]}"""))
        val activity = instrumentation.startActivitySync(Intent(context, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK))
        try {
            // Inject only the invitation snapshot; all controls and handlers below
            // are the production MainActivity screen, with no network dependency.
            instrumentation.runOnMainSync {
                fun field(name: String, value: Any) = MainActivity::class.java.getDeclaredField(name).apply { isAccessible = true }.set(activity, value)
                field("session", JSONObject().put("user_id", 9).put("name", "구본재").put("gender", "male"))
                field("treeDraft", draft)
                MainActivity::class.java.getDeclaredMethod("tree").apply { isAccessible = true }.invoke(activity)
            }
            val father = waitNode { it.contentDescription?.toString() == "김대협의 아버지 추가" }
            screenshot("tree-before.png")
            assertTrue(father.performAction(AccessibilityNodeInfo.ACTION_CLICK))
            val blank = waitNode { it.contentDescription?.toString() == "빈 가족, 내 자리로 선택 가능" }
            assertNull(draft.selectedId)
            assertEquals(1, draft.additions.size)
            assertTrue(blank.performAction(AccessibilityNodeInfo.ACTION_CLICK))
            assertTrue(waitNode { it.text?.toString() == "내 자리로 선택" }.performAction(AccessibilityNodeInfo.ACTION_CLICK))
            automation.waitForIdle(300, 3000)
            val selected = waitNode { it.contentDescription?.toString() == "구본재, 내 자리로 선택 가능" }
            assertNotNull(draft.selectedId)
            val before = Rect().also { selected.getBoundsInScreen(it) }
            val swipe = "input swipe ${before.centerX()} ${before.centerY()} ${before.centerX() - 100} ${before.centerY() - 80} 500"
            ParcelFileDescriptor.AutoCloseInputStream(automation.executeShellCommand(swipe)).use { it.readBytes() }
            instrumentation.waitForIdleSync()
            val after = Rect().also { waitNode { it.contentDescription?.toString() == "구본재, 내 자리로 선택 가능" }.getBoundsInScreen(it) }
            screenshot("tree-selected.png")
            assertTrue("Dragging must pan the tree: $before -> $after", before != after)
            assertEquals("Dragging must not add a node", 1, draft.additions.size)
            instrumentation.runOnMainSync {
                val tree = board(activity.findViewById(android.R.id.content))!!
                val world = tree.getChildAt(0)
                pinch(tree, 100f, 260f)
                assertTrue("Pinch out must enlarge the tree", world.scaleX > 1f)
                val enlarged = world.scaleX
                pinch(tree, 260f, 80f)
                assertTrue("Pinch in must shrink the tree", world.scaleX < enlarged)
                assertEquals("Pinching must not add people", 1, draft.additions.size)
                assertNotNull("Pinching must keep the selected person", draft.selectedId)
                val room = JSONObject().put("tree", draft.snapshot).put("members", JSONArray().put(
                    JSONObject().put("id", 9).put("person_id", "2")))
                MainActivity::class.java.getDeclaredField("room").apply { isAccessible = true }.set(activity, room)
                MainActivity::class.java.getDeclaredMethod("familyTree").apply { isAccessible = true }.invoke(activity)
            }
            instrumentation.waitForIdleSync()
            instrumentation.runOnMainSync {
                val tree = board(activity.findViewById(android.R.id.content))!!
                val world = tree.getChildAt(0) as ViewGroup
                assertEquals("Viewing must omit add buttons", 4, world.childCount)
                assertTrue((0 until world.childCount).none { world.getChildAt(it).isClickable })
                pinch(tree, 100f, 260f)
                assertTrue("The settings tree must also support zoom", world.scaleX > 1f)
            }
            screenshot("tree-viewer-zoomed.png")
        } finally { instrumentation.runOnMainSync { activity.finish() } }
    }
}
