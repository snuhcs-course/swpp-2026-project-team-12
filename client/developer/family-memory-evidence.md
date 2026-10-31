# Family history evidence posts

Family history answers now show original posts below “이 이야기가 담긴 소식”.
`PhotoLetterDeck` renders both the home feed and evidence using frontend v2:
photo-letter styling, caption, author, date, photo count and voice reply. Evidence
letters are stacked vertically with deck pagination hidden for each single post.
Opening a letter uses the existing full detail view and its photo carousel.
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

Based on `iteration-3-demo` at `72014d5`, which includes frontend-v2 PR #50.
The application's font, palette, theme and normal feed retain that source design.
No resources are extracted from a supplied APK. The public API stays unchanged.

## Try it on an emulator

The `talkDockDemo` Gradle option creates a separate `kr.talkdock.app.memorydemo`
application labelled **토닥 데모**, preserving the ordinary app and its sessions.
The demo calls the real local Django/Graphiti/OpenAI pipeline, not fixture answers.
Its SQLite DB, media and generated Neo4j credentials live in ignored
`.local/memory-demo/`. Neo4j uses its own `talkdock-memory-demo` Docker container
and volume, with loopback ports 7688/7475. Only the synthetic family 961031 is
seeded/ingested; existing family data and production are not changed.

Prerequisites: Docker running, the repository virtualenv, and a working
`OPENAI_API_KEY` in the repository `.env`. Ingestion and searches make real API
calls using fictional posts. Six posts cover a Busan trip, a postcard souvenir,
a birthday cake, dog feeding times, a hike and a book. Images are demo artwork.
Seeding is idempotent; it does not duplicate or replace previously seeded posts.

From the repository root, first-time setup:

```sh
.venv/bin/python backend/developer/memory_demo.py setup
.venv/bin/python backend/developer/memory_demo.py ingest
.venv/bin/python backend/developer/memory_demo.py serve
```

On later runs, start the container with `setup`, then run `serve`. Use `ingest`
again only when adding more demo history. The server listens on 127.0.0.1:8001;
the emulator uses `http://10.0.2.2:8001/api/`.

Build/install the separate demo APK, with the Android SDK and Java configured:

```sh
cd client
./gradlew -PtalkDockDemo=true -PtalkDockApiUrl=http://10.0.2.2:8001/api/ :app:assembleDebug
adb -e install -r app/build/outputs/apk/debug/app-debug.apk
```

Open **토닥 데모**, sign in with **01000001031 / MemoryDemo1031!**, then tap the
character and **가족 추억 찾기**. Try:

| Question | Seeded answer |
|---|---|
| 지난 가족 여행은 어디로 갔고 뭘 먹었어? | 부산 해운대, 돼지국밥 |
| 부산 여행에서 지민이가 고른 기념품은 뭐야? | 바다 그림 엽서 |
| 보리 밥은 누가 몇 시에 줘? | 지민, 오전 8시·오후 6시 |
| 엄마 생일에 지민이가 준비한 건 뭐야? | 딸기 케이크 |
| 아빠가 요즘 읽는 책 제목이 뭐였지? | 어린 왕자 |

Each successful answer shows its cited original letters below it. Tap a letter
to view all photos/comments; Back preserves the answer and scroll position.

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

`MemoryDemoLiveTest` is separately opt-in (`-e liveMemoryDemo true`). It requires
the demo-only package, local server and seeded family; it checks the real
Graphiti/OpenAI answer, original v2 letters, photos and return from detail.
