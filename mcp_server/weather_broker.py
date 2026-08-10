"""
Open-Meteo weather engine backing the weather-mcp-server.

Functionality:
1- Current conditions - get_current_weather(location) - temperature, conditions, humidity, wind
2- Forecast - get_forecast(location, days) - multi-day forecast with temp high/low, precipitation
3- Travel recommendation - get_travel_recommendation(location, date) - weather-based travel advice
"""

import base64
import os
import logging
from datetime import datetime, timedelta
from typing import Dict, Any
import requests

from databricks.sdk import WorkspaceClient

logger = logging.getLogger(__name__)
_w = WorkspaceClient()

# Open-Meteo API endpoints (free, no API key required)
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"

def _secret(key: str) -> str:
    """Fetch and base64-decode a value from the Databricks secret scope."""
    secret = _w.secrets.get_secret(scope=_SECRET_SCOPE, key=key)
    return base64.b64decode(secret.value).decode("utf-8")

def _geocode_location(location: str) -> Dict[str, float]:
    """
    Convert a location name (e.g., 'San Francisco, CA') to latitude/longitude.
    
    Args:
        location: City name, optionally with state/country
    
    Returns:
        Dict with 'latitude', 'longitude', and 'name'
    
    Raises:
        ValueError: If location cannot be geocoded
    """
    try:
        response = requests.get(
            GEOCODING_URL,
            params={"name": location, "count": 1, "language": "en", "format": "json"},
            timeout=10
        )
        response.raise_for_status()
        data = response.json()
        
        if not data.get("results"):
            raise ValueError(f"Location '{location}' not found")
        
        result = data["results"][0]
        return {
            "latitude": result["latitude"],
            "longitude": result["longitude"],
            "name": result["name"]
        }
    except Exception as e:
        logger.error(f"Geocoding failed for '{location}': {e}")
        raise ValueError(f"Could not geocode location '{location}': {str(e)}")

def get_current_weather(location: str) -> Dict[str, Any]:
    """
    Get current weather conditions for a location.
    
    Args:
        location: City name and state (e.g., 'San Francisco, CA')
    
    Returns:
        Dict with temperature, conditions, humidity, and wind speed
    """
    try:
        # Geocode the location
        coords = _geocode_location(location)
        
        # Fetch current weather from Open-Meteo
        response = requests.get(
            WEATHER_URL,
            params={
                "latitude": coords["latitude"],
                "longitude": coords["longitude"],
                "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code",
                "temperature_unit": "fahrenheit",
                "wind_speed_unit": "mph"
            },
            timeout=10
        )
        response.raise_for_status()
        data = response.json()
        
        current = data.get("current", {})
        
        # Map weather codes to conditions
        weather_code = current.get("weather_code", 0)
        conditions = _weather_code_to_description(weather_code)
        
        return {
            "location": coords["name"],
            "temperature_f": current.get("temperature_2m"),
            "conditions": conditions,
            "humidity_percent": current.get("relative_humidity_2m"),
            "wind_speed_mph": current.get("wind_speed_10m"),
            "timestamp": current.get("time")
        }
    except Exception as e:
        logger.error(f"Failed to get current weather for '{location}': {e}")
        return {"error": str(e)}

def get_forecast(location: str, days: float) -> Dict[str, Any]:
    """
    Get multi-day weather forecast.
    
    Args:
        location: City name and state (e.g., 'Boston, MA')
        days: Number of days to forecast (max 16)
    
    Returns:
        Dict with daily forecasts including temp high/low, precipitation, conditions
    """
    try:
        # Geocode the location
        coords = _geocode_location(location)
        
        # Ensure days is within valid range
        days = max(1, min(int(days), 16))
        
        # Fetch forecast from Open-Meteo
        response = requests.get(
            WEATHER_URL,
            params={
                "latitude": coords["latitude"],
                "longitude": coords["longitude"],
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
                "temperature_unit": "fahrenheit",
                "forecast_days": days
            },
            timeout=10
        )
        response.raise_for_status()
        data = response.json()
        
        daily = data.get("daily", {})
        dates = daily.get("time", [])
        temp_max = daily.get("temperature_2m_max", [])
        temp_min = daily.get("temperature_2m_min", [])
        precip_prob = daily.get("precipitation_probability_max", [])
        weather_codes = daily.get("weather_code", [])
        
        forecast_days = []
        for i in range(len(dates)):
            forecast_days.append({
                "date": dates[i],
                "temp_high_f": temp_max[i],
                "temp_low_f": temp_min[i],
                "precipitation_probability_percent": precip_prob[i],
                "conditions": _weather_code_to_description(weather_codes[i])
            })
        
        return {
            "location": coords["name"],
            "forecast_days": forecast_days
        }
    except Exception as e:
        logger.error(f"Failed to get forecast for '{location}': {e}")
        return {"error": str(e)}

