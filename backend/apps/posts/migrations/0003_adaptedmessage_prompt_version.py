from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("posts", "0002_adaptedmessage")]
    operations = [migrations.AddField(
        model_name="adaptedmessage", name="prompt_version",
        field=models.CharField(blank=True, default="", max_length=64),
    )]
