const state = {
  endpoints: [],
  universeMenu: { db: null, categories: [], preset_pools: [], exchanges: [], asset_types: [], unsupported: [] },
  currentEndpoint: "historical_eod",
  currentTab: "urls",
  draft: null,
  confirmedPayload: null,
  confirmedRequest: null,
  currentCost: null,
  rows: [],
  executionMeta: null,
  resultStale: false,
  poolLoadSeq: 0,
};

const MAX_SELECTED_SYMBOLS = 2000;
const STRONG_WARNING_SYMBOLS = 100;
const US_CLASS_SUFFIXES = new Set(["A", "B", "C", "K"]);
const US_LISTING_SUFFIXES = new Set([
  "AMEX",
  "ARCA",
  "BATS",
  "NASDAQ",
  "NYSE",
  "NYSEAMERICAN",
  "NYSEARCA",
  "NYSEMKT",
  "OTC",
  "OTCBB",
  "OTCGREY",
  "OTCMKTS",
  "OTCQB",
  "OTCQX",
  "PINK",
  "PINX",
]);

const FUNCTION_META = {
  historical_eod: {
    title: "Historical Price",
    cn: "历史行情",
    description: "Daily, weekly, or monthly OHLCV for selected stocks.",
    requiresSelection: true,
  },
  bulk_last_day_eod: {
    title: "Bulk Last-Day EOD",
    cn: "批量日终行情",
    description: "One-day EOD rows for an exchange or selected stocks.",
    requiresSelection: true,
  },
  live_ohlcv: {
    title: "Latest Snapshot",
    cn: "最新快照",
    description: "Latest delayed OHLCV snapshot for a small watchlist.",
    requiresSelection: true,
  },
  intraday: {
    title: "Intraday Bars",
    cn: "分钟线",
    description: "Delayed/finalized 1m, 5m, or 1h bars.",
    requiresSelection: true,
  },
  instrument_search: {
    title: "Instrument Lookup",
    cn: "证券搜索",
    description: "Search active securities by ticker, name, or identifier.",
    requiresSelection: false,
  },
};

const statusBox = document.getElementById("status");
const configModal = document.getElementById("config_modal");
const requestModal = document.getElementById("request_modal");

function endpointSpec(endpointId = state.draft?.endpoint || state.currentEndpoint) {
  return state.endpoints.find((item) => item.id === endpointId);
}

function valueOf(id) {
  return document.getElementById(id).value;
}

function numberValue(id) {
  return Number.parseInt(valueOf(id), 10);
}

function paramId(name) {
  return `draft_param_${name}`;
}

async function postJson(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || `Request failed with ${response.status}`);
  }
  return data;
}

async function deleteJson(path) {
  const response = await fetch(path, { method: "DELETE" });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || `Request failed with ${response.status}`);
  }
  return data;
}

async function loadEndpoints() {
  const response = await fetch("/api/endpoints");
  const data = await response.json();
  state.endpoints = data.endpoints || [];
}

async function loadUniverseMenu() {
  const response = await fetch("/api/universe/menu");
  state.universeMenu = await response.json();
}

async function loadConfigStatus() {
  const response = await fetch("/api/config");
  const data = await response.json();
  renderTokenStatus(data.token);
}

function createDraft(endpointId) {
  const spec = endpointSpec(endpointId);
  const previous = state.confirmedRequest?.endpoint === endpointId ? state.confirmedRequest : null;
  const params = {};
  (spec.params || []).forEach((param) => {
    params[param.name] = previous?.params?.[param.name] ?? defaultParamValue(param);
  });

  const selectedSymbols = new Map();
  toArray(params.symbols).forEach((symbol) => {
    const providerSymbol = providerSymbolFromToken(symbol, draftExchangeFromParams(params));
    if (providerSymbol) {
      selectedSymbols.set(providerSymbol, manualRow(providerSymbol, "confirmed"));
    }
  });

  return {
    endpoint: endpointId,
    step: 1,
    params,
    fmt: previous?.fmt || spec.default_format || "json",
    previewLimit: previous?.preview_limit || 50,
    pool: {
      category: "preset",
      source: "preset",
      preset: firstPresetId(),
      exchange: "",
      assetType: "stock",
      resourceLabel: "US major venues common stocks",
      history: [],
      historyIndex: -1,
      advanced: {
        activeOnly: true,
        excludeOtc: true,
        textSearch: "",
        assetType: "",
        exchange: "",
        usePreset: true,
        preset: firstPresetId(),
      },
      statusMessage: "",
    },
    candidateRows: [],
    candidatesLoaded: false,
    selectedSymbols,
    focusedSymbol: "",
    importText: "",
    importSummary: "",
    review: null,
  };
}

function defaultParamValue(param) {
  if (param.kind === "checkbox") {
    return Boolean(param.default);
  }
  if (param.kind === "number") {
    return param.default === "" ? "" : Number.parseInt(param.default, 10);
  }
  return param.name === "symbols" ? "" : param.default || "";
}

function draftExchangeFromParams(params) {
  const exchange = params.exchange;
  return typeof exchange === "string" && exchange.trim() ? exchange.trim().toUpperCase() : "US";
}

function firstPresetId() {
  return (state.universeMenu.preset_pools || [])[0]?.id || "us_major_common";
}

function functionMeta(endpointId) {
  return FUNCTION_META[endpointId] || {
    title: endpointSpec(endpointId)?.label || endpointId,
    cn: "取数",
    description: endpointSpec(endpointId)?.description || "",
    requiresSelection: hasSymbolParam(endpointSpec(endpointId)),
  };
}

function hasSymbolParam(spec) {
  return Boolean((spec?.params || []).some((param) => param.name === "symbols"));
}

function selectedProviderSymbols(draft = state.draft) {
  return Array.from(draft?.selectedSymbols?.keys() || []).sort();
}

function selectedRows(draft = state.draft) {
  return Array.from(draft?.selectedSymbols?.values() || []).sort((left, right) =>
    left.provider_symbol.localeCompare(right.provider_symbol)
  );
}

function selectedBulkSymbols(draft = state.draft) {
  return selectedProviderSymbols(draft).map((symbol) => {
    if (draftRequestExchange(draft) === "US" && symbol.endsWith(".US")) {
      return symbol.slice(0, -3);
    }
    return symbol;
  });
}

function draftRequestExchange(draft = state.draft) {
  const exchange = draft?.pool?.exchange || draft?.pool?.advanced?.exchange || "US";
  return String(exchange || "US").trim().toUpperCase();
}

function syncDraftExchangeFromPool() {
  if (state.draft?.params) {
    state.draft.params.exchange = draftRequestExchange();
  }
}

function buildPayloadFromDraft(draft = state.draft) {
  const spec = endpointSpec(draft.endpoint);
  const params = { ...draft.params };
  const usesSymbols = hasSymbolParam(spec);

  if (usesSymbols) {
    params.exchange = draftRequestExchange(draft);
    params.symbols =
      draft.endpoint === "bulk_last_day_eod"
        ? selectedBulkSymbols(draft).join(",")
        : selectedProviderSymbols(draft).join(",");
  }

  return {
    asset: "equity",
    endpoint: draft.endpoint,
    fmt: draft.fmt,
    preview_limit: draft.previewLimit,
    params,
  };
}

function openRequestWizard(endpointId = state.currentEndpoint) {
  if (!endpointSpec(endpointId)) {
    setStatus(`Endpoint ${endpointId} is not available`, true);
    return;
  }
  setActiveFunctionCard(endpointId);
  state.draft = createDraft(endpointId);
  requestModal.classList.remove("hidden");
  renderWizard();
}

function closeRequestWizard() {
  requestModal.classList.add("hidden");
  setActiveFunctionCard(state.currentEndpoint);
}

