package kr.talkdock.app.ui

import org.junit.Assert.*
import org.junit.Test

/** The gallery's selection rules; PhotoSelection has no Android dependencies. */
class PhotoSelectionTest {
    @Test fun singleModeReplacesTheSelection() {
        val selection = PhotoSelection()
        assertTrue(selection.tap("a"))
        assertTrue(selection.tap("b"))
        assertEquals(listOf("b"), selection.selected)
        assertEquals("b", selection.preview)
        assertFalse(selection.isMultiple)
    }

    @Test fun multipleModeKeepsTapOrderAndStopsAtFive() {
        val selection = PhotoSelection().apply { isMultiple = true }
        listOf("a", "b", "c", "d", "e").forEach { assertTrue(selection.tap(it)) }
        assertFalse("A sixth photo must be rejected", selection.tap("f"))
        assertEquals(listOf("a", "b", "c", "d", "e"), selection.selected)
        assertEquals(3, selection.numberOf("c"))
        assertEquals(0, selection.numberOf("f"))
        assertEquals("e", selection.preview)
    }

    @Test fun deselectingMovesThePreviewToTheLastSelectedPhoto() {
        val selection = PhotoSelection().apply { isMultiple = true }
        listOf("a", "b", "c").forEach { selection.tap(it) }
        assertTrue(selection.tap("c"))
        assertEquals(listOf("a", "b"), selection.selected)
        assertEquals("b", selection.preview)
        assertTrue(selection.tap("a"))
        assertEquals("b", selection.preview)
        selection.tap("b")
        assertNull(selection.preview)
        assertTrue(selection.selected.isEmpty())
    }

    @Test fun leavingMultipleModeKeepsOnlyThePreviewedPhoto() {
        val selection = PhotoSelection().apply { isMultiple = true }
        listOf("a", "b", "c").forEach { selection.tap(it) }
        selection.tap("b"); selection.tap("b")
        selection.isMultiple = false
        assertEquals(listOf("b"), selection.selected)
        assertEquals("b", selection.preview)
    }

    @Test fun retainAvailableDropsMissingPhotos() {
        val selection = PhotoSelection().apply { isMultiple = true }
        listOf("a", "b", "c").forEach { selection.tap(it) }
        selection.retainAvailable(listOf("a", "b"))
        assertEquals(listOf("a", "b"), selection.selected)
        assertEquals("b", selection.preview)
        selection.retainAvailable(emptyList())
        assertNull(selection.preview)
    }

    @Test fun restoreDeduplicatesAndRespectsTheModeLimit() {
        val selection = PhotoSelection()
        selection.restore(true, listOf("a", "a", null, "b", "c", "d", "e", "f"), "c")
        assertEquals(listOf("a", "b", "c", "d", "e"), selection.selected)
        assertEquals("c", selection.preview)
        selection.restore(false, listOf("x", "y"), "y")
        assertEquals(listOf("x"), selection.selected)
        assertEquals("x", selection.preview)
        selection.restore(true, emptyList(), "z")
        assertNull(selection.preview)
    }

    @Test fun returnedListsAreCopies() {
        val selection = PhotoSelection()
        selection.tap("a")
        (selection.selected as MutableList<String>).clear()
        assertEquals(listOf("a"), selection.selected)
    }
}
