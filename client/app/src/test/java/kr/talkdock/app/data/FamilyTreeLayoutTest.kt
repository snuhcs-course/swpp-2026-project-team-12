package kr.talkdock.app.data

import org.junit.Assert.*
import org.junit.Test
import org.json.JSONObject

class FamilyTreeLayoutTest {
    @Test fun spouseAddedAfterThreeSiblingsDoesNotConnectThroughAnotherPerson() {
        val draft = FamilyTreeDraft(JSONObject("""{"version":0,"owner_id":"1","people":[
            {"id":"1","name":"부모","gender":"male","generation":0,"user_id":1}],"parents":[],"partnerships":[]}"""))
        val children = List(3) { draft.add("1", "child") }
        val before = FamilyTreeLayout.drawing(draft)
        val spouse = draft.add(children.first(), "spouse")
        for (editable in listOf(false, true)) {
            val drawing = FamilyTreeLayout.drawing(draft, editable)
            val route = FamilyTreeLayout.connection(drawing, children.first(), spouse)
            assertEquals(drawing.points.getValue(children.first()), route.first())
            assertEquals(drawing.points.getValue(spouse), route.last())
            drawing.nodes.filter { it.id !in setOf(children.first(), spouse) }.forEach { node ->
                val p = drawing.points.getValue(node.id)
                // Cover the larger web card too, so both clients follow the same clear route.
                val left = p.x - 60f; val right = p.x + 60f; val top = p.y - 55f; val bottom = p.y + 69f
                route.zipWithNext().forEach { (a, b) ->
                    val crosses = if (a.y == b.y) a.y in top..bottom && maxOf(a.x, b.x) >= left && minOf(a.x, b.x) <= right
                        else a.x in left..right && maxOf(a.y, b.y) >= top && minOf(a.y, b.y) <= bottom
                    assertFalse("Spouse connection crosses unrelated person ${node.id}", crosses)
                }
            }
            val oldOrigin = before.points.getValue("1"); val newOrigin = drawing.points.getValue("1")
            before.points.forEach { (id, p) ->
                val next = drawing.points.getValue(id)
                assertEquals(p.x - oldOrigin.x, next.x - newOrigin.x, .01f)
                assertEquals(p.y - oldOrigin.y, next.y - newOrigin.y, .01f)
            }
        }
    }
    @Test fun addingTenChildrenKeepsEarlierRelativePositionsAndUsesContextualActions() {
        val draft = FamilyTreeDraft(JSONObject("""{"version":0,"owner_id":"1","people":[
            {"id":"1","name":"부모","gender":"male","generation":0,"user_id":1}],"parents":[],"partnerships":[]}"""))
        var before = FamilyTreeLayout.drawing(draft)
        repeat(10) {
            draft.add("1", "child")
            val after = FamilyTreeLayout.drawing(draft)
            val oldOrigin = before.points.getValue("1"); val newOrigin = after.points.getValue("1")
            before.points.forEach { (id, point) ->
                val next = after.points.getValue(id)
                assertEquals(point.x - oldOrigin.x, next.x - newOrigin.x, .01f)
                assertEquals(point.y - oldOrigin.y, next.y - newOrigin.y, .01f)
            }
            assertTrue(after.nodes.none { it.action != null })
            before = after
        }
        assertEquals(11, before.nodes.size)
        assertTrue(FamilyTreeLayout.actions(draft, "1").none { it.relation == "child" })
        val child = draft.childrenOf("1").first()
        assertTrue(FamilyTreeLayout.actions(draft, child).all { it.anchor == child })
    }
    @Test fun largeFamilyHasDistinctSlotsAndCorrectGenerations() {
        val nodes = (0..40).map { TreeDisplayNode("p$it", "가족 $it", -it / 5, "unknown") }
        val parents = (1..40).filter { nodes[it].generation < nodes[(it - 1) / 2].generation }
            .map { TreeParent("p${(it - 1) / 2}", "p$it") }
        val drawing = FamilyTreeLayout.arrange(nodes, parents, emptyList())
        assertEquals(41, drawing.points.size)
        nodes.groupBy { it.generation }.values.forEach { row ->
            val xs = row.map { drawing.points.getValue(it.id).x }.sorted()
            xs.zipWithNext().forEach { (a, b) -> assertTrue("Nodes must not overlap", b - a >= 100f) }
        }
        assertTrue(drawing.height > 1000f)
        assertTrue(drawing.points.getValue("p0").y < drawing.points.getValue("p40").y)
    }

    @Test fun parentsStaySideBySideAboveTheirChildren() {
        val nodes = listOf(TreeDisplayNode("dad", "아빠", 1, "male"), TreeDisplayNode("mom", "엄마", 1, "female"),
            TreeDisplayNode("child", "아이", 0, "unknown"))
        val drawing = FamilyTreeLayout.arrange(nodes, listOf(TreeParent("dad", "child"), TreeParent("mom", "child")), emptyList())
        val dad = drawing.points.getValue("dad"); val mom = drawing.points.getValue("mom")
        assertEquals(dad.y, mom.y, 0.01f)
        assertTrue(dad.x < mom.x)
        assertTrue(drawing.points.getValue("child").y > dad.y)
    }
}
