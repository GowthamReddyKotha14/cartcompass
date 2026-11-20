import pytest

from cartcompass.geo import (drive_miles, haversine_miles, parse_gazetteer, parse_home,
                             route_miles, zip_center)

BG = (41.3925, -83.6513)        # Kroger, N Main St, Bowling Green
WATERVILLE = (41.5000, -83.7180)


def test_haversine_known_distance():
    # Bowling Green to Toledo city centre is about 20 miles in a straight line.
    assert haversine_miles((41.3748, -83.6513), (41.6528, -83.5379)) == pytest.approx(20, abs=1.5)


def test_road_distance_is_longer_than_straight_line():
    assert drive_miles(BG, WATERVILLE) > haversine_miles(BG, WATERVILLE)


def test_round_trip_picks_the_shorter_order():
    home = (41.37, -83.65)
    far, near = (41.60, -83.70), (41.40, -83.66)
    assert route_miles(home, [far, near]) == pytest.approx(route_miles(home, [near, far]))
    assert route_miles(home, [near]) < route_miles(home, [near, far])
    assert route_miles(home, []) == 0


@pytest.mark.parametrize("sep", ["\t", "|"])
def test_gazetteer_formats(sep, tmp_path):
    text = sep.join(["GEOID", "ALAND", "AWATER", "ALAND_SQMI", "AWATER_SQMI", "INTPTLAT", "INTPTLONG    "]) + "\n"
    text += sep.join(["43402", "1", "0", "1", "0", "41.389", "-83.656  "]) + "\n"
    assert parse_gazetteer(text) == {"43402": (41.389, -83.656)}
    f = tmp_path / "z.tsv"
    f.write_text(text)
    assert zip_center("43402", f) == (41.389, -83.656)
    with pytest.raises(KeyError, match="--home"):
        zip_center("99999", f)


def test_parse_home():
    assert parse_home("41.38, -83.65") == (41.38, -83.65)
    with pytest.raises(ValueError):
        parse_home("200,0")
