from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("digests", "0002_digest_updated_at")]

    operations = [
        migrations.AddField(
            model_name="digest",
            name="summaries",
            field=models.JSONField(default=list, blank=True),
        ),
    ]
