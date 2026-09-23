"""Picqer target sink class, which handles writing streams."""

from __future__ import annotations

import json
from typing import Any

from target_picqer.client import PicqerSink


class BuyOrders(PicqerSink):
    """Sink that writes Optiply BuyOrders as Picqer purchase orders."""

    names_available = ["buy_orders", "buyorders", "purchase_orders", "purchaseorders"]

    @property
    def name(self) -> str:
        return "BuyOrders"

    @property
    def endpoint(self) -> str:
        return "purchaseorders"

    def _record_identifier(self, record: dict) -> Any:
        return (
            record.get("id")
            or record.get("externalid")
            or record.get("externalId")
            or record.get("supplier_orderid")
            or record.get("order_number")
            or "unknown"
        )

    def _record_error(self, record: dict, error: Exception) -> RuntimeError:
        return RuntimeError(
            f"{self.name} ID: {self._record_identifier(record)}, Error: {error}"
        )

    def _parse_line_items(self, record: dict) -> list[dict[str, Any]]:
        line_items = record.get("line_items")
        if line_items in (None, ""):
            return []
        if isinstance(line_items, str):
            try:
                line_items = json.loads(line_items)
            except json.JSONDecodeError as err:
                raise ValueError("line_items is not valid JSON") from err
        if not isinstance(line_items, list):
            raise ValueError("line_items must be a JSON string or list")
        return line_items

    def _line_identifier(self, line: dict, index: int) -> Any:
        return line.get("line_id") or line.get("sku") or index + 1

    def _coerce_int_if_numeric(self, value: Any) -> Any:
        if isinstance(value, str) and value.isdigit():
            return int(value)
        return value

    def _product_id_from_line(self, line: dict) -> Any:
        return self._coerce_int_if_numeric(
            line.get("product_remoteId") or line.get("product_id")
        )

    def _product_amount_from_line(self, line: dict) -> Any:
        return line.get("quantity")

    def _build_product_payload(self, line: dict, index: int) -> dict[str, Any]:
        product_id = self._product_id_from_line(line)
        if product_id in (None, ""):
            raise ValueError(
                f"Line {self._line_identifier(line, index)} missing product_remoteId"
            )

        amount = self._product_amount_from_line(line)
        if amount in (None, ""):
            raise ValueError(
                f"Line {self._line_identifier(line, index)} missing valid quantity"
            )

        payload = {
            "idproduct": product_id,
            "amount": amount,
        }

        # Optional fields accepted by Picqer. The minimal required product payload is
        # idproduct + amount; price and delivery_date are optional according to docs.
        if line.get("unit_price") not in (None, ""):
            payload["price"] = line.get("unit_price")
        if line.get("delivery_date"):
            payload["delivery_date"] = line.get("delivery_date")
        if line.get("product_name"):
            payload["name"] = line.get("product_name")

        return payload

    def _warehouse_id(self) -> Any:
        warehouse = self.config.get("buy_order_export_warehouse")
        if warehouse in (None, ""):
            raise ValueError(
                "Missing buy_order_export_warehouse config; define a warehouse "
                "before exporting Picqer purchase orders"
            )
        if isinstance(warehouse, str) and warehouse.isdigit():
            return int(warehouse)
        return warehouse

    def _add_supplier(self, payload: dict[str, Any], record: dict) -> None:
        supplier_name = record.get("supplier_name")
        supplier_remote_id = record.get("supplier_remoteId") or record.get(
            "supplier_remoteid"
        )

        if self.config.get("picqer_fulfilment"):
            if not supplier_name:
                raise ValueError("Missing supplier_name for picqer_fulfilment export")
            payload["supplier_name"] = supplier_name
            return

        if supplier_remote_id:
            payload["idsupplier"] = self._coerce_int_if_numeric(supplier_remote_id)
        elif record.get("supplier_code"):
            payload["idsupplier"] = self._coerce_int_if_numeric(
                record.get("supplier_code")
            )
        elif supplier_name:
            payload["supplier_name"] = supplier_name
        else:
            raise ValueError("Missing supplier_remoteId or supplier_name")

    def _buy_order_id(self, record: dict) -> Any:
        return record.get("id") or record.get("externalid") or record.get("externalId")

    def _render_description(self, template: str, record: dict) -> str:
        buy_order_id = self._buy_order_id(record)
        return template.replace("{{buy_order_id}}", str(buy_order_id or ""))

    def _add_description(self, payload: dict[str, Any], record: dict) -> None:
        description_field = self.config.get("buy_order_description_field")
        if not description_field:
            return

        template = (
            self.config.get("buy_order_description_template") or "{{buy_order_id}}"
        )
        payload[description_field] = self._render_description(template, record)

    def _picqer_purchase_order_id(self, record: dict) -> Any:
        return record.get("idpurchaseorder") or record.get("picqer_id")

    def get_purchase_order(self, order_id) -> dict[str, Any]:
        po = self.request_api("GET", f"purchaseorders/{order_id}")
        if po.status_code != 200:
            return {}
        return po.json()

    def search_product(self, products, search):
        if products:
            for product in products:
                if str(product.get("idproduct")) == str(search):
                    return product
        return {}

    def update_po_product(self, order_id, idpurchaseorder_product, payload):
        res = self.request_api(
            "PUT",
            f"purchaseorders/{order_id}/products/{idpurchaseorder_product}",
            request_data=payload,
        )
        return res

    def add_po_product(self, order_id, payload):
        res = self.request_api(
            "POST", f"purchaseorders/{order_id}/products", request_data=payload
        )
        return res

    def _sync_existing_line_items(
        self, record: dict, line_items: list[dict[str, Any]], purchase_order_id: Any
    ) -> None:
        purchase_order_detail = self.get_purchase_order(purchase_order_id)
        if not purchase_order_detail:
            return

        purchase_products = purchase_order_detail.get("products", [])
        for index, line in enumerate(line_items):
            product_payload = self._build_product_payload(line, index)
            product = self.search_product(
                purchase_products, product_payload["idproduct"]
            )
            if product:
                update_payload = {
                    key: product_payload[key]
                    for key in ("amount", "price", "delivery_date")
                    if key in product_payload
                }
                self.update_po_product(
                    purchase_order_id,
                    product.get("idpurchaseorder_product"),
                    update_payload,
                )
            else:
                self.add_po_product(purchase_order_id, product_payload)

    def preprocess_record(self, record: dict, context: dict) -> dict[str, Any]:
        try:
            line_items = self._parse_line_items(record)
            purchase_order_id = self._picqer_purchase_order_id(record)
            if purchase_order_id:
                self._sync_existing_line_items(record, line_items, purchase_order_id)

            products = [
                self._build_product_payload(line, index)
                for index, line in enumerate(line_items)
            ]
            if not products:
                raise ValueError("Missing line_items for Picqer purchase order")

            mapping: dict[str, Any] = {
                "delivery_date": self.convert_datetime(record.get("created_at")),
                "idwarehouse": self._warehouse_id(),
                "products": products,
            }
            self._add_supplier(mapping, record)
            self._add_description(mapping, record)

            if self.config.get("buy_order_export_as_concept"):
                mapping["status"] = "concept"
            if purchase_order_id:
                mapping["idpurchaseorder"] = purchase_order_id

            return mapping
        except Exception as err:
            raise self._record_error(record, err) from err

    def upsert_record(
        self, record: dict, context: dict
    ) -> tuple[Any, bool, dict[str, Any]]:
        endpoint = self.endpoint
        method_type = "POST"
        action_text = "created"
        state_updates = {}
        purchase_order_id = self._picqer_purchase_order_id(record)
        if purchase_order_id:
            endpoint = f"{endpoint}/{purchase_order_id}"
            method_type = "PUT"
            state_updates["is_updated"] = True
            action_text = "updated"
        if not record:
            return None, False, state_updates

        try:
            buy_order_response = self.request_api(
                method_type, endpoint=endpoint, request_data=record
            )
            po_id = buy_order_response.json()["idpurchaseorder"]
            if (
                not self.config.get("buy_order_export_as_concept")
                and not purchase_order_id
            ):
                self.request_api(
                    "POST", endpoint=f"{self.endpoint}/{po_id}/mark-as-purchased"
                )
            self.logger.info(
                f"Purchase Order Successfully {action_text} with ID {po_id}"
            )
        except Exception as err:
            raise self._record_error(record, err) from err
        return po_id, True, state_updates


# Backwards-compatible import name for existing references/tests.
PurchaseOrders = BuyOrders
