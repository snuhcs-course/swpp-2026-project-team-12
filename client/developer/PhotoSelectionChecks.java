import java.util.List;
import kr.talkdock.app.ui.PhotoSelection;

/** Run against the production selection model; no Android SDK/JUnit required. */
public final class PhotoSelectionChecks {
    private static int checks;
    private static void expect(boolean condition, String description) {
        if (!condition) throw new AssertionError(description);
        checks++;
    }
    private static void order(PhotoSelection model, String... expected) {
        expect(model.getSelected().equals(List.of(expected)), "Wrong upload order: " + model.getSelected());
        for (int i = 0; i < expected.length; i++) {
            expect(model.numberOf(expected[i]) == i + 1, "Wrong badge for " + expected[i]);
        }
    }
    public static void main(String[] args) {
        PhotoSelection model = new PhotoSelection();
        expect(!model.isMultiple(), "Default must be single selection");
        order(model);
        model.tap("A"); model.tap("B"); order(model, "B");
        expect("B".equals(model.getPreview()), "Preview must follow selected photo");
        model.tap("B"); order(model);
        expect(model.getPreview() == null, "Deselecting the last photo must clear preview");
        model.tap("A"); model.setMultiple(true); order(model, "A");
        model.tap("C"); model.tap("B"); order(model, "A", "C", "B");
        model.tap("C"); order(model, "A", "B");
        expect(model.numberOf("C") == 0, "Deselected photo must have no badge");
        model.tap("C"); order(model, "A", "B", "C");
        model.tap("D"); model.tap("E");
        expect(!model.tap("F"), "Sixth photo must be rejected");
        order(model, "A", "B", "C", "D", "E");
        expect("E".equals(model.getPreview()), "Rejected photo must not change preview");
        expect(model.tap("B"), "Deselecting at the limit must remain possible");
        expect(model.tap("F"), "Freed slot must be reusable");
        order(model, "A", "C", "D", "E", "F");
        model.setMultiple(false); order(model, "F");
        model.setMultiple(true); model.tap("D"); model.tap("D");
        expect("F".equals(model.getPreview()), "Removing preview must show a remaining selection");
        PhotoSelection restored = new PhotoSelection();
        restored.restore(true, List.of("A", "C", "B"), "C"); order(restored, "A", "C", "B");
        expect(restored.isMultiple() && "C".equals(restored.getPreview()), "Rotation state must retain mode and preview");
        restored.retainAvailable(List.of("A", "B")); order(restored, "A", "B");
        expect("B".equals(restored.getPreview()), "Revoked photo must not remain the preview");
        restored.getSelected().clear(); order(restored, "A", "B");
        restored.restore(true, List.of("A", "A", "B", "C", "D", "E", "F"), "F");
        order(restored, "A", "B", "C", "D", "E");
        restored.restore(false, List.of("A", "B"), "B"); order(restored, "A");
        restored.retainAvailable(List.of()); order(restored);
        expect(restored.getPreview() == null, "Revoked library must clear preview");
        System.out.println("PASS: " + checks + " selection assertions");
    }
}
