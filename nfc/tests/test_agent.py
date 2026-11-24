"""
Tests for the NFC agent Flask app.

pyscard is replaced by lightweight stubs when it is not installed, and every
reader access is mocked, so no USB reader (nor the PC/SC library) is required.
"""

import sys
import threading
import time
import types
from unittest.mock import MagicMock, patch

import pytest


def _install_smartcard_stubs():
    """Register minimal 'smartcard' modules so agent.agent can be imported without pyscard."""
    try:
        import smartcard  # noqa: F401

        return
    except ImportError:
        pass

    class _CardConnectionException(Exception):
        pass

    class _NoCardException(Exception):
        pass

    modules = {
        "smartcard": types.ModuleType("smartcard"),
        "smartcard.CardMonitoring": types.ModuleType("smartcard.CardMonitoring"),
        "smartcard.Exceptions": types.ModuleType("smartcard.Exceptions"),
        "smartcard.System": types.ModuleType("smartcard.System"),
        "smartcard.util": types.ModuleType("smartcard.util"),
    }
    modules["smartcard.CardMonitoring"].CardMonitor = MagicMock
    modules["smartcard.CardMonitoring"].CardObserver = object
    modules["smartcard.Exceptions"].CardConnectionException = _CardConnectionException
    modules["smartcard.Exceptions"].NoCardException = _NoCardException
    modules["smartcard.System"].readers = lambda: []
    modules["smartcard.util"].toHexString = lambda data: " ".join(
        f"{b:02X}" for b in data
    )
    sys.modules.update(modules)


_install_smartcard_stubs()

import agent.agent as ag  # noqa: E402


@pytest.fixture()
def client():
    """Flask test client with one reader, no tag on it, and a fresh scan broker."""
    ag._broker = ag.ScanBroker()
    ag.app.config["TESTING"] = True
    with (
        patch("agent.agent.readers", return_value=[MagicMock()]),
        patch("agent.agent._read_present_uid", return_value=None),
    ):
        yield ag.app.test_client()


def _later(fn, delay=0.1):
    """Run fn in a background thread after a short delay."""
    t = threading.Thread(target=lambda: (time.sleep(delay), fn()), daemon=True)
    t.start()
    return t


def _scan_async(client, timeout=5):
    """Start a /scan/once request in a thread; return (thread, result holder)."""
    holder = {}

    own_client = client.application.test_client()

    def run():
        holder["res"] = own_client.post("/scan/once", json={"timeout": timeout})

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t, holder


def _wait_for_active_scan(previous=None):
    """Wait until the broker has an active scan different from `previous`."""
    for _ in range(100):
        active = ag._broker._active
        if active is not None and active is not previous:
            return active
        time.sleep(0.01)
    raise AssertionError("scan did not start")


def test_health_reader_connected(client):
    """The health endpoint reports a connected reader."""
    res = client.get("/health")
    assert res.status_code == 200
    assert res.get_json()["status"] == "ok"
    assert res.get_json()["reader_connected"] is True


def test_health_no_reader(client):
    """The health endpoint reports a missing reader."""
    with patch("agent.agent.readers", return_value=[]):
        res = client.get("/health")
    assert res.get_json()["reader_connected"] is False


def test_scan_once_returns_uid(client):
    """A tag presented during the scan is returned."""
    _later(lambda: ag._broker.deliver("AABBCCDD"))
    res = client.post("/scan/once", json={"timeout": 5})
    assert res.status_code == 200
    assert res.get_json()["uid"] == "AABBCCDD"


def test_scan_once_timeout(client):
    """No tag within the timeout gives a 408 timeout."""
    res = client.post("/scan/once", json={"timeout": 0.1})
    assert res.status_code == 408
    assert res.get_json()["error"] == "timeout"


def test_scan_once_no_reader(client):
    """Without a reader the scan fails with 503 no_reader."""
    with patch("agent.agent.readers", return_value=[]):
        res = client.post("/scan/once", json={"timeout": 1})
    assert res.status_code == 503
    assert res.get_json()["error"] == "no_reader"


def test_scan_once_default_timeout(client):
    """A missing timeout falls back to the default and still returns the tag."""
    _later(lambda: ag._broker.deliver("AABBCCDD"))
    res = client.post("/scan/once", json={})
    assert res.status_code == 200
    assert res.get_json()["uid"] == "AABBCCDD"


def test_abandoned_scan_does_not_steal_uid(client):
    """A newer scan cancels the abandoned one and receives the tag."""
    first, first_res = _scan_async(client)
    first_session = _wait_for_active_scan()
    second, second_res = _scan_async(client)
    _wait_for_active_scan(previous=first_session)
    ag._broker.deliver("CAFEBABE")
    first.join(5)
    second.join(5)
    assert first_res["res"].status_code == 409
    assert first_res["res"].get_json()["error"] == "cancelled"
    assert second_res["res"].status_code == 200
    assert second_res["res"].get_json()["uid"] == "CAFEBABE"


def test_cancel_active_scan(client):
    """Cancelling a waiting scan answers cancelled to both requests."""
    t, holder = _scan_async(client)
    _wait_for_active_scan()
    res = client.post("/scan/cancel")
    t.join(5)
    assert res.get_json() == {"cancelled": True}
    assert holder["res"].status_code == 409
    assert holder["res"].get_json()["error"] == "cancelled"


def test_cancel_without_scan(client):
    """Cancelling with no scan waiting reports nothing was cancelled."""
    res = client.post("/scan/cancel")
    assert res.status_code == 200
    assert res.get_json() == {"cancelled": False}


def test_uid_without_active_scan_is_dropped(client):
    """A tag read with no scan waiting is not handed to the next scan."""
    assert ag._broker.deliver("DEADBEEF") is False
    res = client.post("/scan/once", json={"timeout": 0.1})
    assert res.status_code == 408


def test_tag_already_on_reader(client):
    """A tag lying on the reader when the scan starts is returned at once."""
    with patch("agent.agent._read_present_uid", return_value="0102AABB"):
        start = time.monotonic()
        res = client.post("/scan/once", json={"timeout": 5})
    assert res.status_code == 200
    assert res.get_json()["uid"] == "0102AABB"
    assert time.monotonic() - start < 2


def test_read_present_uid_reads_card():
    """_read_present_uid returns the UID from a reader that has a card."""
    connection = MagicMock()
    connection.transmit.return_value = ([0x04, 0xA1, 0xB2], 0x90, 0x00)
    empty = MagicMock()
    empty.createConnection.return_value.connect.side_effect = ag.NoCardException()
    full = MagicMock()
    full.createConnection.return_value = connection
    with patch("agent.agent.readers", return_value=[empty, full]):
        assert ag._read_present_uid() == "04A1B2"
    connection.disconnect.assert_called_once()


def test_read_present_uid_no_card():
    """_read_present_uid returns None when no reader has a card."""
    empty = MagicMock()
    empty.createConnection.return_value.connect.side_effect = ag.NoCardException()
    with patch("agent.agent.readers", return_value=[empty]):
        assert ag._read_present_uid() is None
