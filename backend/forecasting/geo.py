"""Shared geodesic helpers for forecasting — great-circle miles on EPSG:4326.

Used by the region adapters (to populate NetworkLink.length_mi from geometry when
the source model carries no native length) and by vmt.py (the held-segment
fallback). Great-circle on lat/lng — NEVER Euclidean on decimal degrees. Pure
stdlib math, so importing this costs the lean app nothing.
"""

import math

EARTH_RADIUS_MI = 3958.8


def haversine_mi(lng1, lat1, lng2, lat2):
    """Great-circle distance in miles between two EPSG:4326 (lng, lat) points."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_MI * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def polyline_length_mi(coords):
    """Summed great-circle length (mi) of a [(lng, lat), ...] polyline in EPSG:4326."""
    pts = coords or []
    return sum(haversine_mi(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1])
               for i in range(len(pts) - 1))
