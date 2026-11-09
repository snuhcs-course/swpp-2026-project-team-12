package kr.talkdock.app.data

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

/** Pure draft logic; runs on the JVM with the org.json test dependency. */
class FamilyTreeDraftTest {
    private fun snapshot() = JSONObject("""{"version":3,"owner_id":"1","people":[
        {"id":"1","name":"준하","gender":"male","generation":0,"user_id":7},
        {"id":"2","name":"","gender":"unknown","generation":-1,"user_id":null}],
        "parents":[{"parent_id":"1","child_id":"2"}],"partnerships":[]}""")

    @Test fun snapshotKeepsVersionOwnerAndOccupiedPeople() {
        val draft = FamilyTreeDraft(snapshot())
        assertEquals(3, draft.version)
        assertEquals("1", draft.ownerId)
        assertTrue(draft.people.getValue("1").occupied)
        assertFalse(draft.people.getValue("2").occupied)
        assertEquals(listOf("1"), draft.parentsOf("2"))
    }

    @Test fun expandThroughBlankSiblingAndSelectOnlyAfterAdding() {
        val draft = FamilyTreeDraft(snapshot())
        val father = draft.add("1", "father")
        val mother = draft.add("1", "mother")
        val sibling = draft.add(father, "child", mother)
        val nephew = draft.add(sibling, "child")
        assertNull(draft.selectedId)
        draft.selectedId = nephew
        assertEquals(setOf(father, mother), draft.parentsOf(sibling).toSet())
        assertEquals(listOf(mother), draft.coParentsOf(father))
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

    @Test fun relationsSetGenerationAndGender() {
        val draft = FamilyTreeDraft(snapshot())
        val father = draft.people.getValue(draft.add("1", "father"))
        val mother = draft.people.getValue(draft.add("1", "mother"))
        val parent = draft.people.getValue(draft.add("1", "parent"))
        val child = draft.people.getValue(draft.add("1", "child"))
        val spouse = draft.add("1", "spouse")
        assertEquals(listOf(1, 1, 1, -1), listOf(father, mother, parent, child).map { it.generation })
        assertEquals(listOf("male", "female", "unknown", "unknown"), listOf(father, mother, parent, child).map { it.gender })
        assertEquals(0, draft.people.getValue(spouse).generation)
        assertEquals(listOf(spouse), draft.partnersOf("1"))
        assertTrue(draft.coParentsOf("1").contains(spouse))
    }

    @Test fun payloadListsAdditionsAndNullSelection() {
        val draft = FamilyTreeDraft(snapshot())
        val child = draft.add("1", "child", "2")
        val payload = draft.payload()
        assertEquals(3, payload.getInt("tree_version"))
        assertTrue(payload.isNull("person_id"))
        val addition = payload.getJSONArray("additions").getJSONObject(0)
        assertEquals(child, addition.getString("id"))
        assertEquals("1", addition.getString("anchor_id"))
        assertEquals("child", addition.getString("relation"))
        assertEquals("2", addition.getString("co_parent_id"))
        draft.add("1", "father")
        assertFalse(draft.payload().getJSONArray("additions").getJSONObject(1).has("co_parent_id"))
        draft.selectedId = child
        assertEquals(child, draft.payload().getString("person_id"))
    }

    @Test fun undoOnEmptyDraftAndUnknownRestoredSelectionAreIgnored() {
        val draft = FamilyTreeDraft(snapshot())
        draft.undo()
        assertEquals(2, draft.people.size)
        draft.restore(JSONObject().put("person_id", "missing"))
        assertNull(draft.selectedId)
        draft.restore(JSONObject())
        assertTrue(draft.additions.isEmpty())
    }

    @Test fun additionsStopAtTwoHundred() {
        val draft = FamilyTreeDraft(snapshot())
        repeat(200) { draft.add("1", "child") }
        val error = assertThrows(IllegalArgumentException::class.java) { draft.add("1", "child") }
        assertEquals("한 번에 추가할 수 있는 가족은 200명까지예요.", error.message)
        assertEquals(200, draft.additions.size)
    }
}
