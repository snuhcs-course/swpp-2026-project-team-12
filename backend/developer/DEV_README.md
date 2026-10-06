# Developer Tools

## Sample images
```
backend\developer\samples
```

## Developer tests
Run the account API and family model tests from the repository root:

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

All tests use Django's temporary test database, which is deleted after the run.
