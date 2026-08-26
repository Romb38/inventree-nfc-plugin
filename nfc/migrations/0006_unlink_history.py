"""
Add unlink history to NFCTagLink: unlinked_at + unlinked_by, and set
distinct related_names on the user foreign keys.
"""

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("nfc", "0005_tag_to_stockitem"),
    ]

    operations = [
        migrations.AlterField(
            model_name="nfctaglink",
            name="linked_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="nfc_links_created",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="nfctaglink",
            name="unlinked_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="nfctaglink",
            name="unlinked_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="nfc_links_removed",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]