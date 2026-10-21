from __future__ import annotations

from base64 import b64encode
from datetime import datetime
import json
import re
from typing import Any

from hotglue_singer_sdk.exceptions import (  # type: ignore[reportMissingImports]
    FatalAPIError,
    RetriableAPIError,
)
from hotglue_singer_sdk.target_sdk.client import HotglueSink  # type: ignore[reportMissingImports]

ERROR_MESSAGE_KEYS = (
    "message",
    "error",
    "errors",
    "errormessage",
    "error_message",
    "error_description",
)


class MissingProductError(FatalAPIError):
    """Picqer rejected a specific product ID."""

    def __init__(self, message: str, product_id: str) -> None:
        super().__init__(message)
        self.product_id = product_id


class PicqerSink(HotglueSink):
    api_version = "v1"

    @property
    def base_url(self) -> str:
        org = self.config.get("org")
        base_url = f"https://{org}.picqer.com/api/{self.api_version}/"
        return base_url

    def auth_header(self):
        user = self.config.get("api_key")
        passwd = None
        token = b64encode(f"{user}:{passwd}".encode()).decode()
        return f"Basic {token}"

    @property
    def http_headers(self):
        headers = {"Authorization": self.auth_header()}
        headers["User-Agent"] = "MyPicqerClient (picqer.com/api - support@picqer.com)"
        return headers

    def validate_input(self, record: dict):
        return record

    def _extract_error_message_from_json(self, body: Any) -> str | None:
        if isinstance(body, str):
            return body
        if isinstance(body, list):
            messages = [self._extract_error_message_from_json(item) for item in body]
            return "; ".join(message for message in messages if message) or None
        if not isinstance(body, dict):
            return None

        for key in ERROR_MESSAGE_KEYS:
            if key in body:
                message = self._extract_error_message_from_json(body[key])
                if message:
                    return message

        messages = [
            self._extract_error_message_from_json(value) for value in body.values()
        ]
        return "; ".join(message for message in messages if message) or None

    def response_error_message(self, response) -> str:
        try:
            message = self._extract_error_message_from_json(response.json())
            if message:
                return message
        except ValueError:
            pass

        if response.text:
            return response.text

        return super().response_error_message(response)

    def validate_response(self, response) -> None:
        if response.status_code in [429] or 500 <= response.status_code < 600:
            message = self.response_error_message(response)
            self.logger.error({"error": message})
            raise RetriableAPIError(message, response)
        if 400 <= response.status_code < 500:
            message = self.response_error_message(response)
            self.logger.error({"error": message})
            if response.status_code in (400, 404, 422):
                try:
                    body = response.json()
                except ValueError:
                    body = None
                if (
                    isinstance(body, dict)
                    and body.get("error") is True
                    and body.get("error_code") == 20
                ):
                    product = re.fullmatch(
                        r"Product '([0-9]+)' not found\.",
                        str(body.get("error_message", "")),
                    )
                    if product:
                        raise MissingProductError(message, product.group(1))
            raise FatalAPIError(message)

    def parse_json(self, input):
        # if it's a string, use json.loads, else return whatever it is
        if isinstance(input, str):
            return json.loads(input)
        return input

    def convert_datetime(self, date: Any):
        # convert datetime.datetime into str
        if isinstance(date, datetime):
            # This is the format -> "2022-08-15T19:16:35Z"
            return date.strftime("%Y-%m-%dT%H:%M:%SZ")
        return date
