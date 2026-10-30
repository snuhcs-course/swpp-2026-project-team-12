# Family history evidence posts

Family history answers now show original posts below “이 이야기가 담긴 소식”.
`MainActivity.feedPost` renders both the home feed and evidence: author, date,
unabridged caption, ordered photo carousel, comments, summary and audio actions.
Tapping a post or its comments opens the existing detail screen. Back returns to
the saved answer, draft, evidence list and vertical scroll position. This also
works after activity recreation on the detail screen. Saved results are scoped
to account, family room and server.

## API and compatibility

The history endpoint preserves `text`, `query` and `memories`, and adds
`source_episode_ids`, `evidence_posts` and `evidence_kind`:

- The new history answer uses one structured model response to select IDs from
  the retrieved source episodes. Unknown IDs are discarded. Post IDs and URLs
  are never accepted from generated answer text.
- The HTTP layer resolves only exact `post_<id>` episode names, queries the
  current family room, deduplicates posts, excludes deleted posts and reuses the
  feed serializer. Citation order determines post order. No migration is needed.
- The APK also works with the existing deployed endpoint: if `evidence_posts`
  is absent, it resolves the existing `memories[].sources[].name` provenance via
  authenticated post detail requests with the same captured family room. This
  path is labelled “답변을 만들 때 검색한 소식이에요.”, rather than claiming that
  the old model explicitly cited every result. It never searches unrelated feed
  posts by keywords or guesses IDs from the answer.
- An explicit empty `evidence_posts` array does not fall back to uncited results.
  Missing/forbidden posts are omitted; transient evidence loading errors retain
  the answer and show a retry notice. Leaving the screen cancels pending work.
- The citation-selection server changes are local source changes until the
  backend is deployed. Installing the APK alone uses the compatibility path on
  an older server.

## APK baseline

Based on the latest fetched `iteration-3-demo` at `cdbe2d1` (PR #49).
The application's font, theme and resources come from that commit. No font or
UI settings are taken from the user-provided APK. The public APK uses the
existing local debug certificate to update the Galaxy without uninstalling it.
The public API remains `https://talkdock.app/api/`.

## Checks

Offline pytest covers citation validation, citation ordering, deduplication,
room isolation (including a user belonging to both rooms), deleted and text-only
posts, photo ordering and the unchanged answer when sources are unavailable.
JVM tests cover response snapshots and real loopback HTTP compatibility with
the deployed response, authorization and family room headers. Instrumented
`FamilyMemorySearchTest` covers full feed rendering in both font sizes, photos,
detail/back/recreation, scroll and draft retention, re-search, empty evidence and
legacy server responses. These tests use synthetic family records, not a real
family account or paid AI calls.
