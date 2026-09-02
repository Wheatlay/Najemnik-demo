"""Straight-line ("as the crow flies") distance to user-defined reference
points (Settings.commute_points) - this app has no geocoding/routing
integration, so this is a placeholder signal, not real drive/transit time.
The existing commute_time_car/commute_time_public listing fields stay
manual text entries until (if ever) a routing API gets wired in.
"""
import math


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def commute_distances(lat: float | None, lon: float | None, points: list[dict]) -> list[dict]:
    """[{"name", "km"}, ...] from (lat, lon) to each configured reference
    point, or [] if the listing has no pin yet."""
    if lat is None or lon is None:
        return []
    return [
        {"name": p["name"], "km": round(haversine_km(lat, lon, p["lat"], p["lon"]), 1)}
        for p in points
    ]
