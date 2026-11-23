"""
Add NFCEvent: the plugin-owned history of NFC actions on a unit.

Replaces the use of InvenTree's legacy stock tracking model, removed in
InvenTree 1.7.0.
"""

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("nfc", "0006_unlink_history"),
        ("stock", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="NFCEvent",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("created", "Unit created"),
                            ("stock", "Stock change"),
                            ("consumed", "Unit consumed"),
                            ("link", "Tag linked"),
                            ("unlink", "Tag unlinked"),
                        ],
                        max_length=16,
                    ),
                ),
                (
                    "date",
                    models.DateTimeField(
                        db_index=True, default=django.utils.timezone.now
                    ),
                ),
                (
                    "quantity",
                    models.DecimalField(
                        blank=True, decimal_places=5, max_digits=15, null=True
                    ),
                ),
                (
                    "delta",
                    models.DecimalField(
                        blank=True, decimal_places=5, max_digits=15, null=True
                    ),
                ),
                ("uid", models.CharField(blank=True, default="", max_length=64)),
                ("notes", models.TextField(blank=True, default="")),
                (
                    "stock_item",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="nfc_events",
                        to="stock.stockitem",
                        verbose_name="Stock Item",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="nfc_events",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-date", "-pk"],
                "indexes": [
                    models.Index(
                        fields=["stock_item", "date"], name="nfc_event_item_date"
                    )
                ],
            },
        ),
    ]
