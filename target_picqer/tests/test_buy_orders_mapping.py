"""Tests for mapping Optiply BuyOrders to Picqer purchase orders."""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import Mock, call

import pytest

from target_picqer.sinks import BuyOrders


def make_sink(config: dict[str, Any] | None = None) -> Any:
    sink = cast(Any, object.__new__(BuyOrders))
    sink._config = (
        config
        if config is not None
        else {
            "buy_order_export_warehouse": "6178",
            "buy_order_description_field": "remarks",
            "buy_order_description_template": "Ordernummer Optiply: {{buy_order_id}}",
        }
    )
    return sink


def test_buy_orders_stream_mapping_uses_default_data_singer_payload():
    sink = make_sink()
    record = {
        "id": 123456,
        "transaction_date": "2026-07-03T09:15:00Z",
        "created_at": "2026-07-10",
        "customer_id": 7890,
        "supplier_name": "Example Supplier",
        "supplier_remoteId": "42",
        "externalid": 123456,
        "line_items": '[{"sku":"SKU-001","line_id":555001,"product_remoteId":"10001","quantity":12,"lot_size":1},{"sku":"SKU-002","line_id":555002,"product_remoteId":"10002","quantity":6,"lot_size":3}]',
    }

    payload = sink.preprocess_record(record, {})

    assert payload == {
        "idsupplier": 42,
        "idwarehouse": 6178,
        "delivery_date": "2026-07-10",
        "remarks": "Ordernummer Optiply: 123456",
        "products": [
            {"idproduct": 10001, "amount": 12},
            {"idproduct": 10002, "amount": 6},
        ],
    }


def test_buy_orders_writes_id_only_to_configured_description_field():
    sink = make_sink(
        {
            "buy_order_export_warehouse": "6178",
            "buy_order_description_field": "supplier_orderid",
            "buy_order_description_template": "Optiply-{{buy_order_id}}",
        }
    )

    payload = sink.preprocess_record(
        {
            "id": 123456,
            "created_at": "2026-07-10",
            "supplier_remoteId": "42",
            "line_items": [{"product_remoteId": "10001", "quantity": 12}],
        },
        {},
    )

    assert payload["supplier_orderid"] == "Optiply-123456"
    assert "remarks" not in payload


def test_buy_orders_uses_supplier_name_for_picqer_fulfilment():
    sink = make_sink({"buy_order_export_warehouse": "6178", "picqer_fulfilment": True})

    payload = sink.preprocess_record(
        {
            "id": 123456,
            "created_at": "2026-07-10",
            "supplier_name": "Example Supplier",
            "supplier_remoteId": "42",
            "line_items": [{"product_remoteId": "10001", "quantity": 12}],
        },
        {},
    )

    assert payload["supplier_name"] == "Example Supplier"
    assert "idsupplier" not in payload


def test_buy_orders_adds_configured_fulfilment_customer():
    sink = make_sink(
        {
            "buy_order_export_warehouse": "6178",
            "idfulfilment_customer": "10835",
        }
    )

    payload = sink.preprocess_record(
        {
            "id": 123456,
            "created_at": "2026-07-10",
            "supplier_remoteId": "42",
            "line_items": [{"product_remoteId": "10001", "quantity": 12}],
        },
        {},
    )

    assert payload["idfulfilment_customer"] == 10835


@pytest.mark.parametrize("value", ["not-a-number", True])
def test_buy_orders_rejects_invalid_fulfilment_customer(value):
    sink = make_sink(
        {
            "buy_order_export_warehouse": "6178",
            "idfulfilment_customer": value,
        }
    )

    with pytest.raises(
        RuntimeError,
        match="idfulfilment_customer must be a numeric Picqer ID",
    ):
        sink.preprocess_record(
            {
                "id": 123456,
                "supplier_remoteId": "42",
                "line_items": [{"product_remoteId": "10001", "quantity": 12}],
            },
            {},
        )


