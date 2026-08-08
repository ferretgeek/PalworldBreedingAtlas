from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = PROJECT_ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from validate_data import validate_project  # noqa: E402
import json  # noqa: E402


class DataContractTests(unittest.TestCase):
    def test_current_game_data_contract(self) -> None:
        summary = validate_project(PROJECT_ROOT)
        self.assertEqual(287, summary["officialPals"])
        self.assertEqual(8, summary["maxBaseWorkSuitability"])
        self.assertEqual(10, summary["workSuitabilityCap"])

    def test_disputed_lamball_jellroy_recipe_matches_1_0_power_formula(self) -> None:
        data = json.loads(
            (PROJECT_ROOT / "src" / "pal_breed_helper" / "assets" / "data" / "game_data.json").read_text(encoding="utf-8")
        )
        pals = data["pals"]
        self.assertEqual(2820, (pals["1"]["breedingPower"] + pals["46"]["breedingPower"]) // 2)
        self.assertEqual(2820, pals["39"]["breedingPower"])
        self.assertEqual(2860, pals["44"]["breedingPower"])
        pair = {"1", "46"}
        self.assertTrue(any({row[0], row[1]} == pair for row in data["breed"]["39"]))
        self.assertFalse(any({row[0], row[1]} == pair for row in data["breed"]["44"]))

    def test_post_1_0_changed_and_special_recipe_sentinels(self) -> None:
        data = json.loads(
            (PROJECT_ROOT / "src" / "pal_breed_helper" / "assets" / "data" / "game_data.json").read_text(encoding="utf-8")
        )

        def matches(child: str, parent_a: str, parent_b: str) -> list:
            wanted = {parent_a, parent_b}
            return [row for row in data["breed"][child] if {row[0], row[1]} == wanted]

        self.assertTrue(matches("116", "18", "85"))  # Penking × Bushi = Sibelyx
        self.assertTrue(matches("121B", "121", "112"))  # Jormuntide × Blazehowl = Ignis
        self.assertEqual("MALE", matches("78B", "79", "78")[0][2]["parent1Gender"])
        self.assertEqual("FEMALE", matches("78B", "79", "78")[0][2]["parent2Gender"])
        self.assertEqual("FEMALE", matches("79B", "79", "78")[0][2]["parent1Gender"])
        self.assertEqual("MALE", matches("79B", "79", "78")[0][2]["parent2Gender"])


if __name__ == "__main__":
    unittest.main()