function renderWizard() {
  const spec = endpointSpec();
  const meta = functionMeta(state.draft.endpoint);
  document.getElementById("wizard_title").textContent = `${meta.title} / ${meta.cn}`;
  document.querySelectorAll(".step-pill").forEach((button) => {
    const active = Number.parseInt(button.dataset.step, 10) === state.draft.step;
    button.classList.toggle("active", active);
  });
  document.querySelectorAll("[data-step-panel]").forEach((panel) => {
    panel.classList.toggle("hidden", Number.parseInt(panel.dataset.stepPanel, 10) !== state.draft.step);
  });
  document.getElementById("wizard_back").disabled = state.draft.step === 1;
  document.getElementById("wizard_next").classList.toggle("hidden", state.draft.step === 3);
  document.getElementById("wizard_confirm").classList.toggle("hidden", state.draft.step !== 3);

  if (state.draft.step === 1) {
    renderSelectionStep();
  } else if (state.draft.step === 2) {
    renderParameterStep(spec);
  } else {
    renderReviewStep();
  }
}

function renderSelectionStep() {
  const container = document.getElementById("selection_step");
  const spec = endpointSpec();
  const meta = functionMeta(state.draft.endpoint);

  if (!hasSymbolParam(spec)) {
    container.innerHTML = "";
    const note = document.createElement("div");
    note.className = "notice";
    note.innerHTML =
      "<strong>No ticker basket required.</strong><span>Fill the lookup fields in the Parameters step.</span>";
    container.appendChild(note);
    return;
  }

  container.innerHTML = `
    <div class="wizard-intro">
      <strong>${escapeHtml(meta.title)} / ${escapeHtml(meta.cn)}</strong>
      <span>${escapeHtml(meta.description)} Pool lists read the local database only; EODHD token is used only for Execute API and API lookup.</span>
    </div>
    <div class="pool-source-note" id="pool_source_note"></div>
    <div class="pool-browser">
      <aside class="pool-sidebar">
        <div class="pool-nav-history">
          <button type="button" id="pool_back_btn" class="mini-button" title="Back">&lt;</button>
          <button type="button" id="pool_forward_btn" class="mini-button" title="Forward">&gt;</button>
        </div>
        <div id="pool_category_list" class="pool-category-list"></div>
        <button type="button" id="advanced_filter_open" class="secondary-button">Advanced Filter</button>
        <button type="button" id="clear_selected" class="secondary-button">Clear selected</button>
      </aside>
      <section class="pool-resource-pane">
        <div class="subhead">Pool Resources</div>
        <div id="pool_resource_help" class="help"></div>
        <div id="pool_resource_list" class="pool-resource-list"></div>
      </section>
      <section class="pool-candidate-pane">
        <div class="selection-head compact-head">
          <div>
            <strong id="candidate_title">Candidates</strong>
            <span id="candidate_meta"></span>
          </div>
          <input id="candidate_filter" placeholder="Filter: AAPL, Apple, NASDAQ">
        </div>
        <div id="candidate_list" class="asset-list"></div>
      </section>
      <section class="pool-selected-pane">
        <div class="selection-head compact-head">
          <div>
            <strong id="selected_count">${state.draft.selectedSymbols.size} selected</strong>
            <span>Most endpoints spend one API call per ticker.</span>
          </div>
        </div>
        <div id="selected_list" class="asset-list selected-list"></div>
      </section>
    </div>
    <div class="import-panel">
      <div class="field">
        <label for="import_text">Import pasted tickers</label>
        <textarea id="import_text" rows="3" placeholder="AAPL, NVDA, MSFT, BRK.B"></textarea>
      </div>
      <div class="grid two">
        <div class="field">
          <label for="import_file">Import CSV/TXT file</label>
          <input id="import_file" type="file" accept=".csv,.txt,text/csv,text/plain">
        </div>
        <div class="field import-action">
          <label>&nbsp;</label>
          <button type="button" id="import_tickers" class="secondary-button">Import tickers</button>
        </div>
      </div>
      <div class="match-summary" id="import_summary"></div>
    </div>
    <div class="submodal hidden" id="advanced_filter_modal">
      <div class="submodal-panel child-window">
        <div class="child-titlebar">
          <span>Advanced Filter / 高级筛选</span>
          <button type="button" id="advanced_filter_close" class="icon-button">Close</button>
        </div>
        <label class="check">
          <input id="adv_active_only" type="checkbox">
          Active instruments only
        </label>
        <label class="check">
          <input id="adv_exclude_otc" type="checkbox">
          Exclude OTC/PINK venues
        </label>
        <label class="check">
          <input id="adv_use_preset" type="checkbox">
          Use preset pool
        </label>
        <div class="field">
          <label for="adv_preset">Preset pools</label>
          <select id="adv_preset"></select>
        </div>
        <div class="grid two">
          <div class="field">
            <label for="adv_asset_type">Asset type</label>
            <select id="adv_asset_type"></select>
          </div>
          <div class="field">
            <label for="adv_exchange">Exchange</label>
            <select id="adv_exchange"></select>
          </div>
        </div>
        <div class="field">
          <label for="adv_text_search">Text search</label>
          <input id="adv_text_search" placeholder="AAPL, Apple, SPDR">
        </div>
        <div class="actions compact">
          <button type="button" id="advanced_filter_apply">Apply filters</button>
          <button type="button" id="advanced_filter_cancel" class="secondary-button">Cancel</button>
        </div>
        <div class="help">Filters are applied to the local database only. This panel does not call EODHD Screener.</div>
      </div>
    </div>
  `;

  bindSelectionControls();
  ensurePoolHistory();
  renderPoolBrowser();
  renderCandidateTable();
  renderSelectedTable();
  renderImportSummary();
  if (!state.draft.candidatesLoaded && state.universeMenu.db?.available) {
    loadCandidates({ silent: true }).catch((error) => setStatus(error.message, true));
  }
}

function bindSelectionControls() {
  document.getElementById("clear_selected").addEventListener("click", clearSelectedSymbols);
  document.getElementById("candidate_filter").addEventListener("input", renderCandidateTable);
  document.getElementById("pool_back_btn").addEventListener("click", movePoolHistoryBack);
  document.getElementById("pool_forward_btn").addEventListener("click", movePoolHistoryForward);
  document.getElementById("advanced_filter_open").addEventListener("click", openAdvancedFilter);
  document.getElementById("advanced_filter_close").addEventListener("click", closeAdvancedFilter);
  document.getElementById("advanced_filter_cancel").addEventListener("click", closeAdvancedFilter);
  document.getElementById("advanced_filter_apply").addEventListener("click", applyAdvancedFilter);
  document.getElementById("import_text").value = state.draft.importText;
  document.getElementById("import_text").addEventListener("input", (event) => {
    state.draft.importText = event.target.value;
  });
  document.getElementById("import_tickers").addEventListener("click", importTickers);
  bindAdvancedFilterControls();
}

function renderPoolBrowser() {
  renderPoolStatus();
  renderPoolCategories();
  renderPoolResources();
  renderPoolHistoryButtons();
}

function renderPoolStatus() {
  const note = document.getElementById("pool_source_note");
  if (!note) {
    return;
  }
  const db = state.universeMenu.db || {};
  const current = state.draft.pool.resourceLabel || "No pool selected";
  note.textContent = db.available
    ? `Source: read-only MySQL instrument pool. Current pool: ${current}. No EODHD API call is used for candidate loading.`
    : `Pool source unavailable: ${db.message || "database is not configured"}`;
}

function renderPoolCategories() {
  const list = document.getElementById("pool_category_list");
  list.innerHTML = "";
  (state.universeMenu.categories || []).forEach((category) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "pool-category";
    button.disabled = !category.enabled;
    button.classList.toggle("active", state.draft.pool.category === category.id);
    button.innerHTML = `<strong>${escapeHtml(category.label)}</strong><span>${escapeHtml(category.cn || category.source || "")}</span>`;
    button.title = category.enabled ? category.source || "" : category.disabled_reason || "Unavailable";
    button.addEventListener("click", () => selectPoolCategory(category.id));
    list.appendChild(button);
  });
}

