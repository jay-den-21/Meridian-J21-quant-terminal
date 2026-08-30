from __future__ import annotations

from collections import Counter
from dataclasses import replace
import json
from pathlib import Path
import unittest

from fdp_cn.tushare.catalog import (
    CATALOG,
    catalog_summary,
    default_historical_endpoint_specs,
    get_endpoint_spec,
    is_standard_points_eligible,
    standard_points_endpoint_specs,
)
from fdp_cn.tushare.errors import TushareCatalogError
from fdp_cn.tushare.models import AccessSpec


PRODUCT_ROOT = Path(__file__).resolve().parents[1]
CATALOG_SEED = PRODUCT_ROOT / "src" / "fdp_cn" / "tushare" / "catalog_seed.json"


class PermissionCatalogTests(unittest.TestCase):
    def test_catalog_has_closed_93_variant_permission_partition(self):
        eligible = {spec.key for spec in standard_points_endpoint_specs()}
        separate = {
            spec.key for spec in CATALOG if spec.access.kind == "separate_purchase"
        }
        external = {
            spec.key for spec in CATALOG if spec.access.kind == "external_realtime"
        }
        disabled_standard = {
            spec.key
            for spec in CATALOG
            if spec.access.kind == "standard_points"
            and spec.capability.kind == "disabled_unsupported"
        }

        self.assertEqual(len(CATALOG), 93)
        self.assertEqual(
            Counter(spec.access.kind for spec in CATALOG),
            Counter(
                standard_points=73,
                separate_purchase=17,
                external_realtime=3,
            ),
        )
        self.assertEqual(
            Counter(spec.capability.kind for spec in CATALOG),
            Counter(
                executable=8,
                catalogued_not_implemented=80,
                disabled_realtime=3,
                disabled_unsupported=2,
            ),
        )
        self.assertEqual(
            (len(eligible), len(separate), len(external), len(disabled_standard)),
            (71, 17, 3, 2),
        )
        self.assertEqual(
            Counter(
                get_endpoint_spec(key).capability.kind for key in eligible
            ),
            Counter(executable=8, catalogued_not_implemented=63),
        )
        groups = (eligible, separate, external, disabled_standard)
        for index, group in enumerate(groups):
            for other in groups[index + 1 :]:
                self.assertTrue(group.isdisjoint(other))
        self.assertEqual(set().union(*groups), {spec.key for spec in CATALOG})

    def test_every_seed_entry_declares_a_valid_points_tier(self):
        seed = json.loads(CATALOG_SEED.read_text(encoding="utf-8"))

        self.assertEqual(seed["schema_version"], 2)
        self.assertEqual(len(seed["entries"]), 93)
        for entry in seed["entries"]:
            with self.subTest(endpoint=entry["key"]):
                access = entry["access"]
                self.assertIn("points_tier", access)
                if access["kind"] == "standard_points":
                    self.assertIs(type(access["points_tier"]), int)
                    self.assertEqual(access["points_tier"], 10_000)
                else:
                    self.assertIsNone(access["points_tier"])

    def test_access_spec_rejects_mixed_entitlement_semantics(self):
        with self.assertRaisesRegex(ValueError, "requires a positive integer"):
            AccessSpec("standard_points", "reviewed tier", None)
        with self.assertRaisesRegex(ValueError, "requires a positive integer"):
            AccessSpec("standard_points", "reviewed tier", True)
        with self.assertRaisesRegex(ValueError, "must not declare"):
            AccessSpec("separate_purchase", "separate entitlement", 10_000)

        higher_tier = AccessSpec("standard_points", "reviewed tier", 15_000)
        higher_tier_spec = replace(get_endpoint_spec("daily"), access=higher_tier)
        self.assertFalse(is_standard_points_eligible(higher_tier_spec))

    def test_default_selection_uses_points_not_provider_page_limit(self):
        default_keys = {spec.key for spec in standard_points_endpoint_specs()}

        for key in ("fund.fund_basic", "opt.opt_daily"):
            with self.subTest(endpoint=key):
                spec = get_endpoint_spec(key)
                self.assertEqual(spec.page_limit, 15_000)
                self.assertEqual(spec.access.points_tier, 10_000)
                self.assertEqual(catalog_summary(spec)["points_tier"], 10_000)
                self.assertIn(key, default_keys)

        paid_small_page = get_endpoint_spec("us.us_daily")
        self.assertLess(paid_small_page.page_limit or 0, 10_000)
        self.assertNotIn(paid_small_page.key, default_keys)

    def test_separately_entitled_cctv_and_us_daily_are_excluded(self):
        default_keys = {spec.key for spec in standard_points_endpoint_specs()}

        for key in (
            "alt.alt_cctv_news",
            "us.us_daily",
            "us.us_daily_adj",
        ):
            with self.subTest(endpoint=key):
                spec = get_endpoint_spec(key)
                self.assertEqual(spec.access.kind, "separate_purchase")
                self.assertIsNone(spec.access.points_tier)
                self.assertNotIn(key, default_keys)
                self.assertEqual(catalog_summary(spec)["points_tier"], None)

    def test_all_71_eligible_getter_leaf_aliases_resolve_to_their_specs(self):
        eligible = standard_points_endpoint_specs()

        self.assertEqual(len(eligible), 71)
        for spec in eligible:
            leaf = spec.legacy_id.rpartition(".")[2]
            with self.subTest(endpoint=spec.key, getter=leaf):
                self.assertIn(leaf, spec.aliases)
                self.assertIs(get_endpoint_spec(leaf), spec)

    def test_direct_job_default_is_the_executable_subset(self):
        direct = default_historical_endpoint_specs()
        eligible = standard_points_endpoint_specs()

        self.assertEqual(len(direct), 8)
        self.assertTrue(all(spec.executable for spec in direct))
        self.assertTrue(
            {spec.key for spec in direct}.issubset(
                {spec.key for spec in eligible}
            )
        )

    def test_colliding_realtime_getter_leaf_is_not_published(self):
        collision = "get_rt_stk_quote_tick"
        owners = (
            get_endpoint_spec("realtime.rt_stk_quote_tick_east"),
            get_endpoint_spec("realtime.rt_stk_quote_tick_sina"),
        )

        self.assertTrue(all(collision not in spec.aliases for spec in owners))
        with self.assertRaises(TushareCatalogError):
            get_endpoint_spec(collision)


if __name__ == "__main__":
    unittest.main()
