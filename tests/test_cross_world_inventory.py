from __future__ import annotations

import collections
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pal_breed_helper import save_parser


def _fstring(value: str) -> bytes:
    payload = value.encode("utf-8") + b"\x00"
    return len(payload).to_bytes(4, "little", signed=True) + payload


def _name_property(key: str, value: str) -> bytes:
    payload = _fstring(value)
    return (
        _fstring(key)
        + _fstring("NameProperty")
        + len(payload).to_bytes(8, "little")
        + b"\x00"
        + payload
    )


def _map_property(
    key: str, payload: bytes, *, declared_size: int | None = None
) -> bytes:
    size = len(payload) if declared_size is None else declared_size
    return (
        _fstring(key)
        + _fstring("MapProperty")
        + size.to_bytes(8, "little")
        + _fstring("StructProperty")
        + _fstring("StructProperty")
        + b"\x00"
        + payload
        + _fstring("None")
    )


def _array_property(
    key: str, payload: bytes, *, declared_size: int | None = None
) -> bytes:
    size = len(payload) if declared_size is None else declared_size
    return (
        _fstring(key)
        + _fstring("ArrayProperty")
        + size.to_bytes(8, "little")
        + _fstring("StructProperty")
        + b"\x00"
        + payload
        + _fstring("None")
    )


def _injected_value(html: str, variable: str) -> object:
    marker = f"window.{variable}="
    start = html.index(marker) + len(marker)
    value, _ = json.JSONDecoder().raw_decode(html[start:])
    return value


def _individual(identifier: str, code: str, source: str) -> dict:
    return {
        "id": identifier,
        "code": code,
        "source": source,
        "gender": "male",
        "level": 10,
        "rank": 0,
        "passives": [],
        "talents": {"hp": 50, "attack": 50, "defense": 50},
    }


class CharacterSaveParameterMapTests(unittest.TestCase):
    def test_declared_map_payload_excludes_character_id_after_property(self) -> None:
        payload = b"map-entry" + _name_property("CharacterID", "SheepBall")
        raw = (
            b"prefix"
            + _map_property("CharacterSaveParameterMap", payload)
            + _name_property("CharacterID", "PinkCat")
            + b"suffix"
        )

        extracted = save_parser._find_property_payload(
            raw, "CharacterSaveParameterMap", "MapProperty"
        )
        self.assertEqual(payload, extracted)
        self.assertEqual(
            collections.Counter({"SheepBall": 1}),
            save_parser.extract_species(extracted or b""),
        )
        self.assertEqual(
            ["SheepBall"],
            [
                item["code"]
                for item in save_parser.extract_individuals(extracted or b"")
            ],
        )

    def test_declared_map_payload_rejects_truncated_size(self) -> None:
        raw = _map_property(
            "CharacterSaveParameterMap",
            _name_property("CharacterID", "SheepBall"),
            declared_size=4096,
        )

        with self.assertRaisesRegex(RuntimeError, "CharacterSaveParameterMap"):
            save_parser._find_property_payload(
                raw, "CharacterSaveParameterMap", "MapProperty"
            )


class GlobalGenePayloadTests(unittest.TestCase):
    def test_array_payload_keeps_declared_slots_and_excludes_trailing_record(
        self,
    ) -> None:
        payload = (
            (3).to_bytes(4, "little", signed=True)
            + _name_property("CharacterID", "SheepBall")
            + _name_property("CharacterID", "None")
            + _name_property("CharacterID", "PinkCat")
        )
        raw = _array_property("SaveParameterArray", payload) + _name_property(
            "CharacterID", "ChickenPal"
        )

        extracted = save_parser._global_gene_payload(raw)

        self.assertEqual(payload, extracted)
        self.assertEqual(
            collections.Counter({"SheepBall": 1, "None": 1, "PinkCat": 1}),
            save_parser.extract_species(extracted),
        )

    def test_array_payload_rejects_slot_count_mismatch(self) -> None:
        payload = (2).to_bytes(4, "little", signed=True) + _name_property(
            "CharacterID", "SheepBall"
        )
        raw = _array_property("SaveParameterArray", payload)

        with self.assertRaisesRegex(RuntimeError, "声明 2，识别 1"):
            save_parser._global_gene_payload(raw)


