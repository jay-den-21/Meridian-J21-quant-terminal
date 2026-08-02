(function initializeInstrumentCatalogTools(root, factory) {
  const tools = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = tools;
  }
  if (root) {
    root.InstrumentCatalogTools = tools;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function createInstrumentCatalogTools() {
  "use strict";

  const STEP_LABELS = [
    "1 Asset Class / 资产类别",
    "2 Venue & Options / 市场与参数",
    "3 Review / 确认",
  ];
  const VIRTUAL_EXCHANGES = new Set(["INDX", "FOREX", "CC", "GBOND", "MONEY", "EUFUND"]);

  function normalizeMenu(rawMenu) {
    const menu = rawMenu && typeof rawMenu === "object" ? rawMenu : {};
    const exchanges = new Map();
    toArray(menu.exchanges).forEach((row) => {
      const code = String(row?.code || "").trim().toUpperCase();
      if (!code || VIRTUAL_EXCHANGES.has(code) || exchanges.has(code)) {
        return;
      }
      exchanges.set(code, {
        ...row,
        code,
        label: String(row?.label || row?.name || code),
        local_count: Number.parseInt(row?.local_count || 0, 10),
        sources: toArray(row?.sources),
      });
    });
    return {
      db: menu.db || null,
      categories: toArray(menu.categories).map((row) => ({
        ...row,
        id: String(row?.id || ""),
        type_options: toArray(row?.type_options),
      })),
      exchanges: Array.from(exchanges.values()).sort(compareExchanges),
      eodhd_cache: menu.eodhd_cache || { loaded: false, loaded_at: "", row_count: 0 },
      index_constituents: menu.index_constituents || { enabled: false, reason: "Not configured." },
    };
  }

  function createDraft(rawMenu, previousParams = {}) {
    const menu = normalizeMenu(rawMenu);
    const requestedAsset = String(previousParams.catalog_asset || "stock");
    const category = categoryById(menu, requestedAsset) || menu.categories[0] || null;
    const previousExchange = String(previousParams.exchange || "").trim().toUpperCase();
    const exchange = menu.exchanges.some((row) => row.code === previousExchange)
      ? previousExchange
      : menu.exchanges[0]?.code || "";
    const fundVenue = category?.id === "fund" && previousExchange === "EUFUND" ? "eufund" : "exchange";
    const defaultType = String(category?.default_type || "all");
    const requestedType = String(previousParams.type_filter || defaultType);
    const typeFilter = toArray(category?.type_options).includes(requestedType) ? requestedType : defaultType;
    return {
      assetId: category?.id || "stock",
      exchange,
      fundVenue,
      typeFilter,
      delisted: Boolean(previousParams.delisted),
    };
  }

  function categoryById(rawMenu, assetId) {
    const menu = normalizeMenu(rawMenu);
    return menu.categories.find((row) => row.id === assetId) || null;
  }

  function requestParams(rawMenu, draft) {
    const menu = normalizeMenu(rawMenu);
    const category = categoryById(menu, draft?.assetId);
    if (!category) {
      throw new Error("Choose an asset category.");
    }

    if (category.venue_mode === "fixed") {
      return {
        catalog_asset: category.id,
        exchange: String(category.fixed_exchange || ""),
        type_filter: "all",
        delisted: Boolean(draft.delisted),
      };
    }

    if (category.id === "fund" && draft.fundVenue === "eufund") {
      return {
        catalog_asset: "fund",
        exchange: "EUFUND",
        type_filter: "all",
        delisted: Boolean(draft.delisted),
      };
    }

    const exchange = String(draft?.exchange || "").trim().toUpperCase();
    if (!menu.exchanges.some((row) => row.code === exchange)) {
      throw new Error("Choose an exchange loaded from the local DB or EODHD directory.");
    }
    const allowedTypes = toArray(category.type_options);
    const typeFilter = String(draft?.typeFilter || category.default_type || "all");
    if (!allowedTypes.includes(typeFilter)) {
      throw new Error(`Unsupported ${category.label} type filter.`);
    }
    return {
      catalog_asset: category.id,
      exchange,
      type_filter: typeFilter,
      delisted: Boolean(draft.delisted),
    };
  }

  function needsExchange(rawMenu, draft) {
    const category = categoryById(rawMenu, draft?.assetId);
    if (!category || category.venue_mode === "fixed") {
      return false;
    }
    return category.id !== "fund" || draft.fundVenue !== "eufund";
  }

  function exchangeOptionLabel(row) {
    const sources = toArray(row?.sources)
      .map((source) => (source === "local_db" ? "DB" : source === "eodhd" ? "EODHD" : source))
      .join("+");
    const count = Number.parseInt(row?.local_count || 0, 10);
    const suffix = [sources, count ? `${count} local` : ""].filter(Boolean).join(" | ");
    return `${row.code} - ${row.label}${suffix ? ` (${suffix})` : ""}`;
  }

  function compareExchanges(left, right) {
    const leftLocal = toArray(left?.sources).includes("local_db");
    const rightLocal = toArray(right?.sources).includes("local_db");
    if (leftLocal !== rightLocal) {
      return leftLocal ? -1 : 1;
    }
    return left.code.localeCompare(right.code);
  }

  function toArray(value) {
    return Array.isArray(value) ? value : [];
  }

  return {
    STEP_LABELS,
    normalizeMenu,
    createDraft,
    categoryById,
    requestParams,
    needsExchange,
    exchangeOptionLabel,
  };
});
