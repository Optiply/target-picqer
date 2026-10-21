"""Picqer target class."""
# pyright: reportIncompatibleVariableOverride=false, reportIncompatibleMethodOverride=false
# pyright: reportAttributeAccessIssue=false, reportReturnType=false
# pyright: reportAssignmentType=false, reportCallIssue=false

from __future__ import annotations

from hotglue_singer_sdk import typing as th
from hotglue_singer_sdk.sinks import Sink
from hotglue_singer_sdk.target_sdk.target import TargetHotglue

from target_picqer.sinks import (
    BuyOrders,
)


class TargetPicqer(TargetHotglue):
    """Sample target for Picqer."""

    SINK_TYPES = [BuyOrders]
    MAX_PARALLELISM = 10
    name = "target-picqer"
    config_jsonschema = th.PropertiesList(
        th.Property("api_key", th.StringType, required=True),
        th.Property("org", th.StringType, required=True),
        th.Property("picqer_fulfilment", th.BooleanType, default=False),
        th.Property("buy_order_export_as_concept", th.BooleanType, default=False),
        th.Property("buy_order_export_warehouse", th.StringType),
        th.Property("buy_order_description_field", th.StringType),
        th.Property("buy_order_description_template", th.StringType),
        th.Property("idfulfilment_customer", th.StringType),
    ).to_dict()

    def get_sink_class(self, stream_name: str) -> type[Sink] | None:
        """Get sink for a stream."""
        return next(
            (
                sink_class
                for sink_class in self.SINK_TYPES
                if stream_name.lower() in sink_class.names_available
            ),
            None,
        )


if __name__ == "__main__":
    TargetPicqer.cli()
