# Developer Tools

## Sample images
```
backend\developer\samples
```

## Developer tests
Run the account, family, and post API/model tests from the repository root:

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

### Summary
All tests use Django's temporary test database, which is deleted after the run. Post tests save converted images in `backend/developer/test_media/` and write `backend/developer/test_media/posts_report.html` with image previews and the saved post fields. Open that HTML file after the tests; the CLI prints its relative path.

With `OPENAI_API_KEY` configured, an ordinary post test run makes two billable OpenAI requests and writes `backend/developer/test_media/grandma_ai_report.html`. To use fixed responses and write `backend/developer/test_media/grandma_mock_report.html` instead:

```powershell
$env:MOCK_AI_TESTS = "1"
python backend/manage.py test developer.test_codes.test_posts.PostAPITests.test_grandma_post_summaries
Remove-Item Env:MOCK_AI_TESTS
```