function renderPoolResources() {
  const help = document.getElementById("pool_resource_help");
  const list = document.getElementById("pool_resource_list");
  const category = state.draft.pool.category;
  list.innerHTML = "";

  if (!state.universeMenu.db?.available) {
    help.textContent = state.universeMenu.db?.message || "Database pool source unavailable.";
    return;
  }

  if (category === "preset") {
    help.textContent = "Preset pools are backed by the existing us_share.instrument table.";
    (state.universeMenu.preset_pools || []).forEach((preset) => {
      list.appendChild(resourceButton(preset.id, preset.label, preset.description || "", () => selectPresetPool(preset.id)));
    });
    return;
  }

  if (category === "exchange") {
    help.textContent = "Click an exchange to show active instruments in that exchange. This is not an API request.";
    (state.universeMenu.exchanges || []).forEach((exchange) => {
      list.appendChild(
        resourceButton(exchange.code, exchange.code, `${exchange.count || 0} active instruments`, () =>
          selectExchangePool(exchange.code)
        )
      );
    });
    return;
  }

  if (category === "asset_type") {
    help.textContent = "Click an asset type to show active instruments of that type.";
    (state.universeMenu.asset_types || []).forEach((assetType) => {
      list.appendChild(
        resourceButton(assetType.id, assetType.label, `${assetType.count || 0} active instruments`, () =>
          selectAssetTypePool(assetType.id)
        )
      );
    });
    return;
  }

  if (category === "index_assets") {
    help.textContent = "Index Assets are index instruments only. They are not index constituent stock lists.";
    list.appendChild(resourceButton("index_assets", "All index assets", "Display index instruments stored in DB", selectIndexAssetsPool));
    return;
  }

  help.textContent = "Sector/industry pools are disabled until a taxonomy or membership source is added.";
}

function resourceButton(id, label, description, onClick) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "resource-item";
  button.classList.toggle("active", activeResourceId() === id);
  button.innerHTML = `<strong>${escapeHtml(label)}</strong><span>${escapeHtml(description)}</span>`;
  button.addEventListener("click", onClick);
  return button;
}

function selectPoolCategory(category) {
  state.draft.pool.category = category;
  renderPoolBrowser();
  if (category === "index_assets") {
    selectIndexAssetsPool();
  }
}

function selectPresetPool(presetId) {
  const preset = (state.universeMenu.preset_pools || []).find((item) => item.id === presetId);
  state.draft.pool.category = "preset";
  state.draft.pool.source = "preset";
  state.draft.pool.preset = presetId;
  state.draft.pool.resourceLabel = preset?.label || presetId;
  state.draft.pool.exchange = "";
  state.draft.pool.assetType = "stock";
  state.draft.pool.advanced.preset = presetId;
  state.draft.pool.advanced.usePreset = true;
  state.draft.pool.advanced.excludeOtc = Boolean(preset?.exclude_otc);
  state.draft.pool.advanced.assetType = "";
  state.draft.pool.advanced.exchange = "";
  syncDraftExchangeFromPool();
  pushPoolHistory();
  renderPoolBrowser();
  loadCandidates().catch((error) => setStatus(error.message, true));
}

function selectExchangePool(exchange) {
  state.draft.pool.category = "exchange";
  state.draft.pool.source = "exchange";
  state.draft.pool.exchange = exchange;
  state.draft.pool.assetType = state.draft.pool.advanced.assetType || "stock";
  state.draft.pool.resourceLabel = `${exchange} ${state.draft.pool.assetType}`;
  state.draft.pool.advanced.usePreset = false;
  state.draft.pool.advanced.exchange = exchange;
  state.draft.pool.advanced.assetType = state.draft.pool.assetType;
  syncDraftExchangeFromPool();
  pushPoolHistory();
  renderPoolBrowser();
  loadCandidates().catch((error) => setStatus(error.message, true));
}

function selectAssetTypePool(assetType) {
  state.draft.pool.category = "asset_type";
  state.draft.pool.source = "asset_type";
  state.draft.pool.assetType = assetType;
  state.draft.pool.exchange = "";
  state.draft.pool.resourceLabel = `${assetType} instruments`;
  state.draft.pool.advanced.usePreset = false;
  state.draft.pool.advanced.exchange = "";
  state.draft.pool.advanced.assetType = assetType;
  syncDraftExchangeFromPool();
  pushPoolHistory();
  renderPoolBrowser();
  loadCandidates().catch((error) => setStatus(error.message, true));
}

function selectIndexAssetsPool() {
  state.draft.pool.category = "index_assets";
  state.draft.pool.source = "index_assets";
  state.draft.pool.exchange = "";
  state.draft.pool.assetType = "index";
  state.draft.pool.resourceLabel = "Index assets";
  state.draft.pool.advanced.usePreset = false;
  state.draft.pool.advanced.exchange = "";
  state.draft.pool.advanced.assetType = "";
  syncDraftExchangeFromPool();
  pushPoolHistory();
  renderPoolBrowser();
  loadCandidates().catch((error) => setStatus(error.message, true));
}

function activeResourceId() {
  if (state.draft.pool.source === "preset") {
    return state.draft.pool.preset;
  }
  if (state.draft.pool.source === "exchange") {
    return state.draft.pool.exchange;
  }
  if (state.draft.pool.source === "asset_type") {
    return state.draft.pool.assetType;
  }
  return state.draft.pool.source;
}

function ensurePoolHistory() {
  if (state.draft.pool.history.length) {
    return;
  }
  state.draft.pool.history = [poolHistorySnapshot()];
  state.draft.pool.historyIndex = 0;
}

function pushPoolHistory() {
  const snapshot = poolHistorySnapshot();
  const current = state.draft.pool.history[state.draft.pool.historyIndex];
  if (current && JSON.stringify(current) === JSON.stringify(snapshot)) {
    return;
  }
  state.draft.pool.history = state.draft.pool.history.slice(0, state.draft.pool.historyIndex + 1);
  state.draft.pool.history.push(snapshot);
  state.draft.pool.historyIndex = state.draft.pool.history.length - 1;
}

function poolHistorySnapshot() {
  return {
    category: state.draft.pool.category,
    source: state.draft.pool.source,
    preset: state.draft.pool.preset,
    exchange: state.draft.pool.exchange,
    assetType: state.draft.pool.assetType,
    resourceLabel: state.draft.pool.resourceLabel,
    advanced: structuredCloneSafe(state.draft.pool.advanced),
  };
}

function restorePoolHistory(snapshot) {
  Object.assign(state.draft.pool, snapshot);
  syncDraftExchangeFromPool();
  renderPoolBrowser();
  loadCandidates({ silent: true }).catch((error) => setStatus(error.message, true));
}

function movePoolHistoryBack() {
  if (state.draft.pool.historyIndex <= 0) {
    return;
  }
  state.draft.pool.historyIndex -= 1;
  restorePoolHistory(state.draft.pool.history[state.draft.pool.historyIndex]);
}

function movePoolHistoryForward() {
  if (state.draft.pool.historyIndex >= state.draft.pool.history.length - 1) {
    return;
  }
  state.draft.pool.historyIndex += 1;
  restorePoolHistory(state.draft.pool.history[state.draft.pool.historyIndex]);
}

function renderPoolHistoryButtons() {
  const back = document.getElementById("pool_back_btn");
  const forward = document.getElementById("pool_forward_btn");
  if (!back || !forward) {
    return;
  }
  back.disabled = state.draft.pool.historyIndex <= 0;
  forward.disabled = state.draft.pool.historyIndex >= state.draft.pool.history.length - 1;
}

function bindAdvancedFilterControls() {
  fillSelect("adv_preset", state.universeMenu.preset_pools || [], "id", "label", false);
  fillSelect("adv_asset_type", state.universeMenu.asset_types || [], "id", "label", true);
  fillSelect("adv_exchange", state.universeMenu.exchanges || [], "code", "label", true);
}

