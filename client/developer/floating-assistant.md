# Floating assistant

`MainActivity` attaches one `FloatingAssistantView` above the page on the feed,
post detail, family memory, and main family/settings screens. It is outside the
scrolling content. Navigation dismisses the popup, clears old card references,
and attaches a new button while keeping its saved placement.

## Placement and post scope

- Default: right edge, 62% of the available vertical travel.
- Character artwork and touch area are 20% larger than the original 76×88dp
  button (approximately 91.2×105.6dp); docking and saved placement still adapt.
- Drag vertically or across the screen; release snaps to the nearer left/right
  edge. A drag does not open the popup. Cancellation restores the prior anchor.
- The edge and relative height are saved in `talkdock-assistant` device preferences.
  Relative placement adapts to rotation, screen chrome and keyboard insets.
- Accessibility actions provide left/right/up/down movement without dragging.
- The left edge uses the source character direction; the right edge mirrors the
  image horizontally. Dragging across the viewport midpoint updates the direction;
  cancelling a drag restores it along with the saved placement.
- The **center of the visible feed viewport**, independently of the character's
  position, selects the current post. Use the card containing the center, or the
  nearest visible card when the center falls between cards. Offscreen cards are
  excluded. Empty feeds and other screens use family-wide context.
- Post detail always uses its own post, including when scrolling its comments.

`AssistantPlacement` holds the pure geometry and post-selection rules.
`FloatingAssistantView` owns touch handling and persistence. `MainActivity`
registers feed card bounds and connects the selected post to the popup.

## Requests

The character toggles an in-page `AssistantBubbleMenu`, without a modal window.
Three separately sized rounded balloons use RGB(193, 232, 251), sampled
from the bundled character's blue torso, with a subtle outline. Text is right
aligned, 13sp normally and 16sp in large-text mode. Visible pills are compact,
while their enclosing rows keep 48dp/56dp touch targets. The column is at most
224dp/260dp wide, attached to the actual visible artwork rather than the PNG's
transparent canvas, with no horizontal gap. Short balloons align
against the character: right aligned beside a right-docked character, mirrored
beside a left-docked character. The menu stays inside visible content bounds.
The character remains tappable to close the menu; Back also closes it first.
Crossing the drag threshold closes it immediately, including a cancelled drag;
accessible movement also closes it. Navigation, loading and leaving the foreground
dismiss the menu.

While the character's menu is open, `PostFocusHighlight` keeps the current post at
its original brightness and shades the rest of the page with a 40% translucent
gray layer. The original post borders are never changed. Closing the menu,
choosing an option or starting a character drag immediately removes the contrast.
The rounded cutout is intersected with the card's visible scroll area so fixed
headers remain shaded even when the card extends offscreen. The layer is inserted
above the page and below the assistant/menu, never accepts touch or accessibility
focus, and follows the card as the feed scrolls. Changing the centered post restores
the old card and moves the clear area. Detail screens highlight their own post.
Pausing, loading or navigating also removes the layer.

Options are "이 글에 대해 궁금하세요?", "가족의 지난 추억이 궁금하세요?" and
"오늘 가족의 하루". Post questions are disabled when no post is selected. The
menu follows the feed's current post until an option is chosen; then the chosen
post and API client are captured for that conversation. Questions reuse
`PostQuestionPanel`; family history reuses `FamilyMemoryPanel`. Choosing the digest
closes the balloon and opens the existing digest screen.

Opening, dragging and scrolling never start AI requests. Only submitting a
question calls the existing question APIs. Closing a conversation or navigating
detaches its panels and cancels their work.
This change does not add STT/TTS controls or start background workers.

The main feed begins with family posts: the memory-search shortcut, writing hero
card and daily-digest shortcut have been removed. Writing remains in the header.
The assistant balloon provides the memory and digest shortcuts.

## Character asset

`app/src/main/res/drawable-nodpi/assistant_character.png` contains the transparent
cutout from the supplied `character.png`. Only the floating assistant uses this
asset; existing Todak illustrations on other screens keep their own resources.
The button has no background plate, border or shadow. The original asset faces
right from the left edge; `ImageView.scaleX` mirrors it when docked on the right.
Horizontal viewport inset is zero. An image matrix aligns the PNG's straight
torso cut (x=50 on its 1151px source canvas) with the button edge, excluding the
transparent source margin and fit-center letterboxing. The drawing keeps its
aspect ratio; mirroring places the same torso cut against the right edge.
Vertical clearance, drag bounds and saved relative height remain unchanged.

The cutout was produced with the built-in image generation/editing tool with
transparent background enabled. Prompt:

> Use case: background-extraction. Input image: edit target. Extract ONLY the existing smiling child character wearing a pale blue hooded snowsuit and coral scarf, waving a hand, from the supplied image into a transparent PNG for a mobile floating assistant button. Remove the off-white paper background, outer white border, and the long vertical brown line to the left outside the character. Preserve the character's exact existing face, expression, pose, silhouette, brown textured outlines, blue clothing, scarf, buttons, skin colors, original hand drawn texture and orientation. The child is peeking from the LEFT edge and waving toward the RIGHT: keep this direction unchanged. Preserve the straight cropped left boundary of the existing character; do not invent missing limbs or restore hidden portions. Keep the character fully within the canvas with a small transparent margin, tightly framed around the character rather than the removed vertical line. All areas outside the character including gaps between arm and body must be actual alpha transparency. No shadow, no background, no text, no added objects, no redesign.

## Validation

```sh
./gradlew :app:testDebugUnitTest :app:assembleDebug
./gradlew :app:connectedDebugAndroidTest \
  -Pandroid.testInstrumentationRunnerArguments.class=kr.talkdock.app.FloatingAssistantTest
```

The unit tests cover docking, bounds, relative placement and centered post
selection. Device tests use a synthetic feed and local mock server to verify
scroll tracking, drag/cancel behavior, accessible moves, saved placement after
recreation, and freezing a popup's post while the underlying feed changes.
They also cover actual character taps to toggle the menu, three independently
drawn right-aligned balloons, viewport bounds, drag/accessibility dismissal,
current-card emphasis changes, the 20% size increase, gestures/header taps through
the gray layer, Back dismissal, memory search and digest navigation.
They restore the device's existing session and placement preferences and do not
call external AI services or create real posts.
