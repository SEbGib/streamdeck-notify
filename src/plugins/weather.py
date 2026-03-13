"""Weather plugin — shows current weather from Open-Meteo.

Free API, no key needed. Uses urllib.request (stdlib).
"""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.parse
import urllib.request

from .base import BasePlugin, NotificationState

logger = logging.getLogger(__name__)

_OPENMETEO_URL = "https://api.open-meteo.com/v1/forecast"

# WMO weather codes → (description FR, icon hint)
# WMO weather codes → (description FR, icon name)
_WMO_CODES: dict[int, tuple[str, str]] = {
    0: ("Ciel dégagé", "weather_sun"),
    1: ("Peu nuageux", "weather_partly_cloudy"),
    2: ("Partiellement nuageux", "weather_partly_cloudy"),
    3: ("Couvert", "weather_cloudy"),
    45: ("Brouillard", "weather_fog"),
    48: ("Brouillard givrant", "weather_fog"),
    51: ("Bruine légère", "weather_rain"),
    53: ("Bruine", "weather_rain"),
    55: ("Bruine forte", "weather_rain"),
    56: ("Bruine verglaçante", "weather_rain"),
    57: ("Bruine verglaçante forte", "weather_rain"),
    61: ("Pluie légère", "weather_rain"),
    63: ("Pluie", "weather_rain"),
    65: ("Pluie forte", "weather_rain"),
    66: ("Pluie verglaçante", "weather_rain"),
    67: ("Pluie verglaçante forte", "weather_rain"),
    71: ("Neige légère", "weather_snow"),
    73: ("Neige", "weather_snow"),
    75: ("Neige forte", "weather_snow"),
    77: ("Grains de neige", "weather_snow"),
    80: ("Averses légères", "weather_rain"),
    81: ("Averses", "weather_rain"),
    82: ("Averses fortes", "weather_rain"),
    85: ("Averses de neige", "weather_snow"),
    86: ("Averses de neige fortes", "weather_snow"),
    95: ("Orage", "weather_storm"),
    96: ("Orage + grêle", "weather_storm"),
    99: ("Orage + forte grêle", "weather_storm"),
}


class WeatherPlugin(BasePlugin):
    """Show current weather on Stream Deck via Open-Meteo."""

    def __init__(self, config: dict):
        super().__init__(config)
        self._lat: float = config.get("latitude", 44.0553)
        self._lon: float = config.get("longitude", 5.1325)
        self._location: str = config.get("location", "Mazan")

    async def poll(self) -> NotificationState:
        try:
            data = await self._fetch_weather()
        except Exception:
            logger.exception("Weather poll failed")
            return NotificationState(label="Météo", subtitle="Erreur", color="#4A90D9")

        current = data.get("current", {})
        temp = current.get("temperature_2m")
        code = current.get("weather_code", -1)
        description, icon = _WMO_CODES.get(code, ("", "weather"))

        label = f"{temp:.0f}°C" if temp is not None else "N/A"

        return NotificationState(
            count=0,
            label=label,
            subtitle=description or self._location,
            urgent=False,
            color="#4A90D9",
            extra={"weather_icon": icon},
        )

    async def _fetch_weather(self) -> dict:
        params = urllib.parse.urlencode({
            "latitude": self._lat,
            "longitude": self._lon,
            "current": "temperature_2m,weather_code",
            "timezone": "auto",
        })
        url = f"{_OPENMETEO_URL}?{params}"
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._http_get, url)

    @staticmethod
    def _http_get(url: str) -> dict:
        req = urllib.request.Request(url, headers={"User-Agent": "streamdeck-notify/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