function fillSelect(id, rows, valueKey, labelKey, includeBlank) {
  const select = document.getElementById(id);
  select.innerHTML = "";
  if (includeBlank) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No override";
    select.appendChild(option);
  }
  rows.forEach((row) => {
    const option = document.createElement("option");
    option.value = row[valueKey];
    option.textContent = row.count ? `${row[labelKey]} (${row.count})` : row[labelKey];
    select.appendChild(option);
  });
}

function openAdvancedFilter() {
  const advanced = state.draft.pool.advanced;
  document.getElementById("adv_active_only").checked = advanced.activeOnly;
  document.getElementById("adv_exclude_otc").checked = advanced.excludeOtc;
  document.getElementById("adv_use_preset").checked = advanced.usePreset;
  document.getElementById("adv_preset").value = advanced.preset || firstPresetId();
  document.getElementById("adv_asset_type").value = advanced.assetType || "";
  document.getElementById("adv_exchange").value = advanced.exchange || "";
  document.getElementById("adv_text_search").value = advanced.textSearch || "";
  document.getElementById("advanced_filter_modal").classList.remove("hidden");
}

function closeAdvancedFilter() {
  document.getElementById("advanced_filter_modal").classList.add("hidden");
}

function applyAdvancedFilter() {
  const advanced = state.draft.pool.advanced;
  advanced.activeOnly = document.getElementById("adv_active_only").checked;
  advanced.excludeOtc = document.getElementById("adv_exclude_otc").checked;
  advanced.usePreset = document.getElementById("adv_use_preset").checked;
  advanced.preset = document.getElementById("adv_preset").value || firstPresetId();
  advanced.assetType = document.getElementById("adv_asset_type").value;
  advanced.exchange = document.getElementById("adv_exchange").value;
  advanced.textSearch = document.getElementById("adv_text_search").value.trim();
  if (advanced.usePreset) {
    state.draft.pool.category = "preset";
    state.draft.pool.source = "preset";
    state.draft.pool.preset = advanced.preset;
    state.draft.pool.exchange = "";
    state.draft.pool.assetType = advanced.assetType || "stock";
    state.draft.pool.resourceLabel = presetLabel(advanced.preset);
  } else if (advanced.exchange) {
    state.draft.pool.category = "exchange";
    state.draft.pool.source = "exchange";
    state.draft.pool.exchange = advanced.exchange;
    state.draft.pool.assetType = advanced.assetType || "stock";
    state.draft.pool.resourceLabel = `${advanced.exchange} ${state.draft.pool.assetType}`;
  } else {
    state.draft.pool.category = "asset_type";
    state.draft.pool.source = "asset_type";
    state.draft.pool.exchange = "";
    state.draft.pool.assetType = advanced.assetType || "stock";
    state.draft.pool.resourceLabel = `${state.draft.pool.assetType} instruments`;
  }
  syncDraftExchangeFromPool();
  pushPoolHistory();
  closeAdvancedFilter();
  renderPoolBrowser();
  loadCandidates().catch((error) => setStatus(error.message, true));
}

function presetLabel(presetId) {
  return (state.universeMenu.preset_pools || []).find((item) => item.id === presetId)?.label || presetId;
}

async function loadCandidates(options = {}) {
  const loadSeq = ++state.poolLoadSeq;
  const payload = buildPoolLoadPayload();
  if (!options.silent) {
    setStatus("Loading database candidates");
  }
  try {
    const data = await postJson("/api/universe/load", payload);
    if (loadSeq !== state.poolLoadSeq) {
      return;
    }
    if (data.unavailable) {
      state.draft.pool.statusMessage = data.db?.message || "Database pool source unavailable.";
      state.draft.candidateRows = selectedRows();
      renderPoolBrowser();
      renderCandidateTable();
      renderSelectedTable();
      renderImportSummary();
      setStatus(state.draft.pool.statusMessage, true);
      return;
    }
    state.draft.candidateRows = dedupeRows([...(data.rows || []), ...selectedRows()]);
    state.draft.candidatesLoaded = true;
    state.draft.pool.statusMessage = `Loaded ${state.draft.candidateRows.length} candidates from ${data.label || state.draft.pool.resourceLabel}.`;
    renderCandidateTable();
    renderSelectedTable();
    renderImportSummary();
    setStatus(state.draft.pool.statusMessage);
  } catch (error) {
    if (loadSeq !== state.poolLoadSeq) {
      return;
    }
    setStatus(error.message, true);
  }
}

function buildPoolLoadPayload() {
  const pool = state.draft.pool;
  return {
    source: pool.source,
    preset: pool.preset,
    exchange: pool.exchange,
    asset_type: pool.assetType,
    filters: {
      active_only: pool.advanced.activeOnly,
      exclude_otc: pool.advanced.excludeOtc,
      text_search: pool.advanced.textSearch,
      asset_type: pool.advanced.assetType,
      exchange: pool.advanced.exchange,
    },
  };
}

async function importTickers() {
  setStatus("Importing tickers");
  try {
    const textParts = [state.draft.importText || ""];
    const file = document.getElementById("import_file").files[0];
    if (file) {
      textParts.push(await file.text());
    }
    const report = await addImportedSymbols(textParts.join("\n"));
    state.draft.importSummary = formatImportSummary(report);
    renderCandidateTable();
    renderSelectedTable();
    renderImportSummary();
    setStatus("Imported tickers");
  } catch (error) {
    setStatus(error.message, true);
  }
}

async function addImportedSymbols(text) {
  const tokens = extractSymbolTokens(text);
  const report = { valid: 0, duplicates: 0, invalid: [], normalized: [] };
  if (!tokens.length) {
    return report;
  }

  const data = await postJson("/api/universe/resolve", { tokens });
  if (data.unavailable) {
    report.invalid.push(data.db?.message || "database unavailable");
    return report;
  }

  [...(data.invalid || []), ...(data.unmatched || [])].forEach((token) => {
    report.invalid.push(String(token).toUpperCase());
  });

  (data.resolved || []).forEach((item) => {
    const token = String(item.input || "").toUpperCase();
    const row = normalizeResolvedRow(item.row);
    const providerSymbol = row.provider_symbol;
    if (!providerSymbol) {
      report.invalid.push(token);
      return;
    }
    if (state.draft.selectedSymbols.has(providerSymbol)) {
      report.duplicates += 1;
    } else if (state.draft.selectedSymbols.size >= MAX_SELECTED_SYMBOLS) {
      report.invalid.push(`${token} (selection cap reached)`);
      return;
    } else {
      report.valid += 1;
      if (token !== providerSymbol && token !== row.symbol) {
        report.normalized.push(`${token} -> ${providerSymbol}`);
      }
    }
    state.draft.selectedSymbols.set(providerSymbol, row);
    addCandidateRow(row);
  });

  return report;
}

function normalizeResolvedRow(row) {
  const providerSymbol = String(row?.provider_symbol || "").toUpperCase();
  const symbol = String(row?.symbol || providerSymbol.split(".", 1)[0]).toUpperCase();
  const exchange = String(row?.exchange || (providerSymbol.includes(".") ? providerSymbol.split(".").pop() : draftRequestExchange())).toUpperCase();
  return {
    provider_symbol: providerSymbol,
    symbol,
    name: row?.name || "Database instrument",
    exchange,
    type: String(row?.type || "instrument").toLowerCase(),
    source: "db_import",
  };
}

function extractSymbolTokens(text) {
  const cleaned = (text || "").trim();
  if (!cleaned) {
    return [];
  }
  const lines = cleaned.split(/\r?\n/).filter((line) => line.trim());
  const headerTokens = lines.length ? parseCsvLine(lines[0]).map((part) => part.trim().toLowerCase()) : [];
  const symbolColumn = headerTokens.findIndex((part) =>
    ["provider_symbol", "symbol", "ticker", "code"].includes(part)
  );
  if (symbolColumn >= 0 && lines.length > 1) {
    return lines
      .slice(1)
      .map((line) => parseCsvLine(line)[symbolColumn] || "")
      .map((part) => part.trim())
      .filter(Boolean);
  }
  return cleaned
    .split(/[,\n\r\t ]+/)
    .map((part) => part.trim())
    .filter(Boolean);
}