def test_buy_orders_requires_configured_warehouse():
    sink = make_sink({})

    with pytest.raises(
        RuntimeError,
        match="Missing buy_order_export_warehouse config",
    ):
        sink.preprocess_record(
            {
                "id": 123456,
                "supplier_remoteId": "42",
                "line_items": [{"product_remoteId": "10001", "quantity": 12}],
            },
            {},
        )


def test_buy_orders_requires_product_remote_id():
    sink = make_sink()

    with pytest.raises(RuntimeError, match="Line 555001 missing product_remoteId"):
        sink.preprocess_record(
            {
                "id": 123456,
                "supplier_remoteId": "42",
                "line_items": [{"line_id": 555001, "quantity": 12}],
            },
            {},
        )


@pytest.mark.parametrize(
    "order_dates,expected_header_date",
    [
        ({"created_at": "2026-07-10"}, "2026-07-10"),
        ({"delivery_date": "2026-07-15"}, "2026-07-15"),
        (
            {"created_at": "2026-07-10", "delivery_date": "2026-07-15T09:30:00Z"},
            "2026-07-15T09:30:00Z",
        ),
        ({"created_at": "2026-07-10", "delivery_date": None}, "2026-07-10"),
        ({"created_at": "2026-07-10", "delivery_date": ""}, "2026-07-10"),
    ],
)
@pytest.mark.parametrize("existing_order", [False, True], ids=["create", "update"])
@pytest.mark.parametrize(
    "flag_config,line_fields,expected_fields",
    [
        ({}, {"delivery_date": "2026-07-12"}, {}),
        ({"export_line_delivery_date": False}, {"delivery_date": "2026-07-12"}, {}),
        (
            {"export_line_delivery_date": True},
            {"delivery_date": "2026-07-12"},
            {"delivery_date": "2026-07-12"},
        ),
        ({"export_line_delivery_date": True}, {}, {}),
        ({"export_line_delivery_date": True}, {"delivery_date": None}, {}),
        ({"export_line_delivery_date": True}, {"delivery_date": ""}, {}),
    ],
)
def test_buy_orders_export_line_delivery_date(
    monkeypatch,
    existing_order,
    flag_config,
    line_fields,
    expected_fields,
    order_dates,
    expected_header_date,
):
    sink = make_sink({"buy_order_export_warehouse": "6178", **flag_config})
    sink.logger = Mock()
    response = Mock(status_code=200)
    response.json.return_value = {
        "idpurchaseorder": 900,
        "products": [
            {
                "idproduct": 10001,
                "idpurchaseorder_product": 7001,
                "delivery_date": "2026-07-01",
            }
        ],
    }
    request = Mock(return_value=response)
    monkeypatch.setattr(sink, "request_api", request)
    record = {
        "id": 123456,
        **order_dates,
        "supplier_remoteId": "42",
        "line_items": [
            {"product_remoteId": "10001", "quantity": 12, **line_fields},
            {"product_remoteId": "10002", "quantity": 6, **line_fields},
        ],
    }
    if existing_order:
        record["idpurchaseorder"] = 900

    sink.upsert_record(sink.preprocess_record(record, {}), {})

    expected_payload = {
        "idsupplier": 42,
        "idwarehouse": 6178,
        "delivery_date": expected_header_date,
        "products": [
            {"idproduct": 10001, "amount": 12, **expected_fields},
            {"idproduct": 10002, "amount": 6, **expected_fields},
        ],
    }
    if existing_order:
        expected_payload["idpurchaseorder"] = 900
        assert request.call_args_list == [
            call("GET", "purchaseorders/900"),
            call(
                "PUT",
                "purchaseorders/900/products/7001",
                request_data={"amount": 12, **expected_fields},
            ),
            call(
                "POST",
                "purchaseorders/900/products",
                request_data=expected_payload["products"][1],
            ),
            call("PUT", endpoint="purchaseorders/900", request_data=expected_payload),
        ]
    else:
        assert request.call_args_list == [
            call("POST", endpoint="purchaseorders", request_data=expected_payload),
            call("POST", endpoint="purchaseorders/900/mark-as-purchased"),
        ]
