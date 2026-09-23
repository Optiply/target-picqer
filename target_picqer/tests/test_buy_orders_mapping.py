"""Tests for mapping Optiply BuyOrders to Picqer purchase orders."""

from __future__ import annotations

from typing import Any, cast

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