function parseCsvLine(line) {
  const values = [];
  let current = "";
  let quoted = false;
  for (let index = 0; index < line.length; index += 1) {
    const char = line[index];
    if (char === '"' && quoted && line[index + 1] === '"') {
      current += '"';
      index += 1;
    } else if (char === '"') {
      quoted = !quoted;
    } else if ((char === "," || char === "\t") && !quoted) {
      values.push(current);
      current = "";
    } else {
      current += char;
    }
  }
  values.push(current);
  return values;
}

function formatImportSummary(report) {
  const parts = [`${report.valid} valid selected`];
  if (report.duplicates) {
    parts.push(`${report.duplicates} duplicate`);
  }
  if (report.normalized.length) {
    parts.push(`normalized: ${report.normalized.slice(0, 5).join(", ")}`);
  }
  if (report.invalid.length) {
    parts.push(`rejected: ${report.invalid.slice(0, 8).join(", ")}`);
  }
  return parts.join(" | ");
}

function renderImportSummary() {
  const summary = document.getElementById("import_summary");
  if (summary) {
    summary.textContent = state.draft.importSummary || "";
  }
  const count = document.getElementById("selected_count");
  if (count) {
    count.textContent = `${state.draft.selectedSymbols.size} selected`;
    count.classList.toggle("warning-text", state.draft.selectedSymbols.size > STRONG_WARNING_SYMBOLS);
  }
  const candidateMeta = document.getElementById("candidate_meta");
  if (candidateMeta) {
    candidateMeta.textContent = `${visibleCandidateRows().length} visible / ${state.draft.candidateRows.length} loaded`;
  }
}

function renderCandidateTable() {
  const list = document.getElementById("candidate_list");
  if (!list) {
    return;
  }
  list.innerHTML = "";
  const rows = visibleCandidateRows();
  if (!rows.length) {
    const empty = document.createElement("div");
    empty.className = "empty-list";
    empty.textContent = state.universeMenu.db?.available
      ? "No candidates loaded for this pool/filter."
      : "Database-backed pool browser is unavailable.";
    list.appendChild(empty);
    renderImportSummary();
    return;
  }

  rows.forEach((row) => {
    const item = document.createElement("div");
    item.className = "asset-row";
    item.classList.toggle("selected-row", state.draft.selectedSymbols.has(row.provider_symbol));
    item.classList.toggle("focused-row", state.draft.focusedSymbol === row.provider_symbol);
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = state.draft.selectedSymbols.has(row.provider_symbol);
    checkbox.addEventListener("click", (event) => {
      event.stopPropagation();
    });
    checkbox.addEventListener("change", () => {
      setSymbolSelected(row, checkbox.checked);
    });
    const text = document.createElement("div");
    text.className = "asset-text";
    const title = document.createElement("strong");
    title.textContent = `${row.provider_symbol} - ${row.name || "Unnamed"}`;
    const meta = document.createElement("span");
    meta.textContent = `${sourceLabel(row.source)} | ${row.exchange || "N/A"} | ${row.type || "N/A"}`;
    text.append(title, meta);
    item.append(checkbox, text);

    item.addEventListener("click", (event) => {
      if (event.metaKey || event.ctrlKey) {
        toggleSymbol(row);
      } else {
        state.draft.focusedSymbol = row.provider_symbol;
        renderCandidateTable();
      }
    });
    item.addEventListener("dblclick", () => toggleSymbol(row));
    list.appendChild(item);
  });
  renderImportSummary();
}

function visibleCandidateRows() {
  const filter = (document.getElementById("candidate_filter")?.value || "").trim().toUpperCase();
  if (!filter) {
    return state.draft.candidateRows;
  }
  return state.draft.candidateRows.filter((row) =>
    [row.provider_symbol, row.symbol, row.name, row.exchange, row.type, sourceLabel(row.source)]
      .join(" ")
      .toUpperCase()
      .includes(filter)
  );
}

function renderSelectedTable() {
  const list = document.getElementById("selected_list");
  if (!list) {
    return;
  }
  list.innerHTML = "";
  const rows = selectedRows();
  if (!rows.length) {
    const empty = document.createElement("div");
    empty.className = "empty-list";
    empty.textContent = "No stocks selected.";
    list.appendChild(empty);
    return;
  }

  rows.forEach((row) => {
    const item = document.createElement("div");
    item.className = "asset-row selected-row";
    const text = document.createElement("div");
    text.className = "asset-text";
    const title = document.createElement("strong");
    title.textContent = `${row.provider_symbol} - ${row.name || "Unnamed"}`;
    const meta = document.createElement("span");
    meta.textContent = `${sourceLabel(row.source)} | ${row.exchange || "N/A"} | ${row.type || "N/A"}`;
    text.append(title, meta);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "mini-button";
    button.textContent = "Remove";
    button.addEventListener("click", () => {
      state.draft.selectedSymbols.delete(row.provider_symbol);
      renderCandidateTable();
      renderSelectedTable();
      renderImportSummary();
    });
    item.append(text, button);
    list.appendChild(item);
  });
}

function setSymbolSelected(row, selected) {
  if (selected) {
    if (state.draft.selectedSymbols.size >= MAX_SELECTED_SYMBOLS && !state.draft.selectedSymbols.has(row.provider_symbol)) {
      setStatus(`Selection is capped at ${MAX_SELECTED_SYMBOLS} tickers`, true);
      return;
    }
    state.draft.selectedSymbols.set(row.provider_symbol, row);
  } else {
    state.draft.selectedSymbols.delete(row.provider_symbol);
  }
  renderCandidateTable();
  renderSelectedTable();
  renderImportSummary();
}

function toggleSymbol(row) {
  setSymbolSelected(row, !state.draft.selectedSymbols.has(row.provider_symbol));
}

function clearSelectedSymbols() {
  state.draft.selectedSymbols = new Map();
  renderCandidateTable();
  renderSelectedTable();
  renderImportSummary();
}

function addCandidateRow(row) {
  if (!state.draft.candidateRows.some((item) => item.provider_symbol === row.provider_symbol)) {
    state.draft.candidateRows.push(row);
  }
}

function dedupeRows(rows) {
  const deduped = new Map();
  rows.forEach((row) => {
    if (row?.provider_symbol && !deduped.has(row.provider_symbol)) {
      deduped.set(row.provider_symbol, row);
    }
  });
  return Array.from(deduped.values()).sort((left, right) =>
    left.provider_symbol.localeCompare(right.provider_symbol)
  );
}

function manualRow(providerSymbol, source) {
  const exchange = providerSymbol.includes(".") ? providerSymbol.split(".").pop() : draftRequestExchange();
  return {
    provider_symbol: providerSymbol,
    symbol: providerSymbol.split(".", 1)[0],
    name: source === "confirmed" ? "Confirmed request" : "User imported",
    exchange,
    type: "manual",
    source,
  };
}

function sourceLabel(source) {
  if (source === "db_preset") {
    return "DB preset";
  }
  if (source === "db_exchange") {
    return "DB exchange";
  }
  if (source === "db_asset_type") {
    return "DB asset type";
  }
  if (source === "db_index_assets") {
    return "DB index asset";
  }
  if (source === "db_import") {
    return "DB import";
  }
  if (source === "import") {
    return "User imported";
  }
  if (source === "confirmed") {
    return "Confirmed request";
  }
  return "Database";
}

