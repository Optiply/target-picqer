"""Tests for Picqer API error handling."""
# pyright: reportMissingImports=false

from __future__ import annotations

from typing import Any, cast

import pytest
from hotglue_singer_sdk.exceptions import FatalAPIError

from target_picqer.sinks import PurchaseOrders


class DummyLogger:
    """Collect logged errors for assertions."""

    def __init__(self) -> None:
        self.errors = []

    def error(self, message):
        self.errors.append(message)


class DummyResponse:
    """Small response double for validate_response tests."""

    status_code = 400
    text = ""

    def json(self):
        return {"errormessage": "Verplicht: Betalingsconditie"}


def test_validate_response_preserves_picqer_error_message():
    """Picqer API messages should be preserved in raised errors and logs."""
    sink = cast(Any, object.__new__(PurchaseOrders))
    sink.logger = DummyLogger()

    with pytest.raises(FatalAPIError, match="Verplicht: Betalingsconditie"):
        sink.validate_response(cast(Any, DummyResponse()))

    assert sink.logger.errors == [{"error": "Verplicht: Betalingsconditie"}]


def test_purchase_order_error_message_includes_record_identifier():
    """Record-specific errors should include sink name, id, and API message."""
    sink = cast(Any, object.__new__(PurchaseOrders))
    sink.stream_name = "buyOrders"
    assert sink.name == sink.stream_name

    error = sink._record_error(
        {"id": 6054362}, RuntimeError("Verplicht: Betalingsconditie")
    )

    assert str(error) == "buyOrders ID: 6054362, Error: Verplicht: Betalingsconditie"
