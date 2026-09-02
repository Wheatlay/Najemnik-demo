from core.domain.commute import commute_distances, haversine_km


def test_haversine_km_same_point_is_zero():
    assert haversine_km(50.26, 19.02, 50.26, 19.02) == 0.0


def test_haversine_km_known_distance():
    # Katowice centrum -> Kraków centrum, roughly 65-75 km as the crow flies.
    km = haversine_km(50.2649, 19.0238, 50.0614, 19.9366)
    assert 60 < km < 80


def test_commute_distances_no_coords_returns_empty():
    assert commute_distances(None, None, [{"name": "Praca", "lat": 50.0, "lon": 19.0}]) == []


def test_commute_distances_computes_per_point():
    points = [
        {"name": "Praca", "lat": 50.26, "lon": 19.02},
        {"name": "Uczelnia", "lat": 50.29, "lon": 19.13},
    ]
    result = commute_distances(50.26, 19.02, points)
    assert result[0] == {"name": "Praca", "km": 0.0}
    assert result[1]["name"] == "Uczelnia"
    assert result[1]["km"] > 0
