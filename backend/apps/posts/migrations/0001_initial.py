import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("families", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Post",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("image", models.ImageField(upload_to="posts/%Y/%m/")),
                ("caption", models.CharField(blank=True, max_length=2000)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("author", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
                ("room", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="posts", to="families.familyroom")),
            ],
            options={"ordering": ["-created_at", "-id"]},
        ),
    ]