class CrossWorldAnalysisTests(unittest.TestCase):
    def test_analyze_save_keeps_world_inventory_and_cross_world_genes_separate(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            level = Path(directory) / "Level.sav"
            storage = Path(directory) / "GlobalPalStorage.sav"
            level.touch()
            storage.touch()

            world_individual = _individual("world-1", "SheepBall", "world")
            gene_individual = _individual(
                "cross-world-1", "SheepBall", "crossWorldGenes"
            )

            def extract_species(raw: bytes) -> collections.Counter[str]:
                if raw == b"world":
                    return collections.Counter(
                        {
                            "SheepBall": 2,
                            "YakushimaMonster001": 1,
                            "WorldOnlyUnknownCode": 1,
                        }
                    )
                self.assertEqual(b"cross-world", raw)
                return collections.Counter(
                    {
                        "SheepBall": 3,
                        "PinkCat": 4,
                        "None": 5,
                        "BOSS_Male_Soldier04": 1,
                        "GeneOnlyUnknownCode": 2,
                    }
                )

            def extract_individuals(raw: bytes, source: str = "world") -> list[dict]:
                del source
                if raw == b"world":
                    return [world_individual]
                self.assertEqual(b"cross-world", raw)
                return [gene_individual]

            with (
                mock.patch.object(save_parser, "find_oodle_dll", return_value="oodle"),
                mock.patch.object(
                    save_parser,
                    "decompress_sav",
                    side_effect=[b"world", b"cross-world"],
                ),
                mock.patch.object(
                    save_parser, "extract_species", side_effect=extract_species
                ),
                mock.patch.object(
                    save_parser, "extract_individuals", side_effect=extract_individuals
                ),
                mock.patch.object(
                    save_parser, "_world_character_payload", side_effect=lambda raw: raw
                ),
                mock.patch.object(
                    save_parser, "_global_gene_payload", side_effect=lambda raw: raw
                ),
                mock.patch.object(
                    save_parser, "find_global_storage", return_value=str(storage)
                ),
                mock.patch.object(save_parser, "read_meta", return_value={}),
            ):
                result = save_parser.analyze_save(level, lambda _: None)

        self.assertEqual(["1"], result["ownedKeys"])
        self.assertEqual(["1", "2"], result["crossWorldGeneKeys"])

        owned = {item["key"]: item for item in result["owned"]}
        genes = {item["key"]: item for item in result["crossWorldGenes"]}
        self.assertEqual({"1"}, set(owned))
        self.assertEqual({"1", "2"}, set(genes))
        self.assertEqual(2, owned["1"]["count"])
        self.assertEqual(3, genes["1"]["count"])
        self.assertEqual(
            ["world-1"], [item["id"] for item in owned["1"]["individuals"]]
        )
        self.assertEqual(
            ["cross-world-1"],
            [item["id"] for item in genes["1"]["individuals"]],
        )
        self.assertEqual(
            ["YakushimaMonster001"],
            [item["code"] for item in result["excluded"]],
        )
        self.assertEqual(
            ["WorldOnlyUnknownCode"],
            [item["code"] for item in result["unknownData"]],
        )
        self.assertEqual(
            ["BOSS_Male_Soldier04"],
            [item["code"] for item in result["crossWorldGeneExcluded"]],
        )
        self.assertEqual(
            ["GeneOnlyUnknownCode"],
            [item["code"] for item in result["crossWorldGeneUnknownData"]],
        )

    def test_quick_count_does_not_include_global_cross_world_storage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            level = Path(directory) / "Level.sav"
            level.touch()
            with (
                mock.patch.object(save_parser, "find_oodle_dll", return_value="oodle"),
                mock.patch.object(
                    save_parser, "decompress_sav", return_value=b"world"
                ) as decompress,
                mock.patch.object(
                    save_parser,
                    "extract_species",
                    return_value=collections.Counter({"SheepBall": 2}),
                ),
                mock.patch.object(
                    save_parser, "_world_character_payload", side_effect=lambda raw: raw
                ),
                mock.patch.object(save_parser, "find_global_storage") as find_storage,
            ):
                count = save_parser.quick_count(level)

        self.assertEqual(2, count)
        self.assertEqual(1, decompress.call_count)
        find_storage.assert_not_called()


class CrossWorldHtmlTests(unittest.TestCase):
    def test_staged_html_injects_cross_world_genes_as_separate_array(self) -> None:
        owned = [
            {
                "key": "1",
                "count": 2,
                "world": 2,
                "box": 0,
                "individuals": [{"id": "world-1", "source": "world"}],
            }
        ]
        genes = [
            {
                "key": "1",
                "count": 3,
                "world": 0,
                "box": 3,
                "individuals": [
                    {"id": "cross-world-1", "source": "crossWorldGenes"}
                ],
            }
        ]
        result = {
            "source": "测试世界",
            "ownedKeys": ["1"],
            "owned": owned,
            "crossWorldGeneKeys": ["1"],
            "crossWorldGenes": genes,
            "crossWorldGeneExcluded": [],
            "crossWorldGeneUnknownData": [],
            "globalStorageStatus": "ok",
            "rawCounts": {},
        }

        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(
                os.environ, {"PAL_BREED_HELPER_DATA_DIR": directory}, clear=False
            ):
                staged = save_parser.stage_generated_bundle(result)
                try:
                    html = Path(staged["html"]).read_text(encoding="utf-8")
                    self.assertEqual(
                        owned, _injected_value(html, "__SAVE_INVENTORY__")
                    )
                    self.assertEqual(
                        genes, _injected_value(html, "__CROSS_WORLD_GENES__")
                    )
                finally:
                    save_parser.discard_generated_bundle(staged["stagingDir"])


if __name__ == "__main__":
    unittest.main()
