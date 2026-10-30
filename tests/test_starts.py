from rimagent.evaluate import parse_start, summarise_set
from rimagent.starts import name_colony

# The shape of the two parts of a real save (rimagent-landed.rws) that name_colony changes.
SAVE = """<?xml version="1.0" encoding="utf-8"?>
<savegame>
				<allFactions>
					<li>
						<def>OutlanderCivil</def>
						<name>Covenant of Eraler</name>
						<loadID>12</loadID>
					</li>
					<li>
						<leader>null</leader>
						<def>PlayerColony</def>
						<loadID>23</loadID>
						<randomKey>1740418076</randomKey>
					</li>
				</allFactions>
				<worldObjects>
					<li Class="Settlement">
						<def>Settlement</def>
						<faction>Faction_12</faction>
						<nameInt>Loothen</nameInt>
					</li>
					<li Class="Settlement">
						<def>Settlement</def>
						<ID>202</ID>
						<faction>Faction_23</faction>
						<trader>
							<stock IsNull="True" />
						</trader>
						<nameInt>Colony</nameInt>
					</li>
				</worldObjects>
</savegame>
"""


def test_the_colony_is_named_in_the_save(tmp_path):
    src, out = tmp_path / "a.rws", tmp_path / "b.rws"
    src.write_bytes(b"\xef\xbb\xbf" + SAVE.encode())
    name_colony(src, out, "Rimagent")
    text = out.read_bytes()
    assert text.startswith(b"\xef\xbb\xbf")
    text = text.decode("utf-8-sig")
    import re

    assert re.search(r"<def>PlayerColony</def>\s*<name>Rimagent</name>\s*<loadID>23</loadID>", text)
    assert re.search(r"<faction>Faction_23</faction>.*<nameInt>Rimagent</nameInt>\s*<namedByPlayer>True</namedByPlayer>", text, re.S)
    assert "<nameInt>Loothen</nameInt>" in text and text.count("<namedByPlayer>") == 1  # others untouched


def test_start_specs_parse():
    spec = parse_start("boreal7:BorealForest:Randy")
    assert (spec.seed, spec.biome, spec.storyteller, spec.difficulty) == ("boreal7", "BorealForest", "Randy", "Medium")
    assert spec.name == "start-boreal7-BorealForest"
    assert parse_start("x").biome == "TemperateForest"


def test_a_set_summary_has_mean_and_worst():
    def result(total, new):
        parts = {"survival": 1.0, "mood": 0.6, "food": 1.0, "production": 1.0, "shelter": 1.0, "progress": 0.5,
                 "busy": 1.0, "completion": 1.0}
        return {"new": new, "save": None, "endReason": "done", "score": {"total": total, "parts": parts, "daysPlayed": 14},
                "autonomy": {"escalations": 0}}
    text = summarise_set([result(90, "a:X"), result(80, "b:Y"), {"new": "c:Z", "error": "no site"}])
    assert "mean 85.0" in text and "worst 80.0" in text and "setup failed" in text and "weakest mood 0.60" in text
