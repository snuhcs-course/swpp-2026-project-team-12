from django.db import migrations


class Migration(migrations.Migration):
    # Keep both independently published 0003 migrations valid on existing databases.
    dependencies = [
        ("posts", "0003_postphoto"),
        ("posts", "0003_adaptedmessage_prompt_version"),
    ]
    operations = []
