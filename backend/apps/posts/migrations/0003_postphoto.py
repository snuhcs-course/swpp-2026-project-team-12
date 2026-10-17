from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("posts", "0002_adaptedmessage")]
    operations = [
        migrations.AlterField(
            model_name="post", name="image",
            field=models.ImageField(blank=True, upload_to="posts/%Y/%m/"),
        ),
        migrations.CreateModel(
            name="PostPhoto",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("image", models.ImageField(upload_to="posts/%Y/%m/")),
                ("position", models.PositiveSmallIntegerField()),
                ("post", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="photos", to="posts.post")),
            ],
            options={"ordering": ["position", "id"], "constraints": [models.UniqueConstraint(fields=("post", "position"), name="unique_post_photo_position")]},
        ),
    ]
