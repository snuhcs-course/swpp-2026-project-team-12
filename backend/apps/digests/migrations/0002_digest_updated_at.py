from django.db import migrations, models


def has_updated_at(schema_editor):
    with schema_editor.connection.cursor() as cursor:
        columns = schema_editor.connection.introspection.get_table_description(cursor, "digests_digest")
    return any(column.name == "updated_at" for column in columns)


def add_updated_at_if_missing(apps, schema_editor):
    if not has_updated_at(schema_editor):
        digest = apps.get_model("digests", "Digest")
        schema_editor.add_field(digest, digest._meta.get_field("updated_at"))


def remove_updated_at(apps, schema_editor):
    if has_updated_at(schema_editor):
        digest = apps.get_model("digests", "Digest")
        schema_editor.remove_field(digest, digest._meta.get_field("updated_at"))


class Migration(migrations.Migration):
    dependencies = [("digests", "0001_initial")]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="digest",
                    name="updated_at",
                    field=models.DateTimeField(auto_now=True),
                ),
            ],
        ),
        migrations.RunPython(add_updated_at_if_missing, remove_updated_at),
    ]
