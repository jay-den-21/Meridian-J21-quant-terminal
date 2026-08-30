from __future__ import annotations

import ast
from collections import Counter
from datetime import date
from pathlib import Path
import unittest

from fdp_cn.tushare.catalog import (
    CATALOG,
    get_endpoint_spec,
    standard_points_endpoint_specs,
)
from fdp_cn.tushare.service import IngestService


PRODUCT_ROOT = Path(__file__).resolve().parents[1]
GETTER_ROOTS = (
    PRODUCT_ROOT / "get_ph_data_from_ts",
    PRODUCT_ROOT / "get_rt_data_from_ts",
)
START = date(2026, 8, 1)
END = date(2026, 8, 2)
REPRESENTATIVE_CODE = "000001.SZ"


def _physical_getter_paths() -> frozenset[str]:
    return frozenset(
        path.relative_to(PRODUCT_ROOT).as_posix()
        for root in GETTER_ROOTS
        for path in root.rglob("Get_*.py")
        if path.is_file()
    )


def _static_text(node: ast.expr | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for part in node.values:
            if not isinstance(part, ast.Constant) or not isinstance(part.value, str):
                return None
            parts.append(part.value)
        return "".join(parts)
    return None


def _table_name_literals(class_node: ast.ClassDef) -> frozenset[str]:
    values: set[str] = set()
    for node in ast.walk(class_node):
        if isinstance(node, ast.Assign):
            targets = node.targets
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = (node.target,)
            value = node.value
        else:
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "table_name"
            or isinstance(target, ast.Attribute) and target.attr == "table_name"
            for target in targets
        ):
            continue
        literal = _static_text(value)
        if literal is not None:
            values.add(literal)
    return frozenset(values)


class CatalogPhysicalCoverageTests(unittest.TestCase):
    def test_every_physical_getter_is_catalogued(self) -> None:
        catalog_paths = Counter(spec.legacy_path for spec in CATALOG)
        physical_paths = _physical_getter_paths()

        self.assertEqual(len(CATALOG), 93)
        self.assertEqual(len(catalog_paths), 92)
        self.assertEqual(len(physical_paths), 92)
        self.assertEqual(set(catalog_paths), physical_paths)
        self.assertEqual(
            {path: count for path, count in catalog_paths.items() if count > 1},
            {"get_ph_data_from_ts/hk/Get_hk_basic.py": 2},
        )

    def test_every_legacy_id_names_a_symbol_in_its_declared_file(self) -> None:
        parsed_definitions: dict[str, dict[str, ast.AST]] = {}

        for spec in CATALOG:
            with self.subTest(endpoint=spec.key):
                module_name, separator, symbol_name = spec.legacy_id.rpartition(".")
                self.assertEqual(separator, ".")
                self.assertEqual(
                    module_name,
                    Path(spec.legacy_path)
                    .with_suffix("")
                    .as_posix()
                    .replace("/", "."),
                )

                if spec.legacy_path not in parsed_definitions:
                    source_path = PRODUCT_ROOT / spec.legacy_path
                    tree = ast.parse(
                        source_path.read_text(encoding="utf-8"),
                        filename=str(source_path),
                    )
                    parsed_definitions[spec.legacy_path] = {
                        node.name: node
                        for node in tree.body
                        if isinstance(
                            node,
                            (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
                        )
                    }

                definitions = parsed_definitions[spec.legacy_path]
                self.assertIn(symbol_name, definitions)
                definition = definitions[symbol_name]
                self.assertIsInstance(definition, ast.ClassDef)
                if not isinstance(definition, ast.ClassDef):
                    continue
                self.assertIn(
                    spec.target_table,
                    _table_name_literals(definition),
                )

        self.assertEqual(set(parsed_definitions), _physical_getter_paths())

    def test_all_10000_point_variants_are_individually_plannable(self) -> None:
        eligible = standard_points_endpoint_specs()
        eligible_keys = tuple(spec.key for spec in eligible)
        service = IngestService()
        all_plan = service.plan_all(
            date_from=START,
            date_to=END,
            codes=(REPRESENTATIVE_CODE,),
        )

        self.assertEqual(len(eligible), 71)
        self.assertEqual(tuple(item.key for item in all_plan.items), eligible_keys)
        for spec in eligible:
            with self.subTest(endpoint=spec.key):
                self.assertEqual(spec.access.kind, "standard_points")
                self.assertIsNotNone(spec.access.points_tier)
                self.assertLessEqual(spec.access.points_tier or 0, 10_000)
                codes = (
                    (REPRESENTATIVE_CODE,)
                    if spec.scope_kind in {"code_list", "code_date_range"}
                    else ()
                )
                endpoint_plan = service.plan_endpoint(
                    spec.key,
                    date_from=START,
                    date_to=END,
                    codes=codes,
                )
                self.assertEqual(endpoint_plan.mode, "endpoint")
                self.assertEqual(
                    tuple(item.key for item in endpoint_plan.items),
                    (spec.key,),
                )

    def test_unique_eligible_legacy_leaf_aliases_resolve(self) -> None:
        leaf_counts = Counter(
            spec.legacy_id.rpartition(".")[2] for spec in CATALOG
        )

        for spec in standard_points_endpoint_specs():
            leaf = spec.legacy_id.rpartition(".")[2]
            if leaf_counts[leaf] != 1:
                continue
            with self.subTest(endpoint=spec.key, alias=leaf):
                self.assertIn(leaf, spec.aliases)
                self.assertIs(get_endpoint_spec(leaf), spec)


if __name__ == "__main__":
    unittest.main()