function renderParameterStep(spec) {
  const note = document.getElementById("wizard_endpoint_note");
  note.innerHTML = "";
  const title = document.createElement("strong");
  title.textContent = spec.path_pattern;
  const description = document.createElement("span");
  description.textContent = ` ${spec.description} ${spec.call_cost_note}`;
  note.append(title, description);

  const params = document.getElementById("wizard_params");
  params.innerHTML = "";
  (spec.params || []).forEach((param) => {
    if (param.name === "symbols") {
      return;
    }
    if (hasSymbolParam(spec) && param.name === "exchange") {
      return;
    }
    params.appendChild(renderParamField(param));
  });
  bindParamInputs(spec);
  updateDateOffsetPanel();
}

function renderParamField(param) {
  const field = document.createElement("div");
  field.className = param.kind === "checkbox" ? "field check-field" : "field";

  if (param.kind === "checkbox") {
    const label = document.createElement("label");
    label.className = "check";
    const input = document.createElement("input");
    input.id = paramId(param.name);
    input.type = "checkbox";
    input.checked = Boolean(state.draft.params[param.name]);
    label.append(input, document.createTextNode(param.label));
    field.appendChild(label);
    appendHelp(field, param.help_text);
    return field;
  }

  const label = document.createElement("label");
  label.htmlFor = paramId(param.name);
  label.textContent = param.required ? `${param.label} *` : param.label;
  field.appendChild(label);

  if (param.kind === "select") {
    const select = document.createElement("select");
    select.id = paramId(param.name);
    (param.choices || []).forEach((choice) => {
      const option = document.createElement("option");
      option.value = choice.value;
      option.textContent = choice.label;
      select.appendChild(option);
    });
    select.value = state.draft.params[param.name] ?? param.default ?? "";
    field.appendChild(select);
  } else if (param.kind === "textarea") {
    const textarea = document.createElement("textarea");
    textarea.id = paramId(param.name);
    textarea.value = state.draft.params[param.name] ?? "";
    textarea.placeholder = param.placeholder || "";
    textarea.rows = 4;
    field.appendChild(textarea);
  } else {
    const input = document.createElement("input");
    input.id = paramId(param.name);
    input.type = param.kind === "date" ? "date" : param.kind === "number" ? "number" : "text";
    input.value = state.draft.params[param.name] ?? "";
    input.placeholder = param.placeholder || "";
    if (param.min_value !== null && param.min_value !== undefined) {
      input.min = param.min_value;
    }
    if (param.max_value !== null && param.max_value !== undefined) {
      input.max = param.max_value;
    }
    field.appendChild(input);
  }

  appendHelp(field, param.help_text);
  return field;
}

function appendHelp(field, helpText) {
  if (!helpText) {
    return;
  }
  const help = document.createElement("div");
  help.className = "help";
  help.textContent = helpText;
  field.appendChild(help);
}

function bindParamInputs(spec) {
  (spec.params || []).forEach((param) => {
    const element = document.getElementById(paramId(param.name));
    if (!element) {
      return;
    }
    element.addEventListener("change", () => {
      state.draft.params[param.name] = readParamValue(param);
    });
    element.addEventListener("input", () => {
      state.draft.params[param.name] = readParamValue(param);
    });
  });
}

function readParamValue(param) {
  const element = document.getElementById(paramId(param.name));
  if (!element) {
    return state.draft.params[param.name];
  }
  if (param.kind === "checkbox") {
    return element.checked;
  }
  if (param.kind === "number") {
    return element.value.trim() === "" ? "" : Number.parseInt(element.value, 10);
  }
  return element.value;
}

function renderFormatOptions() {
  const spec = endpointSpec();
  const select = document.getElementById("wizard_fmt");
  select.innerHTML = "";
  (spec.formats || ["json"]).forEach((fmt) => {
    const option = document.createElement("option");
    option.value = fmt;
    option.textContent = fmt.toUpperCase();
    select.appendChild(option);
  });
  select.value = state.draft.fmt;
  select.addEventListener("change", () => {
    state.draft.fmt = select.value;
    refreshDraftReview();
  });

  const preview = document.getElementById("wizard_preview_limit");
  preview.value = String(state.draft.previewLimit);
  preview.addEventListener("change", () => {
    state.draft.previewLimit = clampInteger(preview.value, 1, 500);
    preview.value = String(state.draft.previewLimit);
    refreshDraftReview();
  });
}

function renderReviewStep() {
  renderFormatOptions();
  renderReviewContent();
  refreshDraftReview();
}

