import json
from pathlib import Path

from rimsdk.mapview import MapView, Rect

FIXTURES = Path(__file__).parent / "fixtures" / "live"


def test_live_view_puts_colonists_at_their_positions():
    view = MapView.from_data(json.loads((FIXTURES / "map_view.json").read_text())["data"])
    pawns = json.loads((FIXTURES / "pawns.json").read_text())["data"]["pawns"]
    letters = {text.split(" (")[0]: symbol for symbol, text in view.legend.items() if "(" in text}
    for pawn in pawns:
        pos = pawn["position"]
        assert view[pos["x"], pos["z"]] == letters[pawn["name"]], pawn["name"]


def test_symbol_lookup_and_counting():
    view = MapView.from_data({"origin": {"x": 10, "z": 20}, "width": 3, "height": 2,
                              "rows": [":._", "..."], "legend": {":": "rich soil", ".": "soil", "_": "ground too poor"}})
    assert view[10, 21] == ":" and view[12, 21] == "_" and view[10, 20] == "."
    assert view.symbol_for("rich soil") == ":" and view.symbol_for("soil") == "."
    assert view.count(Rect(10, 20, 3, 2), ".") == 4


def test_rect_geometry():
    r = Rect.around(50, 50, 6, 6)
    assert (r.x, r.z, r.width, r.height) == (48, 48, 6, 6)
    assert Rect(-5, 95, 20, 20).clamp(100, 100) == Rect(0, 95, 15, 5)
    assert Rect(0, 0, 4, 4).overlaps(Rect(3, 3, 2, 2)) and not Rect(0, 0, 4, 4).overlaps(Rect(4, 0, 2, 2))
    assert Rect(1, 2, 3, 4).to_api() == {"x": 1, "z": 2, "width": 3, "height": 4}


def test_cells_off_the_view_never_match():
    view = MapView({(0, 0): "."}, {})
    assert view.count(Rect(0, 0, 2, 2), ".") == 1
    assert not view.is_((5, 5), ".t") and view.is_((0, 0), ".t")
