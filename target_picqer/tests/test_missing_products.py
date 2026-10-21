"""Behavioral coverage for partial purchase-order exports."""

from __future__ import annotations

import json
import logging
from typing import Any, cast

import pytest
import requests

from target_picqer.sinks import BuyOrders


def response(status: int, body: Any) -> requests.Response:
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(body).encode()
    return result


def missing_product(product_id: int, status: int = 400) -> requests.Response:
    return response(
        status,
        {
            "error": True,
            "error_code": 20,
            "error_message": f"Product '{product_id}' not found.",
        },
    )


@pytest.fixture
def sink() -> Any:
    result = cast(Any, object.__new__(BuyOrders))
    result._config = {
        "org": "synthetic-example",
        "api_key": "synthetic-not-a-credential",
    }
    result.logger = logging.getLogger(__name__)
    return result


@pytest.fixture
def http(monkeypatch):
    responses = []
    calls = []

    def request(**kwargs):
        endpoint = kwargs["url"].split("/api/v1/")[1]
        payload = json.loads(kwargs["data"]) if kwargs["data"] else None
        calls.append((kwargs["method"], endpoint, payload))
        return responses.pop(0)

    monkeypatch.setattr(requests, "request", request)
    return responses, calls


def order(*product_ids: int) -> dict:
    return {
        "idsupplier": 100,
        "idwarehouse": 200,
        "products": [
            {"idproduct": product_id, "amount": 2, "price": 12.5}
            for product_id in product_ids
        ],
        "remarks": "Synthetic Optiply order",
    }


def test_removes_successive_missing_products_and_purchases_once(sink, http):
    responses, calls = http
    responses.extend(
        [
            missing_product(2),
            missing_product(3),
            response(201, {"idpurchaseorder": 900}),
            response(200, {}),
        ]
    )

    assert sink.upsert_record(order(2, 3, 4), {}) == (900, True, {})

    assert calls == [
        ("POST", "purchaseorders", order(2, 3, 4)),
        ("POST", "purchaseorders", order(3, 4)),
        ("POST", "purchaseorders", order(4)),
        ("POST", "purchaseorders/900/mark-as-purchased", None),
    ]


def test_all_missing_products_fail_without_sending_empty_order(sink, http):
    responses, calls = http
    responses.extend([missing_product(2), missing_product(3)])

    with pytest.raises(RuntimeError, match="No products remain.*Product '3' not found"):
        sink.upsert_record(order(2, 3), {})

    assert calls == [
        ("POST", "purchaseorders", order(2, 3)),
        ("POST", "purchaseorders", order(3)),
    ]


@pytest.mark.parametrize("status", [400, 404, 422])
def test_removes_all_lines_for_same_missing_product_in_concept_mode(sink, http, status):
    responses, calls = http
    sink._config["buy_order_export_as_concept"] = True
    responses.extend(
        [missing_product(2, status), response(201, {"idpurchaseorder": 900})]
    )
    payload = order(2, 2, 3)
    payload["products"][0]["idproduct"] = "2"
    payload["status"] = "concept"

    assert sink.upsert_record(payload, {}) == (900, True, {})

    assert len(calls) == 2
    assert calls[1] == ("POST", "purchaseorders", {**order(3), "status": "concept"})


@pytest.mark.parametrize(
    "rejection",
    [
        missing_product(99),
        missing_product(2, 401),
        missing_product(2, 403),
        response(
            400,
            {"error": True, "error_code": 20, "error_message": "Supplier '2' not found."},
        ),
        response(
            400,
            {"error": True, "error_code": 23, "error_message": "Product '2' not found."},
        ),
        response(
            400,
            {"error": False, "error_code": 20, "error_message": "Product '2' not found."},
        ),
        response(400, ["Product '2' not found."]),
    ],
)
def test_unrelated_or_unmatched_errors_do_not_remove_lines(sink, http, rejection):
    responses, calls = http
    responses.append(rejection)

    with pytest.raises(RuntimeError):
        sink.upsert_record(order(2, 3), {})

    assert calls == [("POST", "purchaseorders", order(2, 3))]


def test_missing_product_on_update_is_not_retried(sink, http):
    responses, calls = http
    responses.append(missing_product(2))
    payload = {**order(2, 3), "idpurchaseorder": 900}

    with pytest.raises(RuntimeError, match="Product '2' not found"):
        sink.upsert_record(payload, {})

    assert calls == [("PUT", "purchaseorders/900", payload)]


def test_purchase_status_failure_does_not_restart_creation(sink, http):
    responses, calls = http
    responses.extend([response(201, {"idpurchaseorder": 900}), missing_product(2)])

    with pytest.raises(RuntimeError, match="Product '2' not found"):
        sink.upsert_record(order(2, 3), {})

    assert calls == [
        ("POST", "purchaseorders", order(2, 3)),
        ("POST", "purchaseorders/900/mark-as-purchased", None),
    ]


def test_repeated_missing_product_error_stops_when_no_line_matches(sink, http):
    responses, calls = http
    responses.extend([missing_product(2), missing_product(2)])

    with pytest.raises(RuntimeError, match="Product '2' not found"):
        sink.upsert_record(order(2, 3), {})

    assert calls == [
        ("POST", "purchaseorders", order(2, 3)),
        ("POST", "purchaseorders", order(3)),
    ]