function renderReviewContent() {
  const review = document.getElementById("wizard_review");
  const meta = functionMeta(state.draft.endpoint);
  const selectedCount = state.draft.selectedSymbols.size;
  const warnings = draftWarnings();
  const validation = state.draft.review;

  review.innerHTML = "";
  const rows = [
    ["Function", `${meta.title} / ${meta.cn}`],
    ["Endpoint", state.draft.endpoint],
    ["Symbols", hasSymbolParam(endpointSpec()) ? `${selectedCount} selected` : "Not required"],
    ["Format", state.draft.fmt.toUpperCase()],
    ["Preview rows", String(state.draft.previewLimit)],
  ];
  if (validation?.cost) {
    rows.push(["Estimated API calls", `${validation.cost.estimated_api_calls} (${validation.cost.message})`]);
  } else {
    rows.push(["Estimated API calls", "Checking..."]);
  }

  const table = document.createElement("table");
  const tbody = document.createElement("tbody");
  rows.forEach(([label, value]) => {
    const tr = document.createElement("tr");
    const th = document.createElement("th");
    th.textContent = label;
    const td = document.createElement("td");
    td.textContent = value;
    tr.append(th, td);
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  review.appendChild(table);

  if (validation?.error) {
    const error = document.createElement("div");
    error.className = "notice error-notice";
    error.textContent = validation.error;
    review.appendChild(error);
  }

  warnings.forEach((message) => {
    const warning = document.createElement("div");
    warning.className = "notice warning-notice";
    warning.textContent = message;
    review.appendChild(warning);
  });
}

async function refreshDraftReview() {
  if (!state.draft || state.draft.step !== 3) {
    return;
  }
  state.draft.review = null;
  renderReviewContent();
  try {
    const data = await postJson("/api/generate", buildPayloadFromDraft());
    state.draft.review = { cost: data.cost || null, error: "" };
  } catch (error) {
    state.draft.review = { cost: null, error: error.message };
  }
  renderReviewContent();
}

function draftWarnings() {
  const warnings = [];
  const count = state.draft.selectedSymbols.size;
  if (count > STRONG_WARNING_SYMBOLS) {
    warnings.push(`Strong warning: ${count} tickers selected. Most endpoints spend one API call per ticker.`);
  }
  if (count > MAX_SELECTED_SYMBOLS) {
    warnings.push(`Selection exceeds the hard cap of ${MAX_SELECTED_SYMBOLS} tickers.`);
  }
  if (state.draft.endpoint === "bulk_last_day_eod") {
    warnings.push("Bulk EOD can consume 100 API calls per exchange/date, plus one extra call per ticker.");
  }
  return warnings;
}

async function confirmDraft() {
  setStatus("Generating confirmed request");
  try {
    const payload = buildPayloadFromDraft();
    const data = await postJson("/api/generate", payload);
    state.confirmedPayload = payload;
    state.confirmedRequest = data.request;
    state.currentCost = data.cost || null;
    state.currentEndpoint = payload.endpoint;
    renderSnippets(data.snippets);
    renderConfirmedSummary();
    if (state.rows.length) {
      state.resultStale = true;
      renderMeta(state.executionMeta);
    }
    closeRequestWizard();
    setActiveFunctionCard(payload.endpoint);
    setStatus("Confirmed and generated");
  } catch (error) {
    setStatus(error.message, true);
  }
}

function renderConfirmedSummary() {
  const summary = document.getElementById("request_summary");
  summary.innerHTML = "";
  if (!state.confirmedRequest) {
    const empty = document.createElement("div");
    empty.innerHTML = "<strong>No confirmed request</strong><span>Click a function above and finish the wizard.</span>";
    summary.appendChild(empty);
    return;
  }

  const meta = functionMeta(state.confirmedRequest.endpoint);
  const params = state.confirmedRequest.params || {};
  const selected = toArray(params.symbols);
  const chips = [
    `${meta.title} / ${meta.cn}`,
    `endpoint: ${state.confirmedRequest.endpoint}`,
    `format: ${state.confirmedRequest.fmt.toUpperCase()}`,
  ];
  if (selected.length) {
    chips.push(`${selected.length} ticker(s)`);
  }
  if (params.date_from || params.date_to) {
    chips.push(`${params.date_from || "..."} to ${params.date_to || "..."}`);
  }
  if (params.trade_date) {
    chips.push(`date: ${params.trade_date}`);
  }
  if (state.currentCost) {
    chips.push(`${state.currentCost.estimated_api_calls} estimated call(s)`);
  }

  chips.forEach((chip) => {
    const item = document.createElement("span");
    item.className = "summary-chip";
    item.textContent = chip;
    summary.appendChild(item);
  });

  if (selected.length > STRONG_WARNING_SYMBOLS) {
    const warning = document.createElement("span");
    warning.className = "summary-chip warning-chip";
    warning.textContent = "More than 100 tickers selected";
    summary.appendChild(warning);
  }
}

async function executeConfirmed() {
  if (!state.confirmedPayload) {
    setStatus("Confirm a request before Execute API", true);
    return;
  }
  setStatus("Executing");
  try {
    const payload = structuredCloneSafe(state.confirmedPayload);
    const generated = await postJson("/api/generate", payload);
    state.currentCost = generated.cost || null;
    renderSnippets(generated.snippets);
    renderConfirmedSummary();
    if (state.currentCost?.requires_confirmation) {
      const confirmed = window.confirm(
        `This request is estimated to consume ${state.currentCost.estimated_api_calls} API calls. Continue?`
      );
      if (!confirmed) {
        setStatus("Execution cancelled");
        return;
      }
      payload.confirm_cost = true;
    }
    const data = await postJson("/api/execute", payload);
    const result = data.result;
    state.rows = result.rows || [];
    state.executionMeta = result;
    state.resultStale = false;
    renderTable(result.preview_rows || []);
    renderMeta(result);
    document.getElementById("export_csv").disabled = state.rows.length === 0;
    setStatus("Executed");
  } catch (error) {
    if (state.rows.length) {
      state.resultStale = true;
      renderMeta(state.executionMeta, `Execution failed: ${error.message}`);
    }
    setStatus(error.message, true);
  }
}

function renderSnippets(snippets) {
  document.getElementById("urls").textContent = (snippets.direct_urls || []).join("\n");
  document.getElementById("python").textContent = snippets.python_requests || "";
  document.getElementById("python_loop").textContent = snippets.python_symbol_loop || "";
  document.getElementById("curl").textContent = snippets.curl || "";
  document.getElementById("javascript").textContent = snippets.javascript_fetch || "";
  document.getElementById("javascript_loop").textContent = snippets.javascript_symbol_loop || "";
  document.getElementById("local_proxy").textContent = snippets.local_proxy_python || "";
}

function renderTable(rows) {
  const table = document.getElementById("preview_table");
  const thead = table.querySelector("thead");
  const tbody = table.querySelector("tbody");
  thead.innerHTML = "";
  tbody.innerHTML = "";
  if (!rows.length) {
    return;
  }

  const columns = Array.from(
    rows.reduce((keys, row) => {
      Object.keys(row).forEach((key) => keys.add(key));
      return keys;
    }, new Set())
  );

  const headRow = document.createElement("tr");
  columns.forEach((column) => {
    const th = document.createElement("th");
    th.textContent = column;
    headRow.appendChild(th);
  });
  thead.appendChild(headRow);

  rows.forEach((row) => {
    const tr = document.createElement("tr");
    columns.forEach((column) => {
      const td = document.createElement("td");
      const value = row[column];
      td.textContent = value === null || value === undefined ? "" : String(value);
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
}

function renderMeta(result, prefix = "") {
  const meta = document.getElementById("preview_meta");
  if (!result) {
    meta.textContent = prefix || "No request executed";
    return;
  }
  const parts = [
    `${result.source_row_count} source rows`,
    `${result.returned_row_count} returned`,
    `${result.requests_made} request(s)`,
  ];
  if (result.truncated) {
    parts.push("capped for browser export");
  }
  if (state.resultStale) {
    parts.unshift("Previous result");
  }
  if (prefix) {
    parts.unshift(prefix);
  }
  meta.textContent = parts.join(" | ");
}

function exportCsv() {
  const csvText = buildCsvText(state.rows);
  if (!csvText) {
    setStatus("No executed rows to export", true);
    return;
  }
  downloadCsvText(csvText);
  setStatus(`Exported ${state.rows.length} row(s)`);
}

function buildCsvText(rows) {
  if (!rows.length) {
    return "";
  }
  const columns = Array.from(
    rows.reduce((keys, row) => {
      Object.keys(row).forEach((key) => keys.add(key));
      return keys;
    }, new Set())
  );
  if (!columns.length) {
    return "";
  }
  const lines = [columns.map(csvCell).join(",")];
  rows.forEach((row) => {
    lines.push(columns.map((column) => csvCell(row[column])).join(","));
  });
  return lines.join("\n");
}

function downloadCsvText(csvText) {
  const blob = new Blob([csvText], { type: "text/csv;charset=utf-8" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `eodhd_export_${new Date().toISOString().slice(0, 19).replaceAll(":", "-")}.csv`;
  document.body.appendChild(link);
  link.click();
  const objectUrl = link.href;
  window.setTimeout(() => {
    link.remove();
    URL.revokeObjectURL(objectUrl);
  }, 1000);
}

function csvCell(value) {
  const text = value === null || value === undefined ? "" : String(value);
  const safeText = /^[=+\-@]/.test(text) ? `'${text}` : text;
  return `"${safeText.replaceAll('"', '""')}"`;
}

function switchTab(nextTab) {
  state.currentTab = nextTab;
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.tab === nextTab);
  });
  document.querySelectorAll(".tab-panel").forEach((panel) => {
    panel.classList.toggle("hidden", panel.id !== nextTab);
  });
}

async function copyActiveSnippet() {
  const text = document.getElementById(state.currentTab)?.textContent || "";
  if (!text || text.startsWith("Confirm a request")) {
    setStatus("Nothing to copy", true);
    return;
  }
  if (!navigator.clipboard) {
    setStatus("Clipboard API is not available", true);
    return;
  }
  try {
    await navigator.clipboard.writeText(text);
    setStatus("Copied");
  } catch (error) {
    setStatus(error.message, true);
  }
}

function renderTokenStatus(token) {
  const status = token || { configured: false, source: "none", message: "No token configured." };
  document.getElementById("token_status").textContent = status.message;
  document.getElementById("delete_token").disabled = !status.can_delete;
  document.getElementById("token_input").value = "";
}

async function saveToken() {
  setStatus("Saving token");
  try {
    const data = await postJson("/api/config/token", { token: valueOf("token_input") });
    renderTokenStatus(data.token);
    setStatus("Token saved");
  } catch (error) {
    setStatus(error.message, true);
  }
}

async function deleteToken() {
  setStatus("Deleting token");
  try {
    const data = await deleteJson("/api/config/token");
    renderTokenStatus(data.token);
    setStatus("Token deleted");
  } catch (error) {
    setStatus(error.message, true);
  }
}

function openConfig() {
  configModal.classList.remove("hidden");
  loadConfigStatus().catch((error) => setStatus(error.message, true));
}

function closeConfig() {
  configModal.classList.add("hidden");
  document.getElementById("token_input").value = "";
}

function updateDateOffsetPanel() {
  const panel = document.getElementById("date_offset_panel");
  const hasDateField = Boolean(
    document.getElementById(paramId("date_from")) ||
      document.getElementById(paramId("date_to")) ||
      document.getElementById(paramId("trade_date"))
  );
  panel.classList.toggle("hidden", !hasDateField);
}

function applyDateOffset() {
  const anchorValue = valueOf("date_anchor") || todayIso();
  const anchorDate = parseIsoDate(anchorValue);
  if (!anchorDate) {
    setStatus("Anchor date is invalid", true);
    return;
  }
  const calendar = valueOf("date_offset_calendar");
  const fromOffset = numberValue("date_from_offset");
  const toOffset = numberValue("date_to_offset");
  if (!Number.isFinite(fromOffset) || !Number.isFinite(toOffset)) {
    setStatus("Date offsets must be numbers", true);
    return;
  }
  setDateField("date_from", offsetDate(anchorDate, fromOffset, calendar));
  setDateField("date_to", offsetDate(anchorDate, toOffset, calendar));
  if (!document.getElementById(paramId("date_from")) && !document.getElementById(paramId("date_to"))) {
    setDateField("trade_date", offsetDate(anchorDate, toOffset, calendar));
  }
  setStatus("Date offsets applied");
}

function setDateField(name, date) {
  const field = document.getElementById(paramId(name));
  if (field) {
    field.value = formatDate(date);
    state.draft.params[name] = field.value;
  }
}

function offsetDate(anchorDate, offset, calendar) {
  const date = new Date(anchorDate.getTime());
  if (calendar === "calendar") {
    date.setDate(date.getDate() + offset);
    return date;
  }
  const direction = offset < 0 ? -1 : 1;
  let remaining = Math.abs(offset);
  while (remaining > 0) {
    date.setDate(date.getDate() + direction);
    if (isBusinessDay(date)) {
      remaining -= 1;
    }
  }
  return date;
}

function isBusinessDay(date) {
  const day = date.getDay();
  return day !== 0 && day !== 6;
}

function parseIsoDate(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return null;
  }
  const [year, month, day] = value.split("-").map((part) => Number.parseInt(part, 10));
  return new Date(year, month - 1, day);
}

function formatDate(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function todayIso() {
  return formatDate(new Date());
}

function focusDateHelper() {
  openRequestWizard(state.currentEndpoint || "historical_eod");
  state.draft.step = 2;
  renderWizard();
  if (document.getElementById("date_offset_panel").classList.contains("hidden")) {
    setStatus("Current function has no date field", true);
  }
}

function applyProgramLanguageChoice() {
  const language = valueOf("program_language").toLowerCase();
  if (language === "python") {
    switchTab("python");
  } else if (language === "javascript") {
    switchTab("javascript");
  } else if (language === "curl") {
    switchTab("curl");
  }
}

function setActiveFunctionCard(endpointId) {
  document.querySelectorAll(".function-card").forEach((button) => {
    button.classList.toggle("active", button.dataset.endpoint === endpointId);
  });
}

function setStatus(message, isError = false) {
  statusBox.textContent = message;
  statusBox.classList.toggle("error", isError);
}

function providerSymbolFromToken(token, exchange = "US") {
  const symbol = normalizeSymbolToken(token);
  if (!/^[A-Z0-9][A-Z0-9._-]{0,39}$/.test(symbol)) {
    return "";
  }
  const cleanExchange = (exchange || "US").toUpperCase();
  if (cleanExchange !== "US") {
    return symbol.includes(".") ? symbol : `${symbol}.${cleanExchange}`;
  }
  const body = symbol.endsWith(".US") ? symbol.slice(0, -3) : symbol;
  if (isUsListingVenueSymbol(body)) {
    return `${normalizeUsSymbolBody(stripUsListingVenue(body))}.US`;
  }
  if (symbol.endsWith(".US")) {
    return `${normalizeUsSymbolBody(body)}.US`;
  }
  return `${normalizeUsSymbolBody(body)}.US`;
}

function normalizeSymbolToken(token) {
  return String(token || "")
    .trim()
    .toUpperCase()
    .replace(/\s+US\s+EQUITY$/, ".US")
    .replace(/\s+EQUITY$/, "")
    .replace(/\//g, ".");
}

function normalizeUsSymbolBody(symbol) {
  const stripped = stripUsListingVenue(symbol);
  if (stripped !== symbol) {
    return normalizeUsSymbolBody(stripped);
  }
  if (!isUsClassSymbolBody(symbol)) {
    return symbol;
  }
  const parts = symbol.split(".");
  return `${parts[0]}-${parts[1]}`;
}

function stripUsListingVenue(symbol) {
  const parts = symbol.split(".");
  if (parts.length !== 2) {
    return symbol;
  }
  return US_LISTING_SUFFIXES.has(parts[1]) ? parts[0] : symbol;
}

function isUsListingVenueSymbol(symbol) {
  const parts = symbol.split(".");
  return parts.length === 2 && Boolean(parts[0]) && US_LISTING_SUFFIXES.has(parts[1]);
}

function isUsClassSymbolBody(symbol) {
  if (!symbol.includes(".")) {
    return false;
  }
  const parts = symbol.split(".");
  return parts.length === 2 && Boolean(parts[0]) && US_CLASS_SUFFIXES.has(parts[1]);
}

function toArray(value) {
  if (!value) {
    return [];
  }
  if (Array.isArray(value)) {
    return value;
  }
  if (typeof value === "string") {
    return value
      .split(/[,\n\r\t ]+/)
      .map((part) => part.trim())
      .filter(Boolean);
  }
  return [];
}

function clampInteger(value, min, max) {
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed)) {
    return min;
  }
  return Math.min(Math.max(parsed, min), max);
}

function structuredCloneSafe(value) {
  return JSON.parse(JSON.stringify(value));
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function bindEvents() {
  document.getElementById("configure_active").addEventListener("click", () => openRequestWizard(state.currentEndpoint));
  document.getElementById("edit_confirmed").addEventListener("click", () => openRequestWizard(state.currentEndpoint));
  document.getElementById("execute").addEventListener("click", executeConfirmed);
  document.getElementById("export_csv").addEventListener("click", exportCsv);
  document.getElementById("copy_snippet").addEventListener("click", copyActiveSnippet);
  document.getElementById("config_open").addEventListener("click", openConfig);
  document.getElementById("config_close").addEventListener("click", closeConfig);
  document.getElementById("save_token").addEventListener("click", saveToken);
  document.getElementById("delete_token").addEventListener("click", deleteToken);
  document.getElementById("wizard_close").addEventListener("click", closeRequestWizard);
  document.getElementById("wizard_back").addEventListener("click", () => {
    state.draft.step = Math.max(1, state.draft.step - 1);
    renderWizard();
  });
  document.getElementById("wizard_next").addEventListener("click", () => {
    state.draft.step = Math.min(3, state.draft.step + 1);
    renderWizard();
  });
  document.getElementById("wizard_confirm").addEventListener("click", confirmDraft);
  document.getElementById("apply_date_offset").addEventListener("click", applyDateOffset);
  document.getElementById("ribbon_tdays").addEventListener("click", focusDateHelper);
  document.getElementById("program_language").addEventListener("change", applyProgramLanguageChoice);
  document.querySelectorAll(".function-card").forEach((button) => {
    button.addEventListener("click", () => openRequestWizard(button.dataset.endpoint));
  });
  document.querySelectorAll(".step-pill").forEach((button) => {
    button.addEventListener("click", () => {
      state.draft.step = Number.parseInt(button.dataset.step, 10);
      renderWizard();
    });
  });
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => switchTab(tab.dataset.tab));
  });
}

document.getElementById("date_anchor").value = todayIso();
bindEvents();

Promise.all([loadEndpoints(), loadUniverseMenu(), loadConfigStatus()])
  .then(() => {
    setActiveFunctionCard(state.currentEndpoint);
    renderConfirmedSummary();
    setStatus("Ready");
  })
  .catch((error) => setStatus(error.message, true));
