# Developer tests

Run the account API tests from the repository root:

```bash
python backend/manage.py test developer.test_codes
```

The output shows every stored column for both test accounts and their access tokens. It comes from Django's temporary test database, which is deleted after the run.
