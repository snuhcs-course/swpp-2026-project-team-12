# Photo-letter floating assistant

The assistant keeps the existing transparent child mascot and is rendered as a small 60 × 72dp overlay on home and post detail, docked against either screen edge without horizontal inset. The home footer shows the author's initials badge/name beside the date and reserves clearance on the assistant's current side. The initial position follows that footer. Dragging and the existing accessible move actions retain left/right docking and a saved relative height, stored under `talkdock-assistant-letter`. The complete character artwork fits inside its image view without cropping; the source PNG is unchanged.

The assistant is hidden while a profile or question dialog is open, during loading, and on the dedicated recording/daily/settings pages. A question dialog represents it with a header avatar. Its hit area remains larger than 56dp.

## Current-post identity

`PhotoLetterDeck.currentPost` supplies the home context directly. Swiping to another letter closes the menu and updates the assistant's post tag. Tapping the card opens the existing detail API and its multi-photo carousel. Detail uses its loaded `selectedPost`. The bot's drag position never selects a different post.

## Contextual popover

Tapping the mascot opens one white rounded popover with:

- **이 소식 물어보기** — disabled without a current post.
- **음성으로 듣기 / 듣기 중지** — prepares or stops the selected post's speech.
- **AI 요약 보기** — shows the selected post's summary without requesting speech.
- **가족 추억 찾기** — opens the existing family-memory search page.

The audio/summary actions open the selected post's detail when chosen from home. On detail they reuse its `InlinePostAudio` controller, including pending-request cancellation, errors and retry behavior. The detail header no longer duplicates these controls. Family-memory search has one combined notice about AI mistakes and posts that are still being organized.

Daily digest is reached through the **하루** tab rather than a duplicate assistant option. The popup fits within the viewport and follows left/right docking. A light clickable shade dismisses it when tapped; the bot or Back also closes it. Moving or navigating closes it. There is no automatic popup or recurring attention animation.

## Question sheet

Choosing a post question captures that post and API client for the conversation. A bottom-aligned sheet shows the bot avatar, close action, current-post cover/name, short dialogue, and a compact multiline text composer. The floating mascot is hidden until dismissal. This entry is separate from the family's **말로 답장하기** action.

Opening/moving the bot and paging posts do not start AI requests. Only submitting a question calls `posts/<id>/questions/`. `PostQuestionPanel` retains draft text on errors, disables duplicate sends, carries bounded prior dialogue, and cancels work when detached. Closing the sheet releases its thumbnail binding.

## Validation

`PhotoLetterDesignTest` covers the deck, real swipes, frozen post context, a mock question/answer request, and profile/daily navigation. `PhotoCarouselTest`, `RecorderTest`, and `CommentComposerTest` cover the reused photo, recording and draft-safety components. All use local fixtures rather than live AI requests. The current four-action menu and author-footer changes have only been checked visually; automated test updates and runs are deferred at the user's request.
