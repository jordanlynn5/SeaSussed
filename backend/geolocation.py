"""IP geolocation via ip-api.com (free, no API key)."""

import ipaddress
import logging
from functools import lru_cache

import httpx

from models import UserLocation

log = logging.getLogger(__name__)

_IP_API_URL = "http://ip-api.com/json/{ip}"
_TIMEOUT = 3.0
_FIELDS = "city,regionName,country,lat,lon"


@lru_cache(maxsize=256)
def get_user_location(ip: str) -> UserLocation | None:
    """Geolocate an IP address. Returns None on failure."""
    if not ip or _is_private_ip(ip):
        return None

    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            resp = client.get(
                _IP_API_URL.format(ip=ip),
                params={"fields": _FIELDS},
            )
            resp.raise_for_status()
        data = resp.json()
        city = data.get("city", "")
        if not city:
            return None
        return UserLocation(
            city=city,
            region=data.get("regionName", ""),
            country=data.get("country", ""),
            lat=float(data.get("lat", 0)),
            lon=float(data.get("lon", 0)),
        )
    except Exception as e:
        log.warning("get_user_location(%s) failed: %s", ip, e)
        return None


def _is_private_ip(ip: str) -> bool:
    """Return True for loopback, private, or link-local IPs."""
    try:
        return ipaddress.ip_address(ip).is_private
    except ValueError:
        return True
