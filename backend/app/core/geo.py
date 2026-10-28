import math

_EARTH_RADIUS_METERS = 6_371_000.0


def haversine_meters(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Jarak lingkaran-besar (meter) antara dua titik (lintang, bujur)."""
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    half_chord = (
        math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_METERS * math.asin(min(1.0, math.sqrt(half_chord)))
