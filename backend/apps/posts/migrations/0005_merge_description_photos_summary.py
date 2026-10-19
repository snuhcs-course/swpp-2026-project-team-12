from django.db import migrations


class Migration(migrations.Migration):
    # Preserve already-applied description and independently published photo/cache histories.
    dependencies = [
        ("posts", "0003_post_description"),
        ("posts", "0004_merge_post_photos_summary_cache"),
    ]
    operations = []
