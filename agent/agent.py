"""
NFC Agent — runs locally on the workstation with the USB reader.
Exposes 3 endpoints:
  GET  /health       → is the reader connected?
  POST /scan/once    → wait for a tag, return its UID
  POST /scan/cancel  → cancel the scan currently waiting, if any
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field

from flask import Flask, jsonify, request
from flask_cors import CORS
from smartcard.CardMonitoring import CardMonitor, CardObserver
from smartcard.Exceptions import CardConnectionException, NoCardException
from smartcard.System import readers
from smartcard.util import toHexString

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
log = logging.getLogger("nfc-agent")

GET_UID = [0xFF, 0xCA, 0x00, 0x00, 0x00]
SW_OK = (0x90, 0x00)

DEFAULT_SCAN_TIMEOUT = 30.0
MIN_SCAN_TIMEOUT = 0.1
MAX_SCAN_TIMEOUT = 120.0


@dataclass
class ScanSession:
    """One scan request waiting for a tag.

    Attributes:
        id: Sequential identifier of the scan.
        uid: UID delivered to this scan, if any.
        cancelled: True if the scan was cancelled or replaced by a newer one.
    """

    id: int
    uid: str | None = None
    cancelled: bool = False
    _done: threading.Event = field(default_factory=threading.Event, repr=False)


class ScanBroker:
    """Hands each scanned UID to the single active scan session.

    Only one scan is active at a time: starting a scan cancels the previous
    one, so a scan abandoned by the browser can never steal the UID meant for
    the next one. A UID read while no scan is active is logged and dropped.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counter = 0
        self._active: ScanSession | None = None

    def start(self) -> ScanSession:
        """Cancel the active scan (if any) and open a new one."""
        with self._lock:
            if self._active is not None:
                self._finish(self._active, cancelled=True)
                log.info("Scan #%s replaced by a new scan", self._active.id)
            self._counter += 1
            self._active = ScanSession(id=self._counter)
            return self._active

    def deliver(self, uid: str, session: ScanSession | None = None) -> bool:
        """Give a UID to the active scan, or to `session` only if it is still active.

        Returns:
            True if a waiting scan received the UID.
        """
        with self._lock:
            target = self._active
            if target is None or (session is not None and target is not session):
                log.info("Tag %s read while no scan was waiting - ignored", uid)
                return False
            if target._done.is_set():
                log.info("Tag %s ignored: scan #%s already completed", uid, target.id)
                return False
            target.uid = uid
            target._done.set()
            return True

    def cancel(self) -> bool:
        """Cancel the active scan.

        Returns:
            True if a scan was waiting and has been cancelled.
        """
        with self._lock:
            target = self._active
            if target is None or target._done.is_set():
                return False
            self._finish(target, cancelled=True)
            self._active = None
            log.info("Scan #%s cancelled", target.id)
            return True

    def wait(self, session: ScanSession, timeout: float) -> ScanSession:
        """Block until the session receives a UID, is cancelled, or times out."""
        session._done.wait(timeout=timeout)
        with self._lock:
            if self._active is session:
                self._active = None
        return session

    @staticmethod
    def _finish(session: ScanSession, cancelled: bool) -> None:
        session.cancelled = cancelled
        session._done.set()


_broker = ScanBroker()


def _uid_from_connection(connection) -> str | None:
    """Send GET_UID on an open card connection and return the UID, or None."""
    response, sw1, sw2 = connection.transmit(GET_UID)
    if (sw1, sw2) == SW_OK and response:
        return toHexString(response).replace(" ", "").upper()
    log.warning("UID read refused by the tag (SW %02X %02X)", sw1, sw2)
    return None


def _read_uid(card) -> str | None:
    """Read the UID of a card reported by the PC/SC monitor."""
    try:
        card.connection = card.createConnection()
        card.connection.connect()
        return _uid_from_connection(card.connection)
    except (CardConnectionException, NoCardException) as e:
        log.warning("UID read failed (tag removed too fast or reader busy): %s", e)
        return None
    finally:
        try:
            card.connection.disconnect()
        except Exception as exc:
            log.debug("Card disconnect failed: %s", exc)


def _read_present_uid() -> str | None:
    """Return the UID of a tag already lying on a reader, if any."""
    for reader in readers():
        try:
            connection = reader.createConnection()
            connection.connect()
        except NoCardException:
            continue
        except Exception as exc:
            log.debug("No readable tag on %s: %s", reader, exc)
            continue
        try:
            uid = _uid_from_connection(connection)
        except Exception as exc:
            log.warning("UID read failed on %s: %s", reader, exc)
            uid = None
        finally:
            try:
                connection.disconnect()
            except Exception as exc:
                log.debug("Reader disconnect failed: %s", exc)
        if uid:
            return uid
    return None


class NFCObserver(CardObserver):
    """PC/SC observer: forwards the UID of every newly presented tag to the broker."""

    def update(self, observable, actions):
        """Called by pyscard's CardMonitor thread when cards are added or removed."""
        added, _ = actions
        for card in added:
            uid = _read_uid(card)
            if uid:
                log.info("Tag scanned: %s", uid)
                _broker.deliver(uid)


app = Flask(__name__)
CORS(app)


@app.get("/health")
def health():
    """Report whether at least one reader is connected."""
    current_readers = readers()

    return jsonify({
        "status": "ok",
        "reader_connected": bool(current_readers),
        "readers": [str(r) for r in current_readers],
    }), 200


@app.post("/scan/once")
def scan_once():
    """Wait for one tag and return its UID.

    A new scan replaces (and cancels) any scan still waiting. A tag already on
    the reader when the scan starts is returned immediately.
    """
    if not readers():
        return jsonify({"error": "no_reader"}), 503

    data = request.get_json(silent=True) or {}
    try:
        timeout = float(data.get("timeout", DEFAULT_SCAN_TIMEOUT))
    except (TypeError, ValueError):
        timeout = DEFAULT_SCAN_TIMEOUT
    timeout = max(MIN_SCAN_TIMEOUT, min(MAX_SCAN_TIMEOUT, timeout))

    session = _broker.start()

    present = _read_present_uid()
    if present:
        log.info("Tag already on the reader: %s", present)
        _broker.deliver(present, session=session)

    _broker.wait(session, timeout)

    if session.cancelled:
        return jsonify({"error": "cancelled"}), 409
    if session.uid is None:
        return jsonify({"error": "timeout"}), 408
    return jsonify({"uid": session.uid}), 200


@app.post("/scan/cancel")
def scan_cancel():
    """Cancel the scan currently waiting, if any."""
    return jsonify({"cancelled": _broker.cancel()}), 200


if __name__ == "__main__":
    from waitress import serve

    monitor = CardMonitor()
    monitor.addObserver(NFCObserver())
    log.info("Agent ready on http://127.0.0.1:8765")
    serve(app, host="127.0.0.1", port=8765)
