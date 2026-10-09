# Developer Tools

## Sample images
```
backend\developer\samples
```

## Developer tests
Run the account, family, post, comment, speech, and voice reply API/model tests from the repository root:

```bash
python backend/manage.py test developer.test_codes
```

### 1. `test_codes\test_accounts.py`

- `test_registration_creates_an_account_and_hashed_session`: Registers two accounts, checks password and token hashing, verifies `/me`, and confirms registration does not create a family room or membership.
- `test_login_and_logout_revoke_only_the_presented_token`: Rejects an incorrect password, logs in with valid credentials, and confirms logout revokes only the token used for that request.
- `test_registration_rejects_weak_password_and_duplicate_username`: Rejects a weak password and a duplicate username, including different letter casing.
- `test_expired_or_inactive_sessions_cannot_authenticate`: Rejects expired tokens and prevents inactive users from accessing `/me` or logging in.
- `test_registration_requires_json_and_valid_username`: Rejects a non-JSON request and an invalid username.

The registration test prints every stored column for its two accounts and their access tokens.

### 2. `test_codes\test_families.py`

- `test_room_defaults_and_owner_protection`: Checks room defaults, unique invitation codes, and protection against deleting a room owner.
- `test_membership_is_unique_per_user_and_slot_within_a_room`: Enforces one membership per user and one user per slot in a room, while allowing membership in another room.
- `test_deleting_a_room_removes_its_memberships`: Confirms deleting a room removes its memberships without deleting its users.
- `test_create_uses_existing_account_and_current_updates_digest_time`: Creates a room with a registered account, checks its owner membership and hashed room password, then reads and updates the digest time.
- `test_lookup_checks_invitation_password`: Finds a room using a case-insensitive invitation code and rejects an incorrect password.
- `test_join_uses_existing_account_and_rejects_occupied_slot`: Joins an existing account, checks relationship output, and rejects repeat joins, occupied slots, unknown slots, and non-owner updates.
- `test_invalid_requests_and_missing_membership`: Rejects invalid room input and access to `current` without a family membership.

After the family workflow tests, the CLI prints an owner-relative family graph with arrows from each child toward their parent. Slots do not identify which child is the parent of a grandchild.

### 3. `test_codes\test_posts.py`

- `test_upload_converts_sample_and_returns_feed_and_detail`: Uploads a sample PNG and checks JPEG conversion, post persistence, room feed, detail, and author relationship.
- `test_upload_resizes_large_sample`: Enlarges a sample PNG and checks that the stored JPEG fits within the configured dimensions.
- `test_photo_requires_membership_and_stays_within_room`: Checks image authentication and isolation between family rooms.
- `test_invalid_uploads_do_not_create_posts`: Rejects missing, invalid, oversized images and overly long captions.
- `test_image_url_uses_configured_public_origin`: Checks the absolute photo URL used for a public HTTPS backend.
- `test_message_is_private_and_cached_per_viewer`: Checks room access, viewer-specific AI messages, and reuse of cached results.
- `test_message_failure_requires_explicit_retry`: Checks the missing-key failure and retry only on POST.
- `test_message_processing_is_claimed_once_and_stale_work_retries`: Checks in-progress and timed-out message generation.
- `test_ai_provider_sends_photo_and_caption_and_reads_completed_text`: Mocks the OpenAI response and checks the image, caption, model, and result parsing without a live API call.
- `test_ai_provider_rejects_incomplete_response`: Checks that an incomplete response does not become a ready message.
- `test_grandma_post_summaries`: Recreates the family from `test_families.py`, uploads the two sample images as 정아, and requests AI summaries as 경자. It calls OpenAI by default; `MOCK_AI_TESTS=1` uses two fixed responses instead.

### 4. `test_codes\test_comments.py`

- `test_comment_appears_in_post_detail_and_feed`: Adds a text comment from 경자 to 정아's Pokémon post, checks the saved comment, author relationship, detail list, and feed count.
- `test_comments_reject_invalid_input_and_other_rooms`: Rejects unauthenticated or unrelated users, invalid JSON input, oversized text, and unknown posts.