def get_travel_recommendation(location: str, date: str) -> Dict[str, Any]:
    """
    Provide travel recommendations based on weather forecast.
    
    Args:
        location: City name and state
        date: Target date (YYYY-MM-DD format)
    
    Returns:
        Dict with recommendations, weather summary, and what to bring
    """
    try:
        # Parse the target date
        target_date = datetime.strptime(date, "%Y-%m-%d").date()
        today = datetime.now().date()
        days_ahead = (target_date - today).days
        
        if days_ahead < 0:
            return {"error": "Cannot provide recommendations for past dates"}
        
        if days_ahead > 16:
            return {"error": "Forecast only available up to 16 days in advance"}
        
        # Get the forecast
        forecast_data = get_forecast(location, days_ahead + 1)
        
        if "error" in forecast_data:
            return forecast_data
        
        # Find the forecast for the target date
        target_forecast = None
        for day in forecast_data.get("forecast_days", []):
            if day["date"] == date:
                target_forecast = day
                break
        
        if not target_forecast:
            return {"error": f"No forecast data available for {date}"}
        
        # Build recommendations based on weather conditions
        recommendations = []
        items_to_bring = []
        
        # Precipitation recommendations
        precip_prob = target_forecast.get("precipitation_probability_percent", 0)
        if precip_prob > 60:
            recommendations.append("High chance of precipitation - consider rescheduling outdoor activities")
            items_to_bring.extend(["umbrella", "rain jacket", "waterproof shoes"])
        elif precip_prob > 40:
            recommendations.append("Moderate chance of rain - be prepared for wet weather")
            items_to_bring.append("umbrella")
        elif precip_prob > 20:
            recommendations.append("Slight chance of rain - pack an umbrella just in case")
        else:
            recommendations.append("Low chance of precipitation - great day for outdoor activities")
        
        # Temperature recommendations
        temp_high = target_forecast.get("temp_high_f", 70)
        temp_low = target_forecast.get("temp_low_f", 50)
        
        if temp_high > 85:
            recommendations.append("Hot weather expected - stay hydrated and avoid prolonged sun exposure")
            items_to_bring.extend(["sunscreen", "hat", "water bottle"])
        elif temp_high > 75:
            recommendations.append("Warm weather - comfortable for most outdoor activities")
            items_to_bring.append("sunscreen")
        elif temp_high < 40:
            recommendations.append("Cold weather - dress in warm layers")
            items_to_bring.extend(["heavy coat", "gloves", "warm hat"])
        elif temp_high < 55:
            recommendations.append("Cool weather - bring a jacket or sweater")
            items_to_bring.append("jacket")
        
        if temp_high - temp_low > 25:
            recommendations.append("Large temperature swing expected - dress in layers")
        
        # Overall travel assessment
        conditions = target_forecast.get("conditions", "")
        if "clear" in conditions.lower() or "sunny" in conditions.lower():
            overall = "Excellent travel conditions"
        elif precip_prob > 60 or temp_high > 90 or temp_high < 32:
            overall = "Challenging travel conditions - plan accordingly"
        else:
            overall = "Good travel conditions with minor considerations"
        
        return {
            "location": forecast_data.get("location"),
            "date": date,
            "overall_assessment": overall,
            "weather_summary": {
                "conditions": conditions,
                "high_temp_f": temp_high,
                "low_temp_f": temp_low,
                "precipitation_probability_percent": precip_prob
            },
            "recommendations": recommendations,
            "items_to_bring": list(set(items_to_bring))  # Remove duplicates
        }
    except Exception as e:
        logger.error(f"Failed to get travel recommendation for '{location}' on '{date}': {e}")
        return {"error": str(e)}

def _weather_code_to_description(code: int) -> str:
    """
    Convert WMO weather code to human-readable description.
    
    Based on Open-Meteo's weather code documentation:
    https://open-meteo.com/en/docs
    """
    weather_codes = {
        0: "Clear sky",
        1: "Mainly clear",
        2: "Partly cloudy",
        3: "Overcast",
        45: "Foggy",
        48: "Depositing rime fog",
        51: "Light drizzle",
        53: "Moderate drizzle",
        55: "Dense drizzle",
        56: "Light freezing drizzle",
        57: "Dense freezing drizzle",
        61: "Slight rain",
        63: "Moderate rain",
        65: "Heavy rain",
        66: "Light freezing rain",
        67: "Heavy freezing rain",
        71: "Slight snow",
        73: "Moderate snow",
        75: "Heavy snow",
        77: "Snow grains",
        80: "Slight rain showers",
        81: "Moderate rain showers",
        82: "Violent rain showers",
        85: "Slight snow showers",
        86: "Heavy snow showers",
        95: "Thunderstorm",
        96: "Thunderstorm with slight hail",
        99: "Thunderstorm with heavy hail"
    }
    return weather_codes.get(code, f"Unknown (code {code})")
