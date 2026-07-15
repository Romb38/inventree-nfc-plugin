"""
Move NFCTagLink from Part-based to StockItem-based linking.

Each tag now identifies a specific StockItem (tube) rather than a Part.
Existing links point at Parts and cannot be auto-converted to StockItems,
so they are removed first (test data). Re-link tags to tubes after migrating.
"""

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def delete_existing_links(apps, schema_editor):
    NFCTagLink = apps.get_model("nfc", "NFCTagLink")
    NFCTagLink.objects.all().delete()


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("nfc", "0004_alter_nfctaglink_part_alter_nfctaglink_uid_and_more"),
        ("stock", "0001_initial"),
    ]

    operations = [
        # 1. Clear old Part-based rows (cannot be converted to StockItem).
        migrations.RunPython(delete_existing_links, noop),

        # 2. Drop the old part-based unique constraint.
        migrations.RemoveConstraint(
            model_name="nfctaglink",
            name="unique_active_part",
        ),

        # 3. Remove the old part FK.
        migrations.RemoveField(
            model_name="nfctaglink",
            name="part",
        ),

        # 4. Add the new stock_item FK.
        migrations.AddField(
            model_name="nfctaglink",
            name="stock_item",
            field=models.ForeignKey(
                default=None,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="nfc_tags",
                to="stock.stockitem",
                verbose_name="Linked Stock Item",
            ),
            preserve_default=False,
        ),

        # 5. Add the new tube-based unique constraint.
        migrations.AddConstraint(
            model_name="nfctaglink",
            constraint=models.UniqueConstraint(
                condition=models.Q(active=True),
                fields=("stock_item",),
                name="unique_active_stock_item",
            ),
        ),
    ]