### 5. `test_codes\test_speech.py`

- `test_speech_request_and_room_cache`: Checks the ElevenLabs request, MP3 response, and reuse of cached audio within a family room. The provider call is mocked.
- `test_grandma_post_summaries_are_spoken_live`: Recreates the seven-member family and two posts from the post tests, gets 경자's summaries, and sends both to the real ElevenLabs TTS API on every run. It saves two MP3 files under `backend/developer/test_media/`. OpenAI is live by default; `MOCK_AI_TESTS=1` uses fixed text while TTS stays live.
- `test_speech_authentication_and_input_validation`: Rejects requests without a token or family membership, and invalid text or content type.
- `test_speech_provider_failures_do_not_cache_audio`: Returns 503 for missing voice configuration or an invalid provider response without storing audio.

### 6. `test_codes\test_voice_replies.py`

- `test_stt_review_and_send_creates_one_comment`: Uploads `samples/sample_reply_2.m4a` to the mocked STT provider, prepares a draft for 경자 to review, and sends it as one voice comment on 정아's paper post. Checks repeated sends do not duplicate the comment.
- `test_sample_replies_use_text_for_game_and_live_stt_for_paper`: Posts both sample images as 정아. 경자 replies to the Pokémon post with text only and to the paper post by sending `sample_reply_2.m4a` through the real ElevenLabs STT and OpenAI draft API. It also requests both real OpenAI post summaries as 경자. The single `backend/developer/test_media/grandma_report.html` shows both posts, summaries, comments, STT text, the original recording, and saved database fields. Requires `ELEVENLABS_API_KEY` and `OPENAI_API_KEY`; skips without them.
- `test_stt_provider_request_and_errors`: Checks the ElevenLabs STT request, Korean language setting, empty transcript, missing key, and invalid or oversized uploads with a mocked provider response.
- `test_voice_reply_room_author_and_input_validation`: Rejects requests without authentication or room access, invalid recognized text, and attempts to send someone else's or an unknown draft.
- `test_rewrite_failure_does_not_create_draft`: Confirms failed AI rewriting saves no draft and checks the rewrite prompt preserves the recognized message.

Run the mocked voice reply tests without external API calls:

```bash
python backend/manage.py test developer.test_codes.test_voice_replies.VoiceReplyAPITests.test_stt_review_and_send_creates_one_comment developer.test_codes.test_voice_replies.VoiceReplyAPITests.test_stt_provider_request_and_errors developer.test_codes.test_voice_replies.VoiceReplyAPITests.test_voice_reply_room_author_and_input_validation developer.test_codes.test_voice_replies.VoiceReplyAPITests.test_rewrite_failure_does_not_create_draft
```

Run the two-post sample test with live STT and AI:

```bash
python backend/manage.py test developer.test_codes.test_voice_replies.VoiceReplyAPITests.test_sample_replies_use_text_for_game_and_live_stt_for_paper
```

### Summary
All tests use Django's temporary test database, which is deleted after the run. The two-post integration test writes the only HTML report, `backend/developer/test_media/grandma_report.html`, so the posts, 경자's summaries, and both kinds of comments appear together.

With `OPENAI_API_KEY` configured, the post summary test makes two billable OpenAI requests. To use fixed responses for that test instead:

```powershell
$env:MOCK_AI_TESTS = "1"
python backend/manage.py test developer.test_codes.test_posts.PostAPITests.test_grandma_post_summaries
Remove-Item Env:MOCK_AI_TESTS
```

The speech test requires `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID`. It calls ElevenLabs twice per run and writes `grandma_post_1_tts.mp3` and `grandma_post_2_tts.mp3` under `backend/developer/test_media/`. Its audio cache is new for each run, so repeated test runs generate fresh speech. With live AI enabled, this test also makes two OpenAI requests. Without speech credentials the live test is skipped; the other speech tests use mocked provider responses.
