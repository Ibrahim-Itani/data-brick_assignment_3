"""
Open-Mateo weather engine backing the weather-mcp-server.Some functionality 
1- Current conditions - e.g. get_current_weather(location) - temperature, conditions, humidity, wind for a given location (city name, zip, or lat/lon - your choice).
2- Forecast - e.g. get_forecast(location, days) - a multi-day forecast (temp high/low, precipitation chance, conditions) for the next N days.
3- Simple recommendation - e.g. get_travel_recommendation(location, date) - some derived judgment call built from the raw forecast data (e.g. "bring an umbrella if precipitation chance > 40%"). 
This is where you show reasoning, not just a passthrough of the raw API response.
"""

import base64
import os

from databricks.sdk import WorkspaceClient

_w = WorkspaceClient()

def _secret(key: str) -> str:
    """Fetch and base64-decode a value from the Databricks secret scope."""
    secret = _w.secrets.get_secret(scope=_SECRET_SCOPE, key=key)
    return base64.b64decode(secret.value).decode("utf-8")
