import pytest

from calc import PRESETS, score_airports

K = {
    "A": {"pax_growth": 0.10, "load_factor": 0.90, "seat_growth": 0.00, "scale": 1_000, "intl_share": 0.1, "delay": 0},
    "B": {"pax_growth": 0.00, "load_factor": 0.70, "seat_growth": 0.10, "scale": 3_000, "intl_share": 0.2, "delay": 2},
    "C": {"pax_growth": 0.05, "load_factor": 0.80, "seat_growth": 0.05, "scale": 2_000, "intl_share": 0.3, "delay": 1},
}


def by_code(result):
    return {r["code"]: r for r in result["ranking"]}


def test_single_kpi_minmax_extremes_and_midpoint():
    r = score_airports(K, "expansion", {"pax_growth": 1})
    s = by_code(r)
    assert s["A"]["score"] == 100 and s["B"]["score"] == 0 and s["C"]["score"] == 50
    assert [x["code"] for x in r["ranking"]] == ["A", "C", "B"]
    assert [x["rank"] for x in r["ranking"]] == [1, 2, 3]


def test_negative_weight_flips_direction():
    r = score_airports(K, "expansion", {"seat_growth": -1})
    s = by_code(r)
    assert s["A"]["score"] == 100 and s["B"]["score"] == 0


def test_weights_are_normalised_and_echoed():
    r = score_airports(K, "expansion", {"pax_growth": 3, "load_factor": 1})
    assert r["weights_used"] == {"pax_growth": 0.75, "load_factor": 0.25}
    assert by_code(r)["A"]["score"] == 100  # best on both


def test_points_sum_to_score():
    r = score_airports(K, "expansion")
    for row in r["ranking"]:
        assert row["score"] == pytest.approx(sum(c["points"] for c in row["contributions"].values()), abs=0.06)


def test_presets_sum_to_one_in_absolute_terms():
    for name, w in PRESETS.items():
        assert sum(abs(v) for v in w.values()) == pytest.approx(1.0), name


def test_equal_values_give_half_credit():
    k = {"A": {"delay": 1, "scale": 1}, "B": {"delay": 1, "scale": 2}}
    r = score_airports(k, "expansion", {"delay": 1})
    assert {x["score"] for x in r["ranking"]} == {50.0}


def test_tie_broken_by_scale_then_code():
    k = {"Z": {"delay": 1, "scale": 5}, "A": {"delay": 1, "scale": 5}, "M": {"delay": 1, "scale": 9}}
    r = score_airports(k, "expansion", {"delay": 1})
    assert [x["code"] for x in r["ranking"]] == ["M", "A", "Z"]


def test_missing_kpi_is_not_scored_but_others_are():
    k = {**K, "D": {"pax_growth": None, "load_factor": 0.5, "seat_growth": 0, "scale": 1, "intl_share": 0, "delay": 0}}
    r = score_airports(k, "expansion")
    assert r["not_scored"] == {"D": "missing pax_growth"}
    assert len(r["ranking"]) == 3


def test_fewer_than_two_airports_is_an_error():
    r = score_airports({"A": K["A"]}, "expansion")
    assert "error" in r and "peer" in r["error"]


def test_unknown_objective_and_kpi_are_errors():
    assert "error" in score_airports(K, "roi")
    assert "error" in score_airports(K, "expansion", {"runways": 1})
    assert "error" in score_airports(K, "expansion", {"delay": 0})
