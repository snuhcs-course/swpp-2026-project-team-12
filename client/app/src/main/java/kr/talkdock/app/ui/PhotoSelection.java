package kr.talkdock.app.ui;

import java.util.ArrayList;
import java.util.Collection;
import java.util.List;

/** Tap order is the upload order. No Android dependencies: executable on a plain JDK. */
public final class PhotoSelection {
    public static final int LIMIT = 5;
    private final ArrayList<String> selected = new ArrayList<>();
    private boolean multiple;
    private String preview;

    public boolean isMultiple() { return multiple; }
    public String getPreview() { return preview; }
    public List<String> getSelected() { return new ArrayList<>(selected); }
    public int numberOf(String uri) { return selected.indexOf(uri) + 1; }

    /** False means adding a sixth photo was rejected; deselection always works. */
    public boolean tap(String uri) {
        if (selected.remove(uri)) {
            if (uri.equals(preview)) preview = selected.isEmpty() ? null : selected.get(selected.size() - 1);
            return true;
        }
        if (multiple && selected.size() == LIMIT) return false;
        if (!multiple) selected.clear();
        selected.add(uri);
        preview = uri;
        return true;
    }

    public void setMultiple(boolean value) {
        multiple = value;
        if (!multiple && selected.size() > 1) {
            String keep = selected.contains(preview) ? preview : selected.get(0);
            selected.clear();
            selected.add(keep);
            preview = keep;
        }
    }

    public void retainAvailable(Collection<String> available) {
        selected.retainAll(available);
        if (!selected.contains(preview)) preview = selected.isEmpty() ? null : selected.get(selected.size() - 1);
    }

    public void restore(boolean multi, List<String> values, String shown) {
        selected.clear();
        multiple = multi;
        for (String value : values) {
            if (value != null && !selected.contains(value)) selected.add(value);
            if (selected.size() == (multi ? LIMIT : 1)) break;
        }
        preview = selected.contains(shown) ? shown : (selected.isEmpty() ? null : selected.get(0));
    }
}
