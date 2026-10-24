from django.db import migrations, models


def collect_images(apps, schema_editor):
    Post = apps.get_model("posts", "Post")
    alias = schema_editor.connection.alias
    for post in Post.objects.using(alias).prefetch_related("photos").iterator(chunk_size=500):
        paths = [post.image.name] if post.image else []
        paths.extend(photo.image.name for photo in post.photos.all() if photo.image)
        Post.objects.using(alias).filter(pk=post.pk).update(images=paths)


def split_images(apps, schema_editor):
    Post = apps.get_model("posts", "Post")
    PostPhoto = apps.get_model("posts", "PostPhoto")
    alias = schema_editor.connection.alias
    for post in Post.objects.using(alias).iterator(chunk_size=500):
        Post.objects.using(alias).filter(pk=post.pk).update(image=post.images[0] if post.images else "")
        PostPhoto.objects.using(alias).bulk_create([
            PostPhoto(post_id=post.pk, image=name, position=index)
            for index, name in enumerate(post.images[1:], start=1)
        ])


class Migration(migrations.Migration):
    dependencies = [("posts", "0005_merge_description_photos_summary")]

    operations = [
        migrations.AddField(
            model_name="post", name="images", field=models.JSONField(blank=True, default=list),
        ),
        migrations.RunPython(collect_images, split_images),
        migrations.RemoveField(model_name="post", name="image"),
        migrations.DeleteModel(name="PostPhoto"),
    ]
