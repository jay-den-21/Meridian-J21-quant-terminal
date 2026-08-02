"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

const {
  STEP_LABELS,
  normalizeMenu,
  createDraft,
  requestParams,
  needsExchange,
  exchangeOptionLabel,
} = require("../src/eodhd_codegen_app/static/instrument_catalog.js");

const MENU = {
  db: { available: true },
  categories: [
    {
      id: "stock",
      label: "Stocks",
      venue_mode: "select",
      default_type: "stock",
      type_options: ["stock", "common_stock"],
    },
    {
      id: "fund",
      label: "Funds",
      venue_mode: "fund",
      fixed_exchange: "EUFUND",
      default_type: "fund",
      type_options: ["fund"],
    },
    {
      id: "index",
      label: "Indices",
      venue_mode: "fixed",
      fixed_exchange: "INDX",
      default_type: "all",
      type_options: ["all"],
    },
  ],
  exchanges: [
    { code: "nasdaq", label: "Nasdaq", local_count: 3, sources: ["local_db"] },
    { code: "NASDAQ", label: "Duplicate", sources: ["eodhd"] },
    { code: "LSE", label: "London", sources: ["eodhd"] },
    { code: "INDX", label: "Indices", sources: ["local_db"] },
  ],
};

test("normalizes and deduplicates menu exchanges", () => {
  const menu = normalizeMenu(MENU);

  assert.deepEqual(
    menu.exchanges.map((row) => row.code),
    ["NASDAQ", "LSE"]
  );
  assert.equal(exchangeOptionLabel(menu.exchanges[0]), "NASDAQ - Nasdaq (DB | 3 local)");
});

test("creates a stock draft from the first validated exchange", () => {
  const draft = createDraft(MENU);

  assert.equal(draft.assetId, "stock");
  assert.equal(draft.exchange, "NASDAQ");
  assert.equal(needsExchange(MENU, draft), true);
  assert.deepEqual(requestParams(MENU, draft), {
    catalog_asset: "stock",
    exchange: "NASDAQ",
    type_filter: "stock",
    delisted: false,
  });
});

test("maps fixed index and EUFUND requests without a free-text exchange", () => {
  const indexDraft = createDraft(MENU, {
    catalog_asset: "index",
    exchange: "INDX",
  });
  const fundDraft = createDraft(MENU, {
    catalog_asset: "fund",
    exchange: "EUFUND",
  });

  assert.equal(needsExchange(MENU, indexDraft), false);
  assert.deepEqual(requestParams(MENU, indexDraft), {
    catalog_asset: "index",
    exchange: "INDX",
    type_filter: "all",
    delisted: false,
  });
  assert.deepEqual(requestParams(MENU, fundDraft), {
    catalog_asset: "fund",
    exchange: "EUFUND",
    type_filter: "all",
    delisted: false,
  });
});

test("rejects a selected venue that is not in the merged menu", () => {
  const draft = createDraft(MENU);
  draft.exchange = "MADEUP";

  assert.throws(() => requestParams(MENU, draft), /local DB or EODHD directory/);
});

test("exposes endpoint-specific wizard labels", () => {
  assert.deepEqual(STEP_LABELS, [
    "1 Asset Class / 资产类别",
    "2 Venue & Options / 市场与参数",
    "3 Review / 确认",
  ]);
});
