"""Django config for the NFC plugin."""

from django.apps import AppConfig


class NFCConfig(AppConfig):
    """Config class for the NFC plugin."""

    name = "nfc"

    def ready(self):
        """Connect the plugin signal handlers whenever the NFC plugin is loaded."""
        from .signals import connect_signals

        connect_signals()
