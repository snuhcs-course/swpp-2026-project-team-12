package kr.talkdock.app

import androidx.test.ext.junit.runners.AndroidJUnit4
import kr.talkdock.app.data.*
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class FamilyTreeDraftTest {
    private fun snapshot() = JSONObject("""{"version":3,"owner_id":"1","people":[{"id":"1","name":"준하","gender":"male","generation":0,"user_id":7}],"parents":[],"partnerships":[]}""")

    @Test fun expandThroughBlankSiblingAndSelectOnlyAfterAdding() {
        val draft = FamilyTreeDraft(snapshot())
        val father = draft.add("1", "father")
        val mother = draft.add("1", "mother")
        val sibling = draft.add(father, "child", mother)
        val nephew = draft.add(sibling, "child")
        assertNull(draft.selectedId)
        draft.selectedId = nephew
        assertEquals(setOf(father, mother), draft.parentsOf(sibling).toSet())
        val drawing = FamilyTreeLayout.drawing(draft)
        assertTrue(drawing.nodes.filter { it.action != null }.all { draft.people.containsKey(it.action!!.anchor) })
        assertEquals(drawing.nodes.size, drawing.points.size)
        val restored = FamilyTreeDraft(snapshot()).apply { restore(draft.payload()) }
        assertEquals(nephew, restored.selectedId)
        assertEquals(draft.parents, restored.parents)
        restored.undo()
        assertNull(restored.selectedId)
        assertFalse(restored.people.containsKey(nephew))
        assertTrue(restored.people.containsKey(sibling))
    }
}
