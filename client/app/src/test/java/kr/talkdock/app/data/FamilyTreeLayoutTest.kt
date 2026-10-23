package kr.talkdock.app.data

import org.junit.Assert.*
import org.junit.Test

class FamilyTreeLayoutTest {
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
