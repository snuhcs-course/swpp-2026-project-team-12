# Boy character refresh

The scarf-and-hood child is replaced throughout the existing character artwork with the brown-haired young boy from the user-provided family character sheet. Transparent assets were produced with the built-in image generation tool using that sheet as the identity reference:

- `app/src/main/assets/todak/td_art_grandchild.png`: 648 × 648 PNG, the boy alone.
- `app/src/main/assets/todak/td_art_together.png`: 768 × 768 PNG, grandmother with the boy.
- `app/src/main/assets/todak/td_art_grandchild_sad.png`: 648 × 648 PNG, a mildly disappointed boy for startup connection and feed error notices only. Waiting, ordinary empty states and success feedback retain the cheerful boy.

Existing artwork names and screen layouts are retained. This covers notices, welcome/empty states, family cards and waiting feedback. The separate grandmother artwork is retained.

Successful posts/comments now animate the same boy PNG with a brief native bounce and gentle rotation. The success screen still completes after three seconds. The view cancels and resets its animation when detached or hidden; system-disabled animations display the still image. The unused scarf-character GIF and still are removed.

No backend or app-icon change is part of this character refresh.

## Validation — 2026-10-25 KST

- Debug build and lint passed.
- Emulator checks use local mock data only.
- `PostingFeedbackTest` checks text/character separation, visible celebration movement, and animation cleanup after detachment.
- `ServerAvailabilityTest` checks the updated notices in both font sizes and successful manual recovery.
