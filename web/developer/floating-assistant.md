# Web floating assistant

The character button is a 96px circle (1.5 times the original size) using the same transparent PNG as Android,
cropped in CSS to show its face. It starts at the bottom-right and can be freely dragged
to any position inside the viewport, without edge snapping. Tapping opens a non-modal conversation panel titled
**이 글에 대해 궁금하세요?** and hides the circular launcher. Closing the panel restores
the launcher at its saved position. Focus moves into the panel on opening and returns
to the launcher on closing. Dragging the closed launcher only moves it.
There is no target-post strip or intermediate speech-bubble menu. A six-second
CSS animation moves a soft blue/white/gold highlight and a small sparkle around
the border. The character remains stationary; reduced-motion preferences stop
the orbit. Drag boundaries use the same 96px size as the rendered button.

## Selection and emphasis

Each feed card carries `data-post-id`. `centeredPost` ignores cards outside the
viewport, then chooses the visible card whose visible portion is closest to the
viewport center. The visible topbar is excluded. Ties retain the previous post.
Scrolls, viewport changes, feed filtering/replacement, and image loads schedule
one geometry update per animation frame. Neither scrolling nor opening sends AI
requests. A fixed, rounded transparent rectangle with a large gray shadow keeps
the selected card bright without changing the card border or stacking order.
The shade ignores all pointer events, so feed scrolling and buttons keep working.

Only the feed shows the assistant. Native detail/composer dialogs and other pages
hide it. Closing via the close button, Escape, or navigation removes
the shade. An empty/filtered-out feed shows guidance and disables question input.

## Conversation lifetime

`PostConversations` is independent of the DOM. Its scope is account ID plus room ID.
Each post owns a draft, successful user/assistant turns, scroll position, pending
question, and error. Scroll changes the displayed entry immediately, including an
in-progress draft. Closing/reopening retains entries within this page session.
Reloading drops conversation contents; switching accounts/rooms or logging out
also discards them and invalidates pending results.

Submitting captures the post and room IDs; the existing authenticated
`POST /api/posts/{id}/questions/` receives that room explicitly and at most ten
successful prior turns. Duplicate submissions are blocked per post, while other
posts may ask independently. Late results update only their original entry, never
the currently viewed post. Failed or empty answers preserve the exact draft and
do not enter history. Edits made while a response is pending are also preserved.
Only geometry is stored on disk under `talkdock.web.assistant.layout.v1`.

## Layout and controls

The desktop panel starts at 400 × 540 CSS pixels next to the character, within the
viewport. Its title is a drag handle. All four edges and corners resize it, with a
320 × 300 minimum where space permits. Arrow keys move the focused title or
character and resize focused handles; Shift uses a larger step. The header only has
the close button; resizing uses the edges/corners. Geometry is saved after gestures
and keyboard changes, and clamped on viewport changes and restoration. Character
positions store horizontal and vertical ratios, so interior positions survive
viewport resizing. Legacy left/right placement settings are migrated on load.

At widths up to 640px the panel uses a bottom layout, at most 65% of the visual
viewport height. Panel move/resize controls are disabled there; the character keeps
its freely chosen position. Visual viewport changes also accommodate keyboard/zoom
changes. Reduced-motion preferences stop the thinking-dot animation.

## Verification

Automated checks:

```sh
node --check web/assets/app.js
node --check web/assets/floating-assistant.js
node --test web/test_family_tree.mjs web/test_images.mjs web/test_usability.mjs web/test_assistant.mjs
python backend/manage.py test web
```

The assistant tests cover viewport selection, offscreen/empty feeds, geometry
bounds, per-post drafts, late replies, independent pending requests, room/account
isolation, failed-answer retry, history limits, and edits during a pending request.
The Django tests also check that the new modules and PNG are served under the
existing explicit asset allowlist and CSP.

Browser checks use synthetic family posts and a local fixture API (no external AI):
open/close, gray cutout following scrolling, returning to a post's draft and answer,
late-answer isolation, failed-request retry, title dragging, corner resizing,
saved geometry after reload, empty-filter handling, free character placement, keyboard
controls, navigation, and the 390px mobile breakpoint.

The local web/API server uses the normal `python web/run.py --port 8000` launcher.
Use the existing local account to sign in. Deployment to talkdock.app is a separate
step; editing these files does not update that server automatically.
