package kr.talkdock.app.ui

import org.junit.Assert.*
import org.junit.Test

class AssistantPlacementTest {
    private val viewport = AssistantBounds(8f, 80f, 392f, 720f)

    @Test fun startsOnTheRightAndPreservesRelativeHeightAcrossScreenSizes() {
        val anchor = AssistantAnchor()
        assertEquals(316f, AssistantPlacement.position(anchor, viewport, 76f, 88f).x, .01f)
        assertEquals(422.24f, AssistantPlacement.position(anchor, viewport, 76f, 88f).y, .01f)
        for (bounds in listOf(viewport, AssistantBounds(8f, 40f, 792f, 440f))) {
            val point = AssistantPlacement.position(anchor, bounds, 76f, 88f)
            assertEquals(.62f, (point.y - bounds.top) / (bounds.bottom - bounds.top - 88), .001f)
        }
    }

    @Test fun releasesSnapToEitherEdgeAndClampToTheVisibleArea() {
        val left = AssistantPlacement.dropped(-100f, -100f, viewport, 76f, 88f)
        assertEquals(AssistantAnchor(AssistantEdge.LEFT, 0f), left)
        assertEquals(AssistantPoint(8f, 80f), AssistantPlacement.position(left, viewport, 76f, 88f))
        val right = AssistantPlacement.dropped(1000f, 1000f, viewport, 76f, 88f)
        assertEquals(AssistantAnchor(AssistantEdge.RIGHT, 1f), right)
        assertEquals(AssistantPoint(316f, 632f), AssistantPlacement.position(right, viewport, 76f, 88f))
    }

    @Test fun shrinkingTheViewportNeverProducesAnInvalidDragRange() {
        val small = AssistantBounds(8f, 80f, 48f, 100f)
        val anchor = AssistantPlacement.dropped(10f, 90f, small, 76f, 88f)
        assertEquals(AssistantPoint(8f, 80f), AssistantPlacement.position(anchor, small, 76f, 88f))
    }

    @Test fun theCenterChoosesThePostEvenWhenItsOwnCenterIsOffscreen() {
        val ranges = listOf(AssistantPostRange(1, -100f, 500f), AssistantPostRange(2, 530f, 760f))
        assertEquals(1, AssistantPlacement.currentPost(ranges, viewport))
        // Only the feed moves; a moved character is deliberately not an input to this decision.
        assertEquals(2, AssistantPlacement.currentPost(ranges.map { it.copy(top = it.top - 250, bottom = it.bottom - 250) }, viewport))
    }

    @Test fun aGapChoosesTheNearestVisiblePostAndNeverAnOffscreenPost() {
        assertEquals(2, AssistantPlacement.currentPost(listOf(
            AssistantPostRange(99, -100f, 79f), AssistantPostRange(1, 100f, 250f),
            AssistantPostRange(2, 430f, 600f), AssistantPostRange(98, 721f, 900f)), viewport))
        assertNull(AssistantPlacement.currentPost(listOf(AssistantPostRange(1, -20f, 50f)), viewport))
        assertNull(AssistantPlacement.currentPost(emptyList(), viewport))
    }
}
