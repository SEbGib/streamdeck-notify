"""Weather plugin — shows current weather from OpenWeatherMap.

Uses urllib.request (stdlib) for HTTP calls.
"""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.request
import urllib.error

from .base import BasePlugin, NotificationState

logger = logging.getLogger(__name__)

_OWM_URL = "https://api.openweathermap.org/data/2.5/weather"


class WeatherPlugin(BasePlugin):
    """Show current weather on Stream Deck."""

    def __init__(self, config: dict):
        super().__init__(config)
        self._api_key: str = config.get("api_key", "")
        self._city: str = config.get("city", "Paris")
        self._units: str = config.get("units", "metric")
        self._lang: str = config.get("lang", "fr")

    async def setup(self) -> None:
        if not self._api_key:
            logger.warning("Weather: no api_key configured")

    async def poll(self) -> NotificationState:
        if not self._api_key:
            return NotificationState(
                label="Météo", subtitle="No API key", color="#4A90D9"
            )

        try:
            data = await self._fetch_weather()
        except Exception:
            logger.exception("Weather poll failed")
            return NotificationState(label="Météo", subtitle="Error", color="#4A90D9")

        temp = data.get("main", {}).get("temp")
        description = ""
        weather_list = data.get("weather", [])
        if weather_list:
            description = weather_list[0].get("description", "").capitalize()

        unit_symbol = "°C" if self._units == "metric" else "°F"
        label = f"{temp:.0f}{unit_symbol}" if temp is not None else "N/A"

        return NotificationState(
            count=0,
            label=label,
            subtitle=description or self._city,
            urgent=False,
            color="#4A90D9",
        )

    async def _fetch_weather(self) -> dict:
        """Fetch weather data from OpenWeatherMap."""
        url = (
            f"{_OWM_URL}?q={self._city}"
            f"&appid={self._api_key}"
            f"&units={self._units}"
            f"&lang={self._lang}"
        )
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._http_get, url)

    @staticmethod
    def _http_get(url: str) -> dict:
        """Blocking HTTP GET returning parsed JSON."""
        req = urllib.request.Request(url, headers={"User-Agent": "streamdeck-notify/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
