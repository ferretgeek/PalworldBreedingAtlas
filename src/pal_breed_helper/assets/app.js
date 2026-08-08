(function (root) {
  "use strict";

  const PalSolver = (() => {
    const preparedDataCache = new WeakMap();
    const STRATEGIES = Object.freeze({
      FASTEST: "fastest",
      FEW_EXTRA: "few-extra",
      ZERO_EXTRA: "zero-extra",
      BALANCED: "balanced",
    });

    function normalizeGender(value) {
      if (value === null || value === undefined || value === "") return "";
      const text = String(value).trim().toLowerCase();
      if (["m", "male", "man", "boy", "♂", "1"].includes(text)) return "male";
      if (["f", "female", "woman", "girl", "♀", "2"].includes(text)) return "female";
      if (["any", "either", "wildcard", "*", "任意", "不限", "unknown", "未知", "0"].includes(text)) return "any";
      return text;
    }

    function genderLabel(value) {
      const gender = normalizeGender(value);
      if (gender === "male") return "雄性";
      if (gender === "female") return "雌性";
      if (gender === "any") return "任意性别";
      return gender ? String(value) : "性别未注明";
    }

    function normalizePair(raw) {
      if (Array.isArray(raw)) {
        if (raw.length < 2 || raw[0] === undefined || raw[1] === undefined) return null;
        const constraints = raw[2] && typeof raw[2] === "object" ? raw[2] : {};
        const ga = normalizeGender(constraints.parent1Gender ?? constraints.parent1_gender ?? constraints.ga ?? constraints.genderA);
        const gb = normalizeGender(constraints.parent2Gender ?? constraints.parent2_gender ?? constraints.gb ?? constraints.genderB);
        return { a: String(raw[0]), b: String(raw[1]), ga, gb, legacy: !ga && !gb };
      }
      if (!raw || typeof raw !== "object" || raw.a === undefined || raw.b === undefined) return null;
      return {
        a: String(raw.a),
        b: String(raw.b),
        ga: normalizeGender(raw.ga ?? raw.genderA ?? raw.aGender),
        gb: normalizeGender(raw.gb ?? raw.genderB ?? raw.bGender),
        legacy: false,
      };
    }

    function pairEntries(pd, child) {
      return prepareData(pd).byChild.get(String(child)) || [];
    }

    function operationSignature(child, pair) {
      const left = `${pair.a}:${pair.ga || "?"}`;
      const right = `${pair.b}:${pair.gb || "?"}`;
      return `${child}<-${[left, right].sort().join("+")}`;
    }

    function prepareData(pd) {
      if (!pd || !pd.breed) return { children: [], byChild: new Map() };
      const cached = preparedDataCache.get(pd);
      if (cached) return cached;
      const byChild = new Map();
      const children = [];
      for (const child of Object.keys(pd.breed)) {
        const pairs = [];
        for (const raw of Array.isArray(pd.breed[child]) ? pd.breed[child] : []) {
          const pair = normalizePair(raw);
          if (!pair) continue;
          const signature = operationSignature(child, pair);
          Object.defineProperties(pair, {
            signature: { value: signature },
            operation: { value: { child, ...pair, signature } },
          });
          pairs.push(pair);
        }
        byChild.set(child, pairs);
        children.push({ child, pairs });
      }
      const prepared = { children, byChild };
      preparedDataCache.set(pd, prepared);
      return prepared;
    }

    function unionSets(a, b) {
      const result = new Set(a);
      for (const value of b) result.add(value);
      return result;
    }

    function stateHash(state) {
      return [
        [...state.operations.keys()].sort().join(","),
        [...state.extra].sort().join(","),
        [...state.owned].sort().join(","),
      ].join("#");
    }

    function baseState(key, type) {
      const state = {
        key,
        operations: new Map(),
        produced: new Set(),
        replaceable: new Set(),
        extra: new Set(type === "extra" ? [key] : []),
        owned: new Set(type === "owned" ? [key] : []),
        tree: { key, type },
        operationCount: 0,
        extraCount: type === "extra" ? 1 : 0,
        ownedCount: type === "owned" ? 1 : 0,
      };
      state.hash = stateHash(state);
      return state;
    }

    function acquisitionWeight(pd, key) {
      const pal = (pd && pd.pals && pd.pals[key]) || {};
      const value = Number(pal.acquisitionWeight ?? pal.acquireWeight ?? 0);
      return Number.isFinite(value) ? Math.max(0, value) : 0;
    }

    function metrics(pd, state) {
      if (state._metrics) return state._metrics;
      let acquisition = 0;
      for (const key of state.extra) acquisition += acquisitionWeight(pd, key);
      state._metrics = {
        operations: state.operationCount ?? state.operations.size,
        extra: state.extraCount ?? state.extra.size,
        acquisition,
        owned: state.ownedCount ?? state.owned.size,
      };
      return state._metrics;
    }

    function compareStates(pd, strategy, left, right) {
      if (!right) return -1;
      if (!left) return 1;
      const a = metrics(pd, left);
      const b = metrics(pd, right);
      let fields;
      if (strategy === STRATEGIES.FEW_EXTRA) {
        fields = [[a.extra, b.extra], [a.operations, b.operations], [a.acquisition, b.acquisition], [-a.owned, -b.owned]];
      } else if (strategy === STRATEGIES.ZERO_EXTRA) {
        fields = [[a.extra, b.extra], [a.operations, b.operations], [-a.owned, -b.owned]];
      } else if (strategy === STRATEGIES.BALANCED) {
        fields = [[a.operations * 2 + a.extra * 3 + a.acquisition, b.operations * 2 + b.extra * 3 + b.acquisition], [a.extra, b.extra], [a.operations, b.operations], [-a.owned, -b.owned]];
      } else {
        fields = [[a.operations, b.operations], [a.extra, b.extra], [a.acquisition, b.acquisition], [-a.owned, -b.owned]];
      }
      for (const [av, bv] of fields) {
        if (av !== bv) return av < bv ? -1 : 1;
      }
      return left.hash.localeCompare(right.hash);
    }

    function combineStates(child, pair, left, right) {
      if (!left || !right) return null;
      if (left.produced.has(child) || right.produced.has(child)) return null;
      const signature = pair.signature || operationSignature(child, pair);
      const operations = new Map(left.operations);
      for (const [key, value] of right.operations) operations.set(key, value);
      operations.set(signature, pair.operation || { child, ...pair, signature });
      const produced = unionSets(left.produced, right.produced);
      produced.add(child);
      const replaceable = unionSets(left.replaceable || new Set(), right.replaceable || new Set());
      if (!left.extra.has(child) && !right.extra.has(child)) replaceable.add(child);
      const owned = unionSets(left.owned, right.owned);
      const extra = unionSets(left.extra, right.extra);
      const removed = [];
      for (const producedKey of replaceable) {
        if (extra.delete(producedKey)) removed.push(producedKey);
      }
      if (removed.length && !canReachTarget(child, owned, extra, operations)) {
        for (const key of removed.sort()) {
          extra.add(key);
          if (canReachTarget(child, owned, extra, operations)) break;
        }
      }
      const state = {
        key: child,
        operations,
        produced,
        replaceable,
        extra,
        owned,
        tree: {
          key: child,
          type: "breed",
          pair,
          operation: signature,
          children: [left.tree, right.tree],
        },
        operationCount: operations.size,
        extraCount: extra.size,
        ownedCount: owned.size,
      };
      state.hash = stateHash(state);
      return state;
    }

    function canReachTarget(target, owned, extra, operations) {
      const available = unionSets(owned, extra);
      let changed = true;
      while (changed) {
        changed = false;
        for (const operation of operations.values()) {
          if (available.has(operation.child)) continue;
          if (available.has(operation.a) && available.has(operation.b)) {
            available.add(operation.child);
            changed = true;
          }
        }
      }
      return available.has(target);
    }

  function insertFrontier(pd, strategy, list, candidate, limit) {
    if (!candidate || list.some((item) => item.hash === candidate.hash)) return false;
    list.push(candidate);
    list.sort((a, b) => compareStates(pd, strategy, a, b));
    if (list.length > limit) list.length = limit;
    return list.includes(candidate);
  }

    function createFrontiers(pd, ownedSet, strategy, target) {
      const frontiers = {};
      for (const key of Object.keys(pd.pals || {})) {
        if (ownedSet.has(key)) frontiers[key] = [baseState(key, "owned")];
        else if (strategy !== STRATEGIES.ZERO_EXTRA && key !== target) frontiers[key] = [baseState(key, "extra")];
        else frontiers[key] = [];
      }
      return frontiers;
    }

    function relax(pd, frontiers, strategy, options = {}) {
      const skipChild = options.skipChild || null;
      const frontierLimit = Math.max(1, Number(options.frontierLimit || 5));
      const maxIterations = Math.max(1, Number(options.maxIterations || 10));
      const onCandidate = typeof options.onCandidate === "function" ? options.onCandidate : null;
      const children = prepareData(pd).children;
      let iterations = 0;
      let changed = true;
      while (changed && iterations < maxIterations) {
        changed = false;
        iterations += 1;
        for (const { child, pairs } of children) {
          if (child === skipChild || !frontiers[child]) continue;
          for (const pair of pairs) {
            const leftStates = frontiers[pair.a] || [];
            const rightStates = frontiers[pair.b] || [];
            if (!leftStates.length || !rightStates.length) continue;
            const leftSnapshot = pair.a === child ? [...leftStates] : leftStates;
            const rightSnapshot = pair.b === child ? [...rightStates] : rightStates;
            for (const left of leftSnapshot) {
              for (const right of rightSnapshot) {
                if (strategy === STRATEGIES.ZERO_EXTRA && frontiers[child].length >= frontierLimit) {
                  const worst = frontiers[child][frontiers[child].length - 1];
                  if (operationUnionSize(left.operations, right.operations, pair.signature) > (worst.operationCount ?? worst.operations.size)) continue;
                }
                const candidate = combineStates(child, pair, left, right);
                if (!candidate) continue;
                if (onCandidate) onCandidate(child, candidate);
                if (insertFrontier(pd, strategy, frontiers[child], candidate, frontierLimit)) changed = true;
              }
            }
          }
        }
      }
      return iterations;
    }

    function operationUnionSize(left, right, signature) {
      let size = left.size;
      for (const key of right.keys()) if (!left.has(key)) size += 1;
      if (!left.has(signature) && !right.has(signature)) size += 1;
      return size;
    }

    function solveDirectFastestRoutes(pd, ownedSet, target, limit) {
      const candidates = [];
      const seen = new Set();
      const parentState = (key) => {
        if (ownedSet.has(key)) return baseState(key, "owned");
        if (key === target) return null;
        return baseState(key, "extra");
      };
      for (const pair of pairEntries(pd, target)) {
        const left = parentState(pair.a);
        const right = parentState(pair.b);
        if (!left || !right) continue;
        const candidate = combineStates(target, pair, left, right);
        if (!candidate || seen.has(candidate.hash)) continue;
        seen.add(candidate.hash);
        candidate.strategy = STRATEGIES.FASTEST;
        candidate.target = target;
        candidate.iterations = 0;
        candidate.metrics = metrics(pd, candidate);
        candidates.push(candidate);
      }
      candidates.sort((left, right) => compareStates(pd, STRATEGIES.FASTEST, left, right));
      return candidates.slice(0, Math.max(1, Number(limit) || 1));
    }

    function solveRoutes({ pd, owned = [], target, strategy = STRATEGIES.FASTEST, requireOwned = false, frontierLimit, maxIterations, limit = 3 } = {}) {
      if (!pd || !pd.pals || !pd.breed || !target || !pd.pals[target]) return null;
      const ownedSet = owned instanceof Set ? new Set([...owned].map(String)) : new Set((owned || []).map(String));
      if (strategy === STRATEGIES.FASTEST && !requireOwned) {
        return solveDirectFastestRoutes(pd, ownedSet, String(target), limit);
      }
      const frontiers = createFrontiers(pd, ownedSet, strategy, String(target));
      const iterations = relax(pd, frontiers, strategy, {
        skipChild: String(target),
        frontierLimit: frontierLimit || (strategy === STRATEGIES.ZERO_EXTRA ? 5 : 2),
        maxIterations: maxIterations || (strategy === STRATEGIES.ZERO_EXTRA ? 5 : 8),
      });
      const candidates = [];
      for (const pair of pairEntries(pd, String(target))) {
        for (const left of frontiers[pair.a] || []) {
          for (const right of frontiers[pair.b] || []) {
            const candidate = combineStates(String(target), pair, left, right);
            if (!candidate) continue;
            if (strategy === STRATEGIES.ZERO_EXTRA && candidate.extra.size) continue;
            if (requireOwned && !candidate.owned.size) continue;
            if (!candidates.some((item) => item.hash === candidate.hash)) candidates.push(candidate);
          }
        }
      }
      candidates.sort((left, right) => compareStates(pd, strategy, left, right));
      return candidates.slice(0, Math.max(1, Number(limit) || 1)).map((result) => {
        result.strategy = strategy;
        result.target = String(target);
        result.iterations = iterations;
        result.metrics = metrics(pd, result);
        return result;
      });
    }

    function solveRoute(options = {}) {
      const routes = solveRoutes({ ...options, limit: 1 });
      return routes && routes[0] || null;
    }

    function discoverRoutes({ pd, owned = [], strategy = STRATEGIES.FEW_EXTRA, frontierLimit = 1, maxIterations = 10 } = {}) {
      if (!pd || !pd.pals || !pd.breed) return [];
      const ownedSet = owned instanceof Set ? new Set([...owned].map(String)) : new Set((owned || []).map(String));
      const frontiers = createFrontiers(pd, ownedSet, strategy, null);
      const bestBred = {};
      const onCandidate = (child, candidate) => {
        if (ownedSet.has(child)) return;
        if (!bestBred[child] || compareStates(pd, strategy, candidate, bestBred[child]) < 0) bestBred[child] = candidate;
      };
      relax(pd, frontiers, strategy, { frontierLimit, maxIterations, onCandidate });
      return Object.entries(bestBred).map(([key, state]) => {
        state.target = key;
        state.strategy = strategy;
        state.metrics = metrics(pd, state);
        return state;
      });
    }

    function orderedOperations(result) {
      if (!result || !result.tree) return [];
      const traversalOrder = new Map();
      let traversalIndex = 0;
      (function walk(node) {
        if (!node || node.type !== "breed") return;
        walk(node.children[0]);
        walk(node.children[1]);
        if (!traversalOrder.has(node.operation)) traversalOrder.set(node.operation, traversalIndex++);
      })(result.tree);
      const pending = [...result.operations.values()].sort((a, b) => (traversalOrder.get(a.signature) ?? 1e9) - (traversalOrder.get(b.signature) ?? 1e9));
      const producedKeys = new Set(pending.map((operation) => operation.child));
      const available = unionSets(result.owned || new Set(), result.extra || new Set());
      const rows = [];
      while (pending.length) {
        let progressed = false;
        for (let index = 0; index < pending.length; index += 1) {
          const operation = pending[index];
          const ready = [operation.a, operation.b].every((parent) => available.has(parent) || !producedKeys.has(parent));
          if (!ready) continue;
          rows.push(operation);
          available.add(operation.child);
          pending.splice(index, 1);
          progressed = true;
          break;
        }
        if (!progressed) {
          rows.push(...pending);
          break;
        }
      }
      return rows;
    }

    function combineInventoryRecords(ownedRecords, geneRecords, includeGenes) {
      const cloneRecord = (raw) => {
        const individuals = Array.isArray(raw && raw.individuals)
          ? raw.individuals.map((item) => ({
            ...item,
            talents: item && item.talents ? { ...item.talents } : {},
            passives: Array.isArray(item && item.passives) ? [...item.passives] : [],
          }))
          : [];
        const suppliedUntracked = Number(raw && raw.untrackedCount);
        const count = Number(raw && raw.count);
        return {
          ...raw,
          key: String(raw && raw.key || ""),
          individuals,
          untrackedCount: Number.isFinite(suppliedUntracked)
            ? Math.max(0, Math.floor(suppliedUntracked))
            : Math.max(0, (Number.isFinite(count) ? Math.floor(count) : 0) - individuals.length),
        };
      };
      const refreshCounts = (record) => {
        const tracked = record.individuals.length;
        const untracked = Math.max(0, Math.floor(Number(record.untrackedCount) || 0));
        const supplied = Number(record.count);
        record.count = tracked + untracked || (Number.isFinite(supplied) && supplied > 0 ? Math.floor(supplied) : null);
        record.male = record.individuals.filter((item) => item.gender === "male").length;
        record.female = record.individuals.filter((item) => item.gender === "female").length;
        record.unknownGender = record.individuals.filter((item) => item.gender !== "male" && item.gender !== "female").length + untracked;
        return record;
      };
      const merged = new Map();
      for (const raw of Array.isArray(ownedRecords) ? ownedRecords : []) {
        const record = refreshCounts(cloneRecord(raw));
        if (!record.key) continue;
        record.crossWorldOnly = false;
        record.crossWorldCount = 0;
        merged.set(record.key, record);
      }
      if (!includeGenes) return [...merged.values()];
      for (const raw of Array.isArray(geneRecords) ? geneRecords : []) {
        const gene = refreshCounts(cloneRecord(raw));
        if (!gene.key) continue;
        const geneCount = Number(gene.count) || 0;
        const current = merged.get(gene.key);
        if (!current) {
          gene.source = "cross-world";
          gene.crossWorldOnly = true;
          gene.crossWorldCount = geneCount;
          merged.set(gene.key, gene);
          continue;
        }
        current.individuals.push(...gene.individuals);
        current.untrackedCount += gene.untrackedCount;
        current.world = Number(current.world) || 0;
        current.box = (Number(current.box) || 0) + (Number(gene.box) || geneCount);
        current.crossWorldCount = (Number(current.crossWorldCount) || 0) + geneCount;
        refreshCounts(current);
      }
      return [...merged.values()];
    }

    return {
      STRATEGIES,
      normalizeGender,
      genderLabel,
      normalizePair,
      pairEntries,
      operationSignature,
      solveRoute,
      solveRoutes,
      discoverRoutes,
      orderedOperations,
      combineInventoryRecords,
      compareStates,
      __test: { baseState, combineStates },
    };
  })();

  if (typeof module !== "undefined" && module.exports) module.exports = PalSolver;
  root.PalSolver = PalSolver;
  if (typeof document === "undefined") return;

  const STORAGE_KEY = "pal-breed-helper.ui.v3";
  const PLANNER_CACHE_KEY = "pal-breed-helper.planner-cache.v1";
  const REVERSE_CACHE_KEY = "pal-breed-helper.reverse-cache.v1";
  const THEME_KEY = "pal-breed-helper.theme";
  const THEMES = new Set(["night", "light", "prism"]);
  const EXPECTED_PAL_COUNT = 287;
  const TYPE_LABELS = {
    normal: "普通",
    fire: "火",
    water: "水",
    leaf: "草",
    electricity: "电",
    ice: "冰",
    ground: "地",
    dark: "暗",
    dragon: "龙",
  };
  const ELEMENT_TYPES = ["fire", "water", "leaf", "electricity", "ice", "ground", "dark", "dragon", "normal"];
  const TARGET_PICKER_PAGE_SIZE = 60;
  const REVERSE_PAGE_SIZE = 48;
  const RECIPE_PAGE_SIZE = 30;
  const WORKS = [
    ["", "全部工作"],
    ["Kindling", "生火"],
    ["Watering", "浇水"],
    ["Planting", "播种"],
    ["Generating_Electricity", "发电"],
    ["Handiwork", "手工作业"],
    ["Gathering", "采集"],
    ["Lumbering", "伐木"],
    ["Mining", "采矿"],
    ["Medicine_Production", "制药"],
    ["Cooling", "制冷"],
    ["Transporting", "搬运"],
    ["Farming", "牧场"],
  ];
  const WORK_LABELS = Object.fromEntries(WORKS);

  const byId = (id) => document.getElementById(id);
  const escapeHtml = (value) => String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
  const normalizeType = (value) => {
    const type = String(value || "").toLowerCase();
    if (type === "earth") return "ground";
    if (type === "grass") return "leaf";
    if (type === "electric") return "electricity";
    if (type === "neutral") return "normal";
    return type || "normal";
  };
  const normalizeElementSelection = (values) => Array.isArray(values)
    ? [...new Set(values.map(normalizeType).filter((type) => TYPE_LABELS[type]))].slice(0, 1)
    : [];

  function toggleSingleElement(selection, type) {
    const shouldClear = selection.has(type);
    selection.clear();
    if (!shouldClear) selection.add(type);
  }

  function renderElementFilterButtons(container, selection) {
    if (!container) return;
    const existing = [...container.querySelectorAll("[data-element]")];
    if (existing.length !== ELEMENT_TYPES.length) {
      container.innerHTML = ELEMENT_TYPES.map((type) => {
        const count = allKeys.filter((key) => palTypes(key).includes(type)).length;
        return `<button class="element-filter element-${type}" type="button" data-element="${type}" aria-pressed="${selection.has(type)}"><span class="element-dot" aria-hidden="true"></span><span>${TYPE_LABELS[type]}</span><small>${count}</small></button>`;
      }).join("");
      return;
    }
    for (const button of existing) {
      button.setAttribute("aria-pressed", String(selection.has(button.dataset.element)));
    }
  }

  let PD;
  let PALDECK;
  let allKeys = [];
  let nameIndex = new Map();
  let searchTextCache = new Map();
  let pairIndex = null;
  let currentPlan = null;
  let currentPlanText = "";
  let reverseHasRun = false;
  let selectedDexElements = new Set();
  let selectedReverseElements = new Set();
  let selectedTargetElements = new Set();
  let elementsAvailable = true;
  let toastTimer = null;
  let persistTimer = null;
  let scrollMemoryTimer = null;
  let dexRenderTimer = null;
  let plannerSolveTimer = null;
  let targetPickerRenderTimer = null;
  let reverseRenderTimer = null;
  let plannerGeneration = 0;
  let reverseGeneration = 0;
  let reverseRouteCache = { key: "", rows: null };
  let reverseDiscoverPromise = null;
  let reverseDiscoverKey = "";
  let reverseRowsCache = [];
  let reverseRowsContext = { maxExtra: 2, only5: true, work: "", elements: new Set() };
  let reverseVisibleCount = REVERSE_PAGE_SIZE;
  let acquisitionRuleCache = new Map();
  let targetRankCache = new Map();
  let targetPickerVisibleCount = TARGET_PICKER_PAGE_SIZE;
  let targetPickerDirty = true;
  let targetPickerRestoreScroll = false;
  let recipeRowsCache = [];
  let recipeVisibleCount = RECIPE_PAGE_SIZE;
  let recipeTargetKey = "";
  let recipeRestrictionNotice = "";
  let currentRouteOptions = [];
  let selectedRouteOption = 0;
  let preferredRouteHash = "";
  let undoState = null;
  let undoTimer = null;
  let dexRowsCache = [];
  let dexVisibleCount = 72;
  let dexDirty = true;
  let derivedResultsReady = false;
  let solverWorker = null;
  let solverRequestId = 0;
  const solverRequests = new Map();
  let crossWorldGenes = new Map();
  let effectiveOwned = new Map();

  const appState = {
    owned: new Map(),
    showCrossWorldGenes: false,
    favorites: new Set(),
    recent: [],
    target: "",
    passives: "",
    strategy: PalSolver.STRATEGIES.FASTEST,
    requireOwned: false,
    activeView: "planner",
    inventorySearch: "",
    inventoryOpen: false,
    advancedOpen: false,
    dexSearch: "",
    dexWork: "",
    dexOwnOnly: false,
    dexFavoriteOnly: false,
    dexElements: [],
    dexWorkLevel: "0",
    dexCombatRole: "",
    dexAcquisition: "",
    dexSort: "number",
    reverseOnly5: true,
    reverseWork: "",
    reverseMaxExtra: "2",
    reverseElements: [],
    parentA: "",
    parentB: "",
    recipeTarget: "",
    recipesOwnedFirst: true,
    plannerRan: false,
    reverseRan: false,
    childLookupRan: false,
    recipeLookupRan: false,
    targetRecommendationMode: "battle",
    targetPickerMode: "battle",
    targetPickerSearch: "",
    targetPickerElements: [],
    homeCombatFilter: "",
    homeWorkFilter: "",
    reverseSort: "cost",
    reversePinned: [],
    routeDensity: "comfortable",
    routeHistory: [],
    favoriteRoutes: [],
    routeChecks: {},
    onboardingSeen: false,
    dexVisibleCount: 72,
    reverseVisibleCount: REVERSE_PAGE_SIZE,
    recipeVisibleCount: RECIPE_PAGE_SIZE,
    targetPickerVisibleCount: TARGET_PICKER_PAGE_SIZE,
    targetPickerScrollTop: 0,
    viewScrollPositions: {},
  };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();

  function boot() {
    PD = root.PD;
    PALDECK = root.PALDECK || {};
    if (!PD || !PD.pals || !PD.breed) {
      showFatalDataError();
      return;
    }
    allKeys = Object.keys(PD.pals).sort(comparePalKeys);
    elementsAvailable = detectElementAvailability();
    buildNameIndex();
    restoreState();
    applyInjectedInventory();
    populatePalList();
    populateWorkSelects();
    renderDataStatus();
    bindServerSaveControl();
    bindCrossWorldToggle();
    bindTheme();
    bindNavigation();
    bindInventory();
    bindPlanner();
    bindTargetPicker();
    bindReverse();
    bindDex();
    bindTools();
    bindSettings();
    bindGlobalActions();
    bindProductivityActions();
    syncControlsFromState();
    renderInventory();
    renderRecentTargets();
    renderSavedRouteShelf();
    renderTargetRecommendations();
    renderTargetPickerFilters();
    renderReverseFilters();
    renderReverseFilterSummary();
    renderReverseCompareTray();
    renderDexFilters();
    activateView(appState.activeView, { persist: false, focus: false });
    updateFavoriteTargetButton();
    restoreDerivedResults();
    showOnboardingIfNeeded();
  }

  function showFatalDataError() {
    const main = byId("mainContent");
    if (main) {
      main.innerHTML = '<section class="settings-card"><h1>数据未能载入</h1><p>缺少 window.PD.pals 或 window.PD.breed。请重新生成数据文件后再打开工具。</p></section>';
    }
    const badge = byId("sourceBadge");
    if (badge) {
      badge.textContent = "数据载入失败";
      badge.className = "status-pill status-pending";
    }
  }

  function comparePalKeys(a, b) {
    const an = Number.parseInt(a, 10);
    const bn = Number.parseInt(b, 10);
    if (an !== bn) return an - bn;
    return a.localeCompare(b, "zh-Hans-CN", { numeric: true });
  }

  function palName(key) {
    return (PD.pals[key] && PD.pals[key].zh) || String(key);
  }

  function palEnglish(key) {
    return (PD.pals[key] && PD.pals[key].en) || (PALDECK[key] && PALDECK[key].en) || "";
  }

  function palImage(key) {
    return (PALDECK[key] && PALDECK[key].img) || "";
  }

  function palNumber(key) {
    return (PALDECK[key] && PALDECK[key].no) || key;
  }

  function palTypes(key) {
    if (!elementsAvailable) return [];
    const values = (PD.pals[key] && PD.pals[key].t) || (PALDECK[key] && PALDECK[key].types) || [];
    return values.length ? [...new Set(values.map(normalizeType))] : ["normal"];
  }

  function detectElementAvailability() {
    const metaStatus = String((PD.meta && (PD.meta.elementStatus || PD.meta.element_status)) || "").toLowerCase();
    if (["unknown", "unverified", "missing"].includes(metaStatus)) return false;
    const rows = Object.values(PD.pals || {});
    if (rows.length && rows.every((pal) => String(pal.elementStatus || pal.element_status || "").toLowerCase() === "unknown")) return false;
    return rows.some((pal) => Array.isArray(pal.t) && pal.t.length) || Object.values(PALDECK || {}).some((pal) => Array.isArray(pal.types) && pal.types.length);
  }

  function buildNameIndex() {
    nameIndex = new Map();
    searchTextCache = new Map();
    for (const key of allKeys) {
      const aliases = root.PAL_ALIASES && root.PAL_ALIASES[key] || [];
      const values = [palName(key), palEnglish(key), `#${palNumber(key)}`, String(palNumber(key)), key, ...aliases];
      searchTextCache.set(key, values.join(" ").toLowerCase());
      for (const value of values) {
        if (!value) continue;
        const normalized = String(value).trim().toLowerCase();
        const current = nameIndex.get(normalized) || [];
        if (!current.includes(key)) current.push(key);
        nameIndex.set(normalized, current);
      }
    }
  }

  function palSearchText(key) {
    if (searchTextCache.has(key)) return searchTextCache.get(key);
    const aliases = root.PAL_ALIASES && root.PAL_ALIASES[key] || [];
    const value = [palName(key), palEnglish(key), palNumber(key), key, ...aliases].join(" ").toLowerCase();
    searchTextCache.set(key, value);
    return value;
  }

  function resolveKeyDetailed(value) {
    const text = String(value || "").trim();
    if (!text) return { key: null, ambiguous: [] };
    const normalized = text.toLowerCase();
    const exact = nameIndex.get(normalized) || [];
    if (exact.length === 1) return { key: exact[0], ambiguous: [] };
    const starts = allKeys.filter((key) => palSearchText(key).split(/\s+/).some((value) => value.startsWith(normalized)));
    if (starts.length === 1) return { key: starts[0], ambiguous: [] };
    const contains = starts.length ? starts : allKeys.filter((key) => palSearchText(key).includes(normalized));
    return contains.length === 1 ? { key: contains[0], ambiguous: [] } : { key: null, ambiguous: contains.slice(0, 8) };
  }

  function resolveKey(value) {
    return resolveKeyDetailed(value).key;
  }

  function populatePalList() {
    const list = byId("palList");
    const fragment = document.createDocumentFragment();
    for (const key of allKeys) {
      const option = document.createElement("option");
      option.value = palName(key);
      option.label = `#${palNumber(key)} · ${palEnglish(key)}`;
      fragment.appendChild(option);
    }
    list.replaceChildren(fragment);
  }

  function populateWorkSelects() {
    for (const id of ["reverseWork", "dexWork", "homeWorkFilter"]) {
      const select = byId(id);
      select.innerHTML = WORKS.map(([value, label]) => `<option value="${escapeHtml(value)}">${escapeHtml(label)}</option>`).join("");
    }
  }

  function safeStorageGet(key = STORAGE_KEY) {
    try {
      return root.localStorage.getItem(key);
    } catch (_) {
      return null;
    }
  }

  function safeStorageSet(value, key = STORAGE_KEY) {
    try {
      root.localStorage.setItem(key, value);
      return true;
    } catch (_) {
      return false;
    }
  }

  function safeStorageRemove(key = STORAGE_KEY) {
    try {
      root.localStorage.removeItem(key);
    } catch (_) {
      // File URLs can disable localStorage. The in-memory state still works.
    }
  }

  function bindTheme() {
    const current = THEMES.has(document.documentElement.dataset.theme) ? document.documentElement.dataset.theme : "night";
    applyTheme(current, false);
    for (const button of document.querySelectorAll("[data-theme-option]")) {
      button.addEventListener("click", () => applyTheme(button.dataset.themeOption, true));
    }
  }

  function applyTheme(theme, announce) {
    const next = THEMES.has(theme) ? theme : "night";
    document.documentElement.dataset.theme = next;
    for (const button of document.querySelectorAll("[data-theme-option]")) {
      button.setAttribute("aria-pressed", String(button.dataset.themeOption === next));
    }
    try {
      root.localStorage.setItem(THEME_KEY, next);
    } catch (_) {
      // 主题仍会在本次页面中生效。
    }
    if (announce) {
      const labels = { night: "幻夜深色", light: "云海浅色", prism: "幻彩浅色" };
      showToast(`已切换为${labels[next]}`);
    }
  }

  function bindCrossWorldToggle() {
    const button = byId("crossWorldToggle");
    if (!button) return;
    button.addEventListener("click", () => {
      if (!crossWorldGenes.size) return;
      appState.showCrossWorldGenes = !appState.showCrossWorldGenes;
      const count = [...crossWorldGenes.values()].reduce((sum, item) => sum + (item.count || 0), 0);
      inventoryChanged(
        appState.showCrossWorldGenes
          ? `已显示并纳入 ${count} 条跨界基因`
          : "已恢复为仅使用本世界库存",
      );
    });
    renderCrossWorldToggle();
  }

  function renderCrossWorldToggle() {
    const button = byId("crossWorldToggle");
    if (!button) return;
    const count = [...crossWorldGenes.values()].reduce((sum, item) => sum + (item.count || 0), 0);
    button.hidden = !crossWorldGenes.size;
    button.setAttribute("aria-pressed", String(appState.showCrossWorldGenes));
    button.title = appState.showCrossWorldGenes
      ? "隐藏跨界基因，只使用本世界现有帕鲁"
      : "显示跨界帕鲁终端中仍保存的基因，并临时纳入规划";
    const action = byId("crossWorldToggleAction");
    const value = byId("crossWorldToggleCount");
    if (action) action.textContent = appState.showCrossWorldGenes ? "隐藏" : "显示";
    if (value) value.textContent = String(count);
  }

  function restoreState() {
    const raw = safeStorageGet();
    if (raw) {
      try {
        const saved = JSON.parse(raw);
        for (const item of saved.owned || []) {
          const record = typeof item === "string" ? { key: item, count: null } : item;
          const key = String(record.key || "");
          if (PD.pals[key]) appState.owned.set(key, normalizeInventoryRecord(record, "local"));
        }
        appState.favorites = new Set((saved.favorites || []).map(String).filter((key) => PD.pals[key]));
        appState.recent = (saved.recent || []).map(String).filter((key) => PD.pals[key]).slice(0, 6);
        appState.target = String(saved.target || "");
        appState.passives = String(saved.passives || "");
        if (Object.values(PalSolver.STRATEGIES).includes(saved.strategy)) appState.strategy = saved.strategy;
        appState.requireOwned = Boolean(saved.requireOwned);
        if (["planner", "reverse", "dex", "tools", "settings"].includes(saved.activeView)) appState.activeView = saved.activeView;
        appState.inventorySearch = String(saved.inventorySearch || "");
        appState.inventoryOpen = Boolean(saved.inventoryOpen);
        appState.advancedOpen = Boolean(saved.advancedOpen);
        appState.dexSearch = String(saved.dexSearch || "");
        appState.dexWork = WORKS.some(([value]) => value === saved.dexWork) ? saved.dexWork : "";
        appState.dexOwnOnly = Boolean(saved.dexOwnOnly);
        appState.dexFavoriteOnly = Boolean(saved.dexFavoriteOnly);
        appState.dexElements = normalizeElementSelection(saved.dexElements);
        appState.dexWorkLevel = ["0", "3", "4", "5"].includes(String(saved.dexWorkLevel)) ? String(saved.dexWorkLevel) : "0";
        appState.dexCombatRole = ["", "attack", "tank", "speed", "balanced"].includes(saved.dexCombatRole) ? saved.dexCombatRole : "";
        appState.dexAcquisition = ["", "breedable", "external", "wild"].includes(saved.dexAcquisition) ? saved.dexAcquisition : "";
        appState.dexSort = ["number", "combat", "work", "speed"].includes(saved.dexSort) ? saved.dexSort : "number";
        appState.reverseOnly5 = saved.reverseOnly5 !== false;
        appState.reverseWork = WORKS.some(([value]) => value === saved.reverseWork) ? saved.reverseWork : "";
        appState.reverseMaxExtra = ["0", "1", "2", "3", "4"].includes(String(saved.reverseMaxExtra)) ? String(saved.reverseMaxExtra) : "2";
        appState.reverseElements = normalizeElementSelection(saved.reverseElements);
        appState.parentA = String(saved.parentA || "");
        appState.parentB = String(saved.parentB || "");
        appState.recipeTarget = String(saved.recipeTarget || "");
        appState.recipesOwnedFirst = saved.recipesOwnedFirst !== false;
        appState.plannerRan = Boolean(saved.plannerRan);
        appState.reverseRan = Boolean(saved.reverseRan);
        appState.childLookupRan = Boolean(saved.childLookupRan);
        appState.recipeLookupRan = Boolean(saved.recipeLookupRan);
        appState.targetRecommendationMode = ["battle", "work"].includes(saved.targetRecommendationMode) ? saved.targetRecommendationMode : "battle";
        appState.targetPickerMode = ["battle", "work", "all"].includes(saved.targetPickerMode) ? saved.targetPickerMode : "battle";
        appState.targetPickerSearch = String(saved.targetPickerSearch || "");
        appState.targetPickerElements = normalizeElementSelection(saved.targetPickerElements);
        appState.homeCombatFilter = ["", "attack", "tank", "speed", "balanced"].includes(saved.homeCombatFilter) ? saved.homeCombatFilter : "";
        appState.homeWorkFilter = WORKS.some(([value]) => value === saved.homeWorkFilter) ? saved.homeWorkFilter : "";
        appState.reverseSort = ["cost", "operations", "work", "combat", "number"].includes(saved.reverseSort) ? saved.reverseSort : "cost";
        appState.reversePinned = (saved.reversePinned || []).map(String).filter((key) => PD.pals[key]).slice(0, 3);
        appState.routeDensity = saved.routeDensity === "compact" ? "compact" : "comfortable";
        appState.routeHistory = Array.isArray(saved.routeHistory) ? saved.routeHistory.slice(0, 8) : [];
        appState.favoriteRoutes = Array.isArray(saved.favoriteRoutes) ? saved.favoriteRoutes.slice(0, 20) : [];
        appState.routeChecks = saved.routeChecks && typeof saved.routeChecks === "object" ? saved.routeChecks : {};
        appState.onboardingSeen = Boolean(saved.onboardingSeen);
        appState.dexVisibleCount = normalizeVisibleCount(saved.dexVisibleCount, 72);
        appState.reverseVisibleCount = normalizeVisibleCount(saved.reverseVisibleCount, REVERSE_PAGE_SIZE);
        appState.recipeVisibleCount = normalizeVisibleCount(saved.recipeVisibleCount, RECIPE_PAGE_SIZE);
        appState.targetPickerVisibleCount = normalizeVisibleCount(saved.targetPickerVisibleCount, TARGET_PICKER_PAGE_SIZE);
        appState.targetPickerScrollTop = normalizeScrollPosition(saved.targetPickerScrollTop);
        appState.viewScrollPositions = normalizeViewScrollPositions(saved.viewScrollPositions);
      } catch (_) {
        safeStorageRemove();
      }
    }
    try {
      const params = new URL(root.location.href).searchParams;
      const view = params.get("view");
      const target = params.get("target");
      const strategy = params.get("strategy");
      if (["planner", "reverse", "dex", "tools", "settings"].includes(view)) appState.activeView = view;
      if (target && PD.pals[target]) appState.target = palName(target);
      if (Object.values(PalSolver.STRATEGIES).includes(strategy)) appState.strategy = strategy;
    } catch (_) {
      // URL state is a convenience, never a launch blocker.
    }
    dexVisibleCount = appState.dexVisibleCount;
    reverseVisibleCount = appState.reverseVisibleCount;
    recipeVisibleCount = appState.recipeVisibleCount;
    targetPickerVisibleCount = appState.targetPickerVisibleCount;
  }

  function normalizeVisibleCount(value, fallback) {
    const count = Number(value);
    return Number.isFinite(count) && count >= fallback ? Math.floor(count) : fallback;
  }

  function normalizeScrollPosition(value) {
    const position = Number(value);
    return Number.isFinite(position) && position > 0 ? Math.floor(position) : 0;
  }

  function normalizeViewScrollPositions(value) {
    const positions = {};
    if (!value || typeof value !== "object") return positions;
    for (const view of ["planner", "reverse", "dex", "tools", "settings"]) {
      positions[view] = normalizeScrollPosition(value[view]);
    }
    return positions;
  }

  function cacheDataSignature() {
    const meta = PD.meta || {};
    return [meta.dataVersion || meta.data_version || "", meta.build || meta.buildId || meta.dataBuild || "", allKeys.length].join("|");
  }

  function ownedCacheSignature() {
    return `${appState.showCrossWorldGenes ? "genes:on" : "genes:off"}|${[...effectiveOwned.keys()].sort(comparePalKeys).join("|")}`;
  }

  function plannerCacheContext() {
    return JSON.stringify({
      data: cacheDataSignature(),
      owned: ownedCacheSignature(),
      target: resolveKey(appState.target),
      strategy: appState.strategy,
      requireOwned: appState.requireOwned,
      passives: appState.passives.trim(),
    });
  }

  function serializeRouteForCache(route) {
    return {
      ...route,
      operations: [...route.operations.entries()],
      produced: [...route.produced],
      replaceable: [...route.replaceable],
      extra: [...route.extra],
      owned: [...route.owned],
    };
  }

  function deserializeRouteFromCache(route) {
    if (!route || !PD.pals[route.target] || !Array.isArray(route.operations)) return null;
    return {
      ...route,
      operations: new Map(route.operations),
      produced: new Set(route.produced || []),
      replaceable: new Set(route.replaceable || []),
      extra: new Set(route.extra || []),
      owned: new Set(route.owned || []),
    };
  }

  function persistPlannerResultCache() {
    if (!currentRouteOptions.length || !currentPlan) return;
    const payload = {
      version: 1,
      context: plannerCacheContext(),
      selectedRouteOption,
      routes: currentRouteOptions.map(serializeRouteForCache),
    };
    safeStorageSet(JSON.stringify(payload), PLANNER_CACHE_KEY);
  }

  function restorePlannerResultCache() {
    const raw = safeStorageGet(PLANNER_CACHE_KEY);
    if (!raw) return false;
    try {
      const saved = JSON.parse(raw);
      if (saved.version !== 1 || saved.context !== plannerCacheContext() || !Array.isArray(saved.routes)) return false;
      const routes = saved.routes.map(deserializeRouteFromCache).filter(Boolean).slice(0, 4);
      if (!routes.length) return false;
      currentRouteOptions = routes;
      selectedRouteOption = Math.min(normalizeVisibleCount(saved.selectedRouteOption, 0), routes.length - 1);
      appState.plannerRan = true;
      renderPlan(routes[selectedRouteOption], 0, { focusResult: false, restored: true });
      byId("plannerStatus").textContent = "已立即恢复上次路线，条件变化时才会重新计算。";
      return true;
    } catch (_) {
      safeStorageRemove(PLANNER_CACHE_KEY);
      return false;
    }
  }

  function persistReverseResultCache(cacheKey, rows) {
    const payload = {
      version: 1,
      data: cacheDataSignature(),
      owned: cacheKey,
      rows: rows.map((route) => ({
        target: route.target,
        operationCount: routeOperationCount(route),
        extra: [...route.extra],
      })),
    };
    safeStorageSet(JSON.stringify(payload), REVERSE_CACHE_KEY);
  }

  function restoreReverseResultCache(cacheKey) {
    const raw = safeStorageGet(REVERSE_CACHE_KEY);
    if (!raw) return null;
    try {
      const saved = JSON.parse(raw);
      if (saved.version !== 1 || saved.data !== cacheDataSignature() || saved.owned !== cacheKey || !Array.isArray(saved.rows)) return null;
      return saved.rows.filter((route) => route && PD.pals[route.target]).map((route) => ({
        target: route.target,
        operationCount: Number(route.operationCount) || 0,
        operations: new Map(),
        extra: new Set((route.extra || []).filter((key) => PD.pals[key])),
        owned: new Set(effectiveOwned.keys()),
      }));
    } catch (_) {
      safeStorageRemove(REVERSE_CACHE_KEY);
      return null;
    }
  }

  function clearResultCaches() {
    safeStorageRemove(PLANNER_CACHE_KEY);
    safeStorageRemove(REVERSE_CACHE_KEY);
  }

  function routeOperationCount(route) {
    return Number.isFinite(route && route.operationCount) ? route.operationCount : route && route.operations ? route.operations.size : 0;
  }

  function normalizeCount(value) {
    const number = Number(value);
    return Number.isFinite(number) && number > 0 ? Math.floor(number) : null;
  }

  function normalizeIndividual(raw, key, index, source) {
    const input = raw && typeof raw === "object" ? raw : {};
    const rawGender = String(input.gender || "").toLowerCase();
    const gender = ["male", "female"].includes(rawGender) ? rawGender : "unknown";
    const level = Number(input.level);
    const rank = Number(input.rank);
    const talents = input.talents && typeof input.talents === "object" ? input.talents : {};
    return {
      id: String(input.id || `${source}-${key}-${index + 1}`),
      key,
      source: String(input.source || source),
      gender,
      level: Number.isFinite(level) && level > 0 ? Math.floor(level) : null,
      rank: Number.isFinite(rank) && rank >= 0 ? Math.floor(rank) : null,
      passives: Array.isArray(input.passives)
        ? input.passives.map(String).filter(Boolean)
        : String(input.passives || "").split(/[、,，;；]/).map((value) => value.trim()).filter(Boolean),
      talents: {
        hp: normalizeTalent(talents.hp),
        attack: normalizeTalent(talents.attack),
        defense: normalizeTalent(talents.defense),
      },
    };
  }

  function normalizeTalent(value) {
    const number = Number(value);
    return Number.isFinite(number) && number >= 0 ? Math.floor(number) : null;
  }

  function refreshInventoryRecord(record) {
    record.individuals = Array.isArray(record.individuals) ? record.individuals : [];
    record.untrackedCount = Math.max(0, Math.floor(Number(record.untrackedCount) || 0));
    record.count = record.individuals.length + record.untrackedCount || null;
    record.male = record.individuals.filter((item) => item.gender === "male").length;
    record.female = record.individuals.filter((item) => item.gender === "female").length;
    const explicitUnknown = record.individuals.filter((item) => item.gender === "unknown").length;
    record.unknownGender = explicitUnknown + record.untrackedCount;
    return record;
  }

  function normalizeInventoryRecord(raw, fallbackSource = "local") {
    const input = raw && typeof raw === "object" ? raw : { key: raw };
    const key = String(input.key || "");
    const source = String(input.source || fallbackSource);
    const individuals = Array.isArray(input.individuals)
      ? input.individuals.map((item, index) => normalizeIndividual(item, key, index, source))
      : [];
    const count = normalizeCount(input.count) || individuals.length || null;
    const suppliedUntracked = Number(input.untrackedCount);
    const untrackedCount = Number.isFinite(suppliedUntracked)
      ? Math.max(0, Math.floor(suppliedUntracked))
      : Math.max(0, (count || 0) - individuals.length);
    return refreshInventoryRecord({
      key,
      source,
      world: normalizeCount(input.world) || 0,
      box: normalizeCount(input.box) || 0,
      individuals,
      untrackedCount,
      crossWorldOnly: Boolean(input.crossWorldOnly),
      crossWorldCount: normalizeCount(input.crossWorldCount) || 0,
    });
  }

  function rebuildEffectiveInventory() {
    const rows = PalSolver.combineInventoryRecords(
      [...appState.owned.values()],
      [...crossWorldGenes.values()],
      appState.showCrossWorldGenes,
    );
    effectiveOwned = new Map(rows.map((record) => [record.key, record]));
  }

  function createManualIndividual(key, index = 0) {
    return normalizeIndividual({
      id: `manual-${key}-${Date.now()}-${index}`,
      source: "manual",
    }, key, index, "manual");
  }

  function applyInjectedInventory() {
    const hasInventory = Array.isArray(root.__SAVE_INVENTORY__);
    const hasOwnedKeys = Array.isArray(root.__SAVE_OWNED__);
    const hasCrossWorldGenes = Array.isArray(root.__CROSS_WORLD_GENES__);
    const inventory = hasInventory ? root.__SAVE_INVENTORY__ : [];
    const injected = hasOwnedKeys ? root.__SAVE_OWNED__ : [];
    const injectedGenes = hasCrossWorldGenes ? root.__CROSS_WORLD_GENES__ : [];
    if (!hasInventory && !hasOwnedKeys && !hasCrossWorldGenes) {
      rebuildEffectiveInventory();
      return;
    }
    let loaded = 0;
    let unknown = 0;
    const rows = inventory.length ? inventory : injected.map((key) => ({ key, source: "save" }));
    const incomingKeys = new Set(rows.map((item) => String(item && typeof item === "object" ? item.key : item)));
    let removed = 0;
    for (const [key, record] of appState.owned) {
      if (record.source === "save" && !incomingKeys.has(key)) {
        appState.owned.delete(key);
        removed += 1;
      }
    }
    for (const raw of rows) {
      const record = normalizeInventoryRecord(raw, "save");
      const key = record.key;
      if (!PD.pals[key]) {
        unknown += 1;
        continue;
      }
      appState.owned.set(key, record);
      loaded += 1;
    }

    crossWorldGenes = new Map();
    let geneUnknown = 0;
    for (const raw of injectedGenes) {
      const record = normalizeInventoryRecord(raw, "cross-world");
      if (!PD.pals[record.key]) {
        geneUnknown += 1;
        continue;
      }
      record.source = "cross-world";
      record.crossWorldOnly = true;
      record.crossWorldCount = record.count || 0;
      crossWorldGenes.set(record.key, record);
    }
    appState.showCrossWorldGenes = false;
    rebuildEffectiveInventory();

    const individualCount = [...appState.owned.values()]
      .filter((record) => record.source === "save")
      .reduce((sum, record) => sum + record.individuals.length, 0);
    const geneCount = [...crossWorldGenes.values()]
      .reduce((sum, record) => sum + (record.count || 0), 0);
    const message = `已载入本世界 ${loaded} 种${individualCount ? `、${individualCount} 个个体` : ""}${removed ? `，移除 ${removed} 种旧存档记录` : ""}${unknown ? `，${unknown} 种未识别` : ""}${geneCount ? `；跨界基因 ${geneCount} 条（默认隐藏）` : ""}${geneUnknown ? `，另跳过 ${geneUnknown} 种未知基因` : ""}`;
    setTimeout(() => showToast(message), 0);
    persistState();
  }

  function persistState() {
    const data = {
      version: 6,
      owned: [...appState.owned.values()],
      favorites: [...appState.favorites],
      recent: appState.recent,
      target: appState.target,
      passives: appState.passives,
      strategy: appState.strategy,
      requireOwned: appState.requireOwned,
      activeView: appState.activeView,
      inventorySearch: appState.inventorySearch,
      inventoryOpen: appState.inventoryOpen,
      advancedOpen: appState.advancedOpen,
      dexSearch: appState.dexSearch,
      dexWork: appState.dexWork,
      dexOwnOnly: appState.dexOwnOnly,
      dexFavoriteOnly: appState.dexFavoriteOnly,
      dexElements: [...selectedDexElements],
      dexWorkLevel: appState.dexWorkLevel,
      dexCombatRole: appState.dexCombatRole,
      dexAcquisition: appState.dexAcquisition,
      dexSort: appState.dexSort,
      reverseOnly5: appState.reverseOnly5,
      reverseWork: appState.reverseWork,
      reverseMaxExtra: appState.reverseMaxExtra,
      reverseElements: [...selectedReverseElements],
      parentA: appState.parentA,
      parentB: appState.parentB,
      recipeTarget: appState.recipeTarget,
      recipesOwnedFirst: appState.recipesOwnedFirst,
      plannerRan: appState.plannerRan,
      reverseRan: appState.reverseRan,
      childLookupRan: appState.childLookupRan,
      recipeLookupRan: appState.recipeLookupRan,
      targetRecommendationMode: appState.targetRecommendationMode,
      targetPickerMode: appState.targetPickerMode,
      targetPickerSearch: appState.targetPickerSearch,
      targetPickerElements: [...selectedTargetElements],
      homeCombatFilter: appState.homeCombatFilter,
      homeWorkFilter: appState.homeWorkFilter,
      reverseSort: appState.reverseSort,
      reversePinned: appState.reversePinned,
      routeDensity: appState.routeDensity,
      routeHistory: appState.routeHistory,
      favoriteRoutes: appState.favoriteRoutes,
      routeChecks: appState.routeChecks,
      onboardingSeen: appState.onboardingSeen,
      dexVisibleCount,
      reverseVisibleCount,
      recipeVisibleCount,
      targetPickerVisibleCount,
      targetPickerScrollTop: appState.targetPickerScrollTop,
      viewScrollPositions: appState.viewScrollPositions,
    };
    safeStorageSet(JSON.stringify(data));
    updateUrlState();
  }

  function schedulePersistState() {
    if (persistTimer) root.clearTimeout(persistTimer);
    persistTimer = root.setTimeout(() => {
      persistTimer = null;
      persistState();
    }, 180);
  }

  function scheduleDexRender() {
    if (dexRenderTimer) root.clearTimeout(dexRenderTimer);
    dexRenderTimer = root.setTimeout(() => {
      dexRenderTimer = null;
      renderDex();
    }, 90);
  }

  function runSolverWorker(kind, payload) {
    if (!("Worker" in root)) return Promise.reject(new Error("Worker unavailable"));
    if (!solverWorker) {
      solverWorker = new Worker("solver-worker.js");
      solverWorker.addEventListener("message", (event) => {
        const request = solverRequests.get(event.data && event.data.id);
        if (!request) return;
        solverRequests.delete(event.data.id);
        if (event.data.error) request.reject(new Error(event.data.error));
        else request.resolve(event.data.result);
      });
      solverWorker.addEventListener("error", () => {
        for (const request of solverRequests.values()) request.reject(new Error("Worker failed"));
        solverRequests.clear();
        solverWorker?.terminate();
        solverWorker = null;
      });
    }
    const id = ++solverRequestId;
    return new Promise((resolve, reject) => {
      solverRequests.set(id, { resolve, reject });
      solverWorker.postMessage({ id, kind, payload });
    });
  }

  async function solveOptionsCooperatively(payload) {
    await new Promise((resolve) => root.setTimeout(resolve, 0));
    return PalSolver.solveRoutes({
      pd: PD,
      owned: new Set(payload.owned || []),
      target: payload.target,
      strategy: payload.strategy,
      requireOwned: payload.requireOwned,
      limit: 2,
    }) || [];
  }

  function updateUrlState() {
    try {
      const url = new URL(root.location.href);
      url.searchParams.set("view", appState.activeView);
      const target = resolveKey(appState.target);
      if (target) url.searchParams.set("target", target);
      else url.searchParams.delete("target");
      url.searchParams.set("strategy", appState.strategy);
      root.history.replaceState(null, "", url.href);
    } catch (_) {
      // history.replaceState can be restricted on some file:// launches.
    }
  }

  function syncControlsFromState() {
    byId("targetInput").value = appState.target;
    byId("passives").value = appState.passives;
    byId("requireOwned").checked = appState.requireOwned;
    const radio = [...document.querySelectorAll('input[name="strategy"]')].find((item) => item.value === appState.strategy);
    if (radio) radio.checked = true;
    byId("inventorySearch").value = appState.inventorySearch;
    byId("inventoryDetails").open = appState.inventoryOpen;
    byId("advancedDetails").open = appState.advancedOpen;
    byId("dexSearch").value = appState.dexSearch;
    byId("dexWork").value = appState.dexWork;
    byId("dexOwnOnly").checked = appState.dexOwnOnly;
    byId("dexFavoriteOnly").checked = appState.dexFavoriteOnly;
    byId("dexWorkLevel").value = appState.dexWorkLevel;
    byId("dexCombatRole").value = appState.dexCombatRole;
    byId("dexAcquisition").value = appState.dexAcquisition;
    byId("dexSort").value = appState.dexSort;
    selectedDexElements = new Set(elementsAvailable ? appState.dexElements : []);
    byId("only5").checked = appState.reverseOnly5;
    byId("reverseWork").value = appState.reverseWork;
    byId("reverseMaxExtra").value = appState.reverseMaxExtra;
    selectedReverseElements = new Set(elementsAvailable ? appState.reverseElements : []);
    byId("parentAInput").value = appState.parentA;
    byId("parentBInput").value = appState.parentB;
    byId("recipeTargetInput").value = appState.recipeTarget || appState.target;
    byId("recipesOwnedFirst").checked = appState.recipesOwnedFirst;
    byId("targetPickerSearch").value = appState.targetPickerSearch;
    byId("homeCombatFilter").value = appState.homeCombatFilter;
    byId("homeWorkFilter").value = appState.homeWorkFilter;
    byId("reverseSort").value = appState.reverseSort;
    selectedTargetElements = new Set(elementsAvailable ? appState.targetPickerElements : []);
    renderPlannerTargetSummary();
    applyRouteDensity();
    updateStrategyHint();
  }

  function restoreDerivedResults() {
    derivedResultsReady = true;
    root.setTimeout(() => {
      restoreResultsForView(appState.activeView);
    }, 0);
  }

  function restoreResultsForView(view) {
    if (view === "planner" && appState.plannerRan && resolveKey(appState.target) && !currentPlan && byId("solve").getAttribute("aria-busy") !== "true") {
      if (!restorePlannerResultCache()) solvePlanner({ focusResult: false });
    }
    if (view === "reverse" && appState.reverseRan && effectiveOwned.size && !reverseHasRun) scheduleReverseRun();
    if (view === "tools") {
      if (appState.childLookupRan && resolveKey(appState.parentA) && resolveKey(appState.parentB)) lookupChild();
      if (appState.recipeLookupRan && resolveKey(appState.recipeTarget || appState.target) && !recipeRowsCache.length) lookupRecipes({ preserveVisible: true });
    }
    restoreActiveViewScroll(view);
  }

  function renderDataStatus() {
    const meta = PD.meta || {};
    const count = allKeys.length;
    const gameVersion = meta.gameVersion || meta.game_version || meta.version || "1.0";
    const build = meta.build || meta.buildId || meta.dataBuild || meta.data_build || "待核验";
    const expected = Number(meta.officialPalCount || meta.expectedPalCount || meta.expected_pal_count || EXPECTED_PAL_COUNT);
    const fieldStatus = meta.fieldStatus || meta.field_status || {};
    let sources = normalizeSources(meta.sources || meta.source || []);
    const pakVerified = Boolean(meta.sourceCommit)
      && String(fieldStatus.names || "").includes("current-pak-export")
      && String(fieldStatus.breedingMatrix || fieldStatus.breeding_matrix || "").includes("current-pak-export");
    const verified = meta.verified === true || String(meta.sourceStatus || meta.source_status || "").toLowerCase() === "verified" || pakVerified;
    if (!sources.length && meta.sourceCommit) {
      sources = [{ name: "当前 1.0 PAK 导出快照", note: `固定来源提交 ${meta.sourceCommit}` }];
    }
    byId("buildBadge").textContent = `${gameVersion} · Build ${build}`;
    byId("palCountBadge").textContent = `${count} / ${expected}`;
    const sourceBadge = byId("sourceBadge");
    sourceBadge.textContent = verified ? "1.0 数据已核验" : sources.length ? "来源已声明" : "来源元数据待核验";
    sourceBadge.className = `status-pill ${verified ? "status-ok" : "status-pending"}`;

    const pairCount = Object.values(PD.breed).reduce((sum, rows) => sum + (Array.isArray(rows) ? rows.length : 0), 0);
    byId("dataDetails").innerHTML = [
      ["游戏版本", gameVersion],
      ["数据 Build", build],
      ["数据版本", meta.dataVersion || meta.data_version || "未注明"],
      ["帕鲁数量", `${count} / ${expected}`],
      ["配方记录", pairCount.toLocaleString("zh-CN")],
      ["基础工作上限", "8（可强化至 10）"],
      ["元素字段", elementsAvailable ? "已包含" : "当前数据包未包含已验证元素字段"],
      ["来源提交", meta.sourceCommit || meta.source_commit || "未注明"],
      ["更新时间", meta.updatedAt || meta.updated_at || "数据文件未注明"],
      ["校验状态", verified ? "已核验" : "等待数据元信息确认"],
    ].map(([key, value]) => `<dt>${escapeHtml(key)}</dt><dd>${escapeHtml(value)}</dd>`).join("");
    byId("sourceList").innerHTML = sources.length
      ? sources.map((source) => `<div class="source-item"><strong>${escapeHtml(source.name)}</strong>${source.note ? `<div>${escapeHtml(source.note)}</div>` : ""}</div>`).join("")
      : '<div class="source-item">当前数据文件没有附带来源清单。界面不会自行宣称已完成权威校验。</div>';
  }

  function normalizeSources(raw) {
    const values = Array.isArray(raw) ? raw : raw ? [raw] : [];
    return values.map((item) => {
      if (typeof item === "string") return { name: item, note: "" };
      return { name: item.name || item.label || item.url || "未命名来源", note: item.note || item.description || item.url || "" };
    });
  }

  function bindNavigation() {
    const tabs = [...document.querySelectorAll(".nav-tab")];
    for (const tab of tabs) {
      tab.addEventListener("click", () => activateView(tab.dataset.view, { focus: true }));
      tab.addEventListener("keydown", (event) => {
        if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
        event.preventDefault();
        let index = tabs.indexOf(tab);
        if (event.key === "ArrowRight") index = (index + 1) % tabs.length;
        if (event.key === "ArrowLeft") index = (index - 1 + tabs.length) % tabs.length;
        if (event.key === "Home") index = 0;
        if (event.key === "End") index = tabs.length - 1;
        tabs[index].focus();
        activateView(tabs[index].dataset.view, { focus: false });
      });
    }
  }

  function activateView(name, options = {}) {
    const valid = ["planner", "reverse", "dex", "tools", "settings"].includes(name) ? name : "planner";
    const requestedPanel = byId(`view-${valid}`);
    const entering = appState.activeView !== valid || Boolean(requestedPanel && requestedPanel.hidden);
    if (entering) rememberActiveViewScroll();
    for (const tab of document.querySelectorAll(".nav-tab")) {
      const active = tab.dataset.view === valid;
      tab.classList.toggle("is-active", active);
      tab.setAttribute("aria-selected", String(active));
      tab.tabIndex = active ? 0 : -1;
    }
    for (const panel of document.querySelectorAll("[data-view-panel]")) {
      const active = panel.dataset.viewPanel === valid;
      panel.hidden = !active;
      panel.classList.toggle("is-active", active);
    }
    appState.activeView = valid;
    if (valid === "dex" && (dexDirty || !dexRowsCache.length)) renderDex({ preserveVisible: !dexRowsCache.length });
    if (derivedResultsReady && entering) root.setTimeout(() => restoreResultsForView(valid), 0);
    else if (entering) restoreActiveViewScroll(valid);
    updateMobileActionBar();
    if (options.persist !== false) schedulePersistState();
    if (options.focus) {
      const panel = byId(`view-${valid}`);
      panel.tabIndex = -1;
      panel.focus({ preventScroll: true });
    }
  }

  function rememberActiveViewScroll() {
    if (!["planner", "reverse", "dex", "tools", "settings"].includes(appState.activeView)) return;
    const panel = byId(`view-${appState.activeView}`);
    if (!panel || panel.hidden) return;
    appState.viewScrollPositions[appState.activeView] = normalizeScrollPosition(root.scrollY);
  }

  function rememberOpenDialogState() {
    const dialog = byId("targetPickerDialog");
    if (dialog && dialog.open) appState.targetPickerScrollTop = normalizeScrollPosition(dialog.scrollTop);
  }

  function restoreActiveViewScroll(view = appState.activeView) {
    if (view !== appState.activeView) return;
    const top = normalizeScrollPosition(appState.viewScrollPositions[view]);
    root.requestAnimationFrame(() => root.requestAnimationFrame(() => {
      if (view === appState.activeView) root.scrollTo({ top, left: 0, behavior: "auto" });
    }));
  }

  function scheduleScrollMemory() {
    if (scrollMemoryTimer) root.clearTimeout(scrollMemoryTimer);
    scrollMemoryTimer = root.setTimeout(() => {
      scrollMemoryTimer = null;
      rememberActiveViewScroll();
    }, 180);
  }

  function bindInventory() {
    byId("addOwn").addEventListener("click", addOwnedFromInput);
    byId("ownInput").addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        addOwnedFromInput();
      }
    });
    byId("inventorySearch").addEventListener("input", () => {
      appState.inventorySearch = byId("inventorySearch").value;
      renderInventory();
      schedulePersistState();
    });
    byId("inventoryDetails").addEventListener("toggle", () => {
      appState.inventoryOpen = byId("inventoryDetails").open;
      schedulePersistState();
    });
    byId("advancedDetails").addEventListener("toggle", () => {
      appState.advancedOpen = byId("advancedDetails").open;
      schedulePersistState();
    });
    byId("inventoryList").addEventListener("click", (event) => {
      const manageButton = event.target.closest("[data-manage-individuals]");
      if (manageButton) {
        openInventoryPalDialog(manageButton.dataset.manageIndividuals);
        return;
      }
      const button = event.target.closest("[data-remove-own]");
      if (!button) return;
      const key = button.dataset.removeOwn;
      const previous = normalizeInventoryRecord(JSON.parse(JSON.stringify(appState.owned.get(key))), "local");
      appState.owned.delete(key);
      inventoryChanged(`${palName(key)}已从库存移除`);
      offerUndo("已移除，可撤销", () => {
        appState.owned.set(key, previous);
        inventoryChanged(`${palName(key)}已恢复`);
      });
    });
    byId("clearOwn").addEventListener("click", () => {
      if (!appState.owned.size) return;
      if (!root.confirm("确定清空当前库存吗？可通过导入文件或重新读取存档恢复。")) return;
      const previous = [...appState.owned.values()].map((record) => JSON.parse(JSON.stringify(record)));
      appState.owned.clear();
      inventoryChanged("库存已清空");
      offerUndo("库存已清空，可撤销", () => {
        for (const record of previous) appState.owned.set(record.key, normalizeInventoryRecord(record, "local"));
        inventoryChanged("库存已恢复");
      });
    });
    byId("importInventory").addEventListener("click", () => openInventoryFile("inventory"));
    const dialog = byId("inventoryPalDialog");
    byId("closeInventoryPalDialog").addEventListener("click", () => dialog.close());
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dialog.close();
    });
    byId("inventoryPalDialogBody").addEventListener("click", handleInventoryDialogClick);
    byId("inventoryPalDialogBody").addEventListener("change", handleInventoryDialogChange);
  }

  function addOwnedFromInput() {
    const input = byId("ownInput");
    const detail = resolveKeyDetailed(input.value);
    const error = byId("ownError");
    error.textContent = "";
    if (!detail.key) {
      error.textContent = detail.ambiguous.length
        ? `名称不唯一，请从候选中选一个：${detail.ambiguous.map(palName).join("、")}`
        : `找不到“${input.value.trim() || "空名称"}”`;
      input.setAttribute("aria-invalid", "true");
      return;
    }
    input.removeAttribute("aria-invalid");
    if (appState.owned.has(detail.key)) {
      error.textContent = `${palName(detail.key)}已在库存中`;
      return;
    }
    appState.owned.set(detail.key, normalizeInventoryRecord({
      key: detail.key,
      count: 1,
      source: "manual",
      individuals: [createManualIndividual(detail.key)],
    }, "manual"));
    input.value = "";
    input.focus();
    inventoryChanged(`${palName(detail.key)}已加入库存`);
  }

  function inventoryChanged(message) {
    rebuildEffectiveInventory();
    const refreshPlanner = Boolean(currentPlan || appState.plannerRan || plannerSolveTimer);
    reverseGeneration += 1;
    reverseRouteCache = { key: "", rows: null };
    clearResultCaches();
    renderCrossWorldToggle();
    renderInventory();
    dexDirty = true;
    if (appState.activeView === "dex") renderDex();
    markPlannerDirty(refreshPlanner ? "库存发生变化，正在刷新路线。" : "库存已经更新，请在选定目标后生成路线。", true);
    persistState();
    if (refreshPlanner) schedulePlannerSolve(120);
    if (appState.reverseRan || reverseHasRun) scheduleReverseRun();
    if (message) showToast(message);
  }

  function renderInventory() {
    const summary = byId("inventorySummary");
    const knownCount = [...effectiveOwned.values()].reduce((sum, item) => sum + (item.count || 0), 0);
    const hasUnknown = [...effectiveOwned.values()].some((item) => !item.count);
    summary.textContent = effectiveOwned.size
      ? `${effectiveOwned.size} 种${knownCount && !hasUnknown ? ` · ${knownCount} 只` : ""}${appState.showCrossWorldGenes ? " · 含跨界基因" : ""}`
      : "尚未添加帕鲁";
    renderInventorySourceSummary();
    const query = byId("inventorySearch").value.trim().toLowerCase();
    const rows = [...effectiveOwned.keys()]
      .filter((key) => !query || palSearchText(key).includes(query))
      .sort(comparePalKeys);
    byId("inventoryList").innerHTML = rows.length
      ? rows.map((key) => {
        const record = effectiveOwned.get(key);
        const sourceLabel = record.crossWorldOnly
          ? '<span class="inventory-source-tag">跨界基因</span>'
          : record.crossWorldCount
            ? `<span class="inventory-source-tag">另含跨界 ${record.crossWorldCount}</span>`
            : "";
        return `<div class="inventory-item">
          ${palImage(key) ? `<img src="${escapeHtml(palImage(key))}" alt="" loading="lazy" decoding="async">` : "<span></span>"}
          <button class="inventory-name inventory-manage" type="button" data-manage-individuals="${escapeHtml(key)}" aria-label="${record.crossWorldOnly ? "查看" : "管理"}${escapeHtml(palName(key))}个体">
            <strong>${escapeHtml(palName(key))}</strong>
            <small>#${escapeHtml(palNumber(key))}${record.count ? ` · ${record.count} 只` : " · 数量未记录"}${sourceLabel}</small>
            ${inventoryGenderSummary(record)}
          </button>
          ${record.crossWorldOnly
            ? '<span class="inventory-readonly" title="跨界基因来自只读存档">只读</span>'
            : `<button class="remove-own" type="button" data-remove-own="${escapeHtml(key)}" aria-label="从库存移除${escapeHtml(palName(key))}">移除</button>`}
        </div>`;
      }).join("")
      : `<div class="field-hint">${effectiveOwned.size ? "没有符合筛选的库存帕鲁" : "可手动添加、导入 JSON，或由桌面程序自动读取存档。"}</div>`;
    renderReverseInventoryBanner();
  }

  function inventoryGenderSummary(record) {
    if (!record.count) return '<span class="inventory-genders">点此补充个体资料</span>';
    const parts = [];
    if (record.male) parts.push(`雄 ${record.male}`);
    if (record.female) parts.push(`雌 ${record.female}`);
    if (record.unknownGender) parts.push(`未注明 ${record.unknownGender}`);
    return `<span class="inventory-genders">${escapeHtml(parts.join(" · ") || "性别未记录")}</span>`;
  }

  function renderInventorySourceSummary() {
    const container = byId("inventorySourceSummary");
    const meta = root.__SAVE_META__;
    if (!meta || typeof meta !== "object") {
      container.hidden = true;
      container.textContent = "";
      return;
    }
    const rawCounts = meta.rawCounts || {};
    const parts = [meta.deployment === "server"
      ? "当前库存来自自托管服务器读取的最新存档"
      : "当前库存来自桌面程序读取的本世界存档"];
    const individualCount = rawCounts.ownedIndividuals ?? rawCounts.worldIndividuals;
    const worldCount = rawCounts.ownedWorld ?? rawCounts.world;
    const geneCount = rawCounts.crossWorldGenes ?? rawCounts.ownedBox ?? 0;
    if (individualCount) parts.push(`${individualCount} 个正式帕鲁个体`);
    if (worldCount) parts.push(`本世界 ${worldCount}`);
    if (geneCount) parts.push(`跨界基因 ${geneCount} 条${appState.showCrossWorldGenes ? "（已显示）" : "（默认隐藏）"}`);
    container.textContent = parts.join(" · ");
    container.hidden = false;
  }

  function bindServerSaveControl() {
    const meta = root.__SAVE_META__;
    const button = byId("serverSaveControl");
    const label = byId("serverSaveStatusText");
    if (!button || !label || !meta || meta.deployment !== "server") return;
    button.hidden = false;
    const onboardingCopy = document.querySelector("#onboardingDialog .onboarding-steps li:nth-child(2) span");
    if (onboardingCopy) onboardingCopy.textContent = "服务器会只读载入最新存档，也可随时手动刷新。";
    let requested = false;
    let pollingTimer = null;
    const loadedSignature = String(meta.signature || "");

    function shortTime(value) {
      if (!value) return "时间未知";
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return "时间未知";
      return new Intl.DateTimeFormat("zh-CN", {
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      }).format(date);
    }

    function applyStatus(status) {
      const busy = Boolean(status.busy);
      const error = String(status.lastError || "");
      button.disabled = busy;
      button.classList.toggle("is-busy", busy);
      button.classList.toggle("is-error", Boolean(error));
      if (busy) label.textContent = "正在读取…";
      else if (error) label.textContent = "读取失败";
      else if (!status.fresh) label.textContent = "发现新存档";
      else label.textContent = shortTime(status.publishedSaveModifiedAt || status.sourceModifiedAt);
      button.title = error
        ? `上次读取失败：${error}。点击重试。`
        : `当前页面：${shortTime(meta.saveModifiedAt)}；服务器：${shortTime(status.sourceModifiedAt)}。点击读取最新存档。`;
    }

    async function statusRequest() {
      const response = await fetch("/api/breed/status", {
        credentials: "same-origin",
        cache: "no-store",
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error || "无法读取服务器存档状态");
      return payload.data || {};
    }

    async function startRefresh() {
      requested = true;
      button.disabled = true;
      button.classList.add("is-busy");
      button.classList.remove("is-error");
      label.textContent = "正在读取…";
      const response = await fetch("/api/breed/refresh", {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        headers: {
          "Content-Type": "application/json",
          "X-Palworld-Panel": "1",
        },
        body: "{}",
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error || "无法启动存档读取");
      schedulePoll(700);
    }

    async function poll({ auto = false } = {}) {
      try {
        const status = await statusRequest();
        applyStatus(status);
        const published = String(status.publishedSignature || "");
        if (published && published !== loadedSignature && !status.busy) {
          root.location.reload();
          return;
        }
        if (status.busy) {
          schedulePoll(900);
          return;
        }
        if (requested) {
          requested = false;
          if (status.lastError) showToast(`服务器存档读取失败：${status.lastError}`);
          else if (status.fresh) showToast("当前页面已经是服务器最新存档");
          return;
        }
        if (auto && !status.fresh && !status.lastError) await startRefresh();
      } catch (error) {
        requested = false;
        button.disabled = false;
        button.classList.remove("is-busy");
        button.classList.add("is-error");
        label.textContent = "状态异常";
        button.title = error.message || "无法连接服务器存档服务";
        showToast(`服务器存档状态异常：${error.message || "连接失败"}`);
      }
    }

    function schedulePoll(delay) {
      if (pollingTimer) root.clearTimeout(pollingTimer);
      pollingTimer = root.setTimeout(() => poll(), delay);
    }

    button.addEventListener("click", () => {
      if (!button.disabled) startRefresh().catch((error) => {
        requested = false;
        button.disabled = false;
        button.classList.remove("is-busy");
        button.classList.add("is-error");
        label.textContent = "读取失败";
        showToast(`无法读取最新存档：${error.message || "请求失败"}`);
      });
    });
    poll({ auto: true });
  }

  function openInventoryPalDialog(key) {
    if (!effectiveOwned.has(key)) return;
    const dialog = byId("inventoryPalDialog");
    dialog.dataset.key = key;
    const readOnly = !appState.owned.has(key);
    dialog.dataset.readOnly = String(readOnly);
    byId("inventoryPalDialogTitle").textContent = `${readOnly ? "查看跨界基因" : "管理"} ${palName(key)}`;
    renderInventoryPalDialog();
    dialog.showModal();
  }

  function renderInventoryPalDialog() {
    const dialog = byId("inventoryPalDialog");
    const key = dialog.dataset.key;
    const record = appState.owned.get(key) || crossWorldGenes.get(key);
    if (!record) {
      dialog.close();
      return;
    }
    const readOnly = dialog.dataset.readOnly === "true";
    const extraGeneCount = !readOnly && appState.showCrossWorldGenes
      ? crossWorldGenes.get(key)?.count || 0
      : 0;
    const rows = record.individuals.map((item, index) => `
      <article class="inventory-individual" data-individual-id="${escapeHtml(item.id)}">
        <div class="individual-heading"><strong>${readOnly ? "基因" : "个体"} ${index + 1}</strong>${readOnly ? '<span class="inventory-readonly">只读</span>' : `<button class="button quiet danger-text" type="button" data-remove-individual="${escapeHtml(item.id)}">删除</button>`}</div>
        <div class="individual-fields">
          <label>性别<select data-individual-field="gender"${readOnly ? " disabled" : ""}><option value="unknown"${item.gender === "unknown" ? " selected" : ""}>未注明</option><option value="male"${item.gender === "male" ? " selected" : ""}>雄性</option><option value="female"${item.gender === "female" ? " selected" : ""}>雌性</option></select></label>
          <label>等级<input type="number" min="1" max="100" inputmode="numeric" value="${item.level || ""}" placeholder="未记录" data-individual-field="level"${readOnly ? " disabled" : ""}></label>
          <label class="individual-passives">被动词条<input type="text" value="${escapeHtml(item.passives.join("、"))}" placeholder="用顿号或逗号分隔" data-individual-field="passives"${readOnly ? " disabled" : ""}></label>
        </div>
      </article>`).join("");
    byId("inventoryPalDialogBody").innerHTML = `
      ${readOnly ? '<p class="field-hint">这是跨界帕鲁终端中的只读基因记录，不是本世界现有个体。</p>' : extraGeneCount ? `<p class="field-hint">另有 ${extraGeneCount} 条同种跨界基因已临时纳入规划；这里只编辑本世界个体。</p>` : ""}
      <div class="inventory-pal-overview">
        ${palImage(key) ? `<img src="${escapeHtml(palImage(key))}" alt="">` : ""}
        <div><strong>${escapeHtml(palName(key))} · ${record.count || 0} 只</strong>${inventoryGenderSummary(record)}<small>${record.individuals.length === record.count ? "个体资料已完整记录" : `还有 ${(record.count || 0) - record.individuals.length} 只仅记录了数量`}</small></div>
        ${readOnly ? "" : '<button class="button secondary" type="button" data-add-individual>新增个体</button>'}
      </div>
      <div class="inventory-individual-list">${rows || `<p class="field-hint">${readOnly ? "没有可显示的个体字段。" : "还没有个体资料，点击“新增个体”开始记录。"}</p>`}</div>`;
  }

  function handleInventoryDialogClick(event) {
    const dialog = byId("inventoryPalDialog");
    const key = dialog.dataset.key;
    const record = appState.owned.get(key);
    if (!record) return;
    if (event.target.closest("[data-add-individual]")) {
      const wasUntracked = record.untrackedCount > 0;
      if (wasUntracked) record.untrackedCount -= 1;
      record.individuals.push(createManualIndividual(key, record.individuals.length));
      refreshInventoryRecord(record);
      inventoryChanged(`${palName(key)}已${wasUntracked ? "补充" : "新增"} 1 个个体资料`);
      renderInventoryPalDialog();
      return;
    }
    const removeButton = event.target.closest("[data-remove-individual]");
    if (!removeButton) return;
    const index = record.individuals.findIndex((item) => item.id === removeButton.dataset.removeIndividual);
    if (index < 0) return;
    const removedIndividual = record.individuals[index];
    record.individuals.splice(index, 1);
    refreshInventoryRecord(record);
    if (!record.count) {
      appState.owned.delete(key);
      dialog.close();
    } else {
      renderInventoryPalDialog();
    }
    inventoryChanged(`${palName(key)}已删除 1 个个体`);
    offerUndo("个体已删除，可撤销", () => {
      const restored = appState.owned.get(key) || normalizeInventoryRecord({ key, source: "manual" }, "manual");
      restored.individuals.splice(index, 0, removedIndividual);
      refreshInventoryRecord(restored);
      appState.owned.set(key, restored);
      inventoryChanged(`${palName(key)}的个体已恢复`);
    });
  }

  function handleInventoryDialogChange(event) {
    const field = event.target.closest("[data-individual-field]");
    const row = event.target.closest("[data-individual-id]");
    if (!field || !row) return;
    const key = byId("inventoryPalDialog").dataset.key;
    const record = appState.owned.get(key);
    const individual = record && record.individuals.find((item) => item.id === row.dataset.individualId);
    if (!individual) return;
    if (field.dataset.individualField === "gender") individual.gender = field.value;
    if (field.dataset.individualField === "level") individual.level = normalizeCount(field.value);
    if (field.dataset.individualField === "passives") {
      individual.passives = field.value.split(/[、,，;；]/).map((value) => value.trim()).filter(Boolean);
    }
    refreshInventoryRecord(record);
    inventoryChanged(`${palName(key)}的个体资料已更新`);
    renderInventoryPalDialog();
  }

  function bindPlanner() {
    byId("targetInput").addEventListener("input", () => {
      appState.target = byId("targetInput").value;
      byId("targetError").textContent = "";
      updateFavoriteTargetButton();
      renderPlannerTargetSummary();
      const resolved = resolveKey(appState.target);
      if (resolved && currentPlan && resolved !== currentPlan.target) preparePlannerForTarget(resolved);
      schedulePersistState();
    });
    byId("targetInput").addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        solvePlanner();
      }
    });
    for (const radio of document.querySelectorAll('input[name="strategy"]')) {
      radio.addEventListener("change", () => {
        const refreshPlanner = Boolean(currentPlan || appState.plannerRan || plannerSolveTimer);
        appState.strategy = radio.value;
        updateStrategyHint();
        markPlannerDirty(refreshPlanner ? "规划策略发生变化，正在刷新路线。" : "规划策略已经更新。", false);
        schedulePersistState();
        if (refreshPlanner) schedulePlannerSolve(120);
      });
    }
    byId("passives").addEventListener("input", () => {
      const refreshPlanner = Boolean(currentPlan || appState.plannerRan || plannerSolveTimer);
      appState.passives = byId("passives").value;
      if (appState.passives.trim() && !byId("requireOwned").checked) {
        byId("requireOwned").checked = true;
        appState.requireOwned = true;
      }
      markPlannerDirty(refreshPlanner ? "词条条件发生变化，正在刷新路线。" : "词条条件已经更新。", false);
      schedulePersistState();
      if (refreshPlanner) schedulePlannerSolve(260);
    });
    byId("requireOwned").addEventListener("change", () => {
      const refreshPlanner = Boolean(currentPlan || appState.plannerRan || plannerSolveTimer);
      appState.requireOwned = byId("requireOwned").checked;
      markPlannerDirty(refreshPlanner ? "血脉要求发生变化，正在刷新路线。" : "血脉要求已经更新。", false);
      schedulePersistState();
      if (refreshPlanner) schedulePlannerSolve(120);
    });
    byId("solve").addEventListener("click", solvePlanner);
    byId("favoriteTarget").addEventListener("click", toggleCurrentTargetFavorite);
    byId("recentTargets").addEventListener("click", (event) => {
      const button = event.target.closest("[data-recent-target]");
      if (!button) return;
      setPlannerTarget(button.dataset.recentTarget, false);
    });
    byId("copyCurrentPlan").addEventListener("click", () => copyText(currentPlanText, "路线已复制"));
    byId("copyCompactPlan").addEventListener("click", () => {
      if (!currentPlan) return;
      copyText(planToCompactText(currentPlan, PalSolver.orderedOperations(currentPlan)), "执行版路线已复制");
    });
    byId("printCurrentPlan").addEventListener("click", () => root.print());
    byId("routeDensity").addEventListener("click", () => {
      appState.routeDensity = appState.routeDensity === "compact" ? "comfortable" : "compact";
      applyRouteDensity();
      persistState();
    });
    byId("favoriteCurrentRoute").addEventListener("click", toggleCurrentRouteFavorite);
    byId("continueToPlan").addEventListener("click", scrollToPlannerControls);
    byId("plannerTargetSummary").addEventListener("click", (event) => {
      if (event.target.closest("[data-change-planner-target]")) byId("openTargetPicker").click();
    });
    byId("plannerResults").addEventListener("change", (event) => {
      const check = event.target.closest("[data-route-check]");
      if (!check || !currentPlan) return;
      appState.routeChecks[check.dataset.routeCheck] = check.checked;
      for (const peer of byId("plannerResults").querySelectorAll("[data-route-check]")) {
        if (peer.dataset.routeCheck === check.dataset.routeCheck) peer.checked = check.checked;
      }
      persistState();
      updateChecklistProgress();
    });
    byId("plannerResults").addEventListener("click", (event) => {
      const option = event.target.closest("[data-route-option]");
      if (option) {
        selectedRouteOption = Number(option.dataset.routeOption) || 0;
        renderPlan(currentRouteOptions[selectedRouteOption], 0, { focusResult: false, preserveOptions: true });
      }
    });
    byId("savedRouteShelf").addEventListener("click", (event) => {
      const button = event.target.closest("[data-saved-route-target]");
      if (!button) return;
      const strategy = button.dataset.savedRouteStrategy;
      if (Object.values(PalSolver.STRATEGIES).includes(strategy)) {
        appState.strategy = strategy;
        const radio = document.querySelector(`input[name="strategy"][value="${strategy}"]`);
        if (radio) radio.checked = true;
        updateStrategyHint();
      }
      preferredRouteHash = button.dataset.savedRouteHash || "";
      setPlannerTarget(button.dataset.savedRouteTarget, true);
    });
  }

  function updateStrategyHint() {
    const strategy = document.querySelector('input[name="strategy"]:checked')?.value || appState.strategy;
    const hints = {
      fastest: "优先减少配种操作，适合尽快得到目标。",
      "few-extra": "优先减少需要额外获取的物种，再比较操作数量。",
      "zero-extra": "只使用当前库存和沿途子代；库存不足时可能没有路线。",
      balanced: "综合比较操作数量、补充物种与获取成本，适合没有单一偏好时使用。",
    };
    byId("strategyHint").textContent = `${hints[strategy] || hints.fastest} “需额外获取”不等于可在野外直接抓取。`;
  }

  function renderPlannerTargetSummary() {
    const key = resolveKey(byId("targetInput")?.value || appState.target);
    const summary = byId("plannerTargetSummary");
    if (!summary) return;
    if (!key) {
      summary.classList.add("is-empty");
      summary.innerHTML = '<div><span>当前目标</span><strong>尚未选择有效帕鲁</strong><small>请先在上方推荐、全部目标或搜索框中选择。</small></div><button class="button secondary" type="button" data-change-planner-target>选择目标</button>';
    } else {
      summary.classList.remove("is-empty");
      const types = palTypes(key).map((type) => `<span class="type-badge type-${type}">${escapeHtml(TYPE_LABELS[type])}</span>`).join("");
      const restricted = requiresExternalStart(key) ? '<small class="restricted-note">只能同种自繁：无库存时至少先取得两只异性个体</small>' : '<small>确认策略和库存后即可生成路线</small>';
      summary.innerHTML = `<div class="planner-target-identity">${palThumb(key)}<div><span>当前目标</span><strong>${escapeHtml(palName(key))}</strong><div class="planner-target-types">${types}</div>${restricted}</div></div><button class="button quiet" type="button" data-change-planner-target>更换</button>`;
    }
    updatePlannerAction(key);
  }

  function updatePlannerAction(key = resolveKey(byId("targetInput")?.value || appState.target)) {
    const solve = byId("solve");
    const next = byId("continueToPlan");
    const busy = solve?.getAttribute("aria-busy") === "true";
    if (solve && !busy) {
      solve.disabled = !key;
      solve.textContent = key ? `立即生成${palName(key)}路线` : "请先选择有效目标";
    }
    if (next) {
      next.disabled = !key;
      next.textContent = key ? `继续：为${palName(key)}设置路线条件` : "请先选择一个目标帕鲁";
    }
    updateMobileActionBar();
  }

  function scrollToPlannerControls() {
    if (!resolveKey(byId("targetInput").value)) return;
    const heading = byId("plannerControlsHeading");
    heading.tabIndex = -1;
    heading.focus({ preventScroll: true });
    heading.closest(".control-panel").scrollIntoView({ block: "start", behavior: root.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  }

  function updateFavoriteTargetButton() {
    const key = resolveKey(byId("targetInput").value);
    const button = byId("favoriteTarget");
    button.disabled = !key;
    const active = key ? appState.favorites.has(key) : false;
    button.setAttribute("aria-pressed", String(active));
    button.textContent = active ? "已收藏" : "收藏";
  }

  function toggleCurrentTargetFavorite() {
    const key = resolveKey(byId("targetInput").value);
    if (!key) return;
    if (appState.favorites.has(key)) appState.favorites.delete(key);
    else appState.favorites.add(key);
    updateFavoriteTargetButton();
    dexDirty = true;
    if (appState.activeView === "dex") renderDex();
    persistState();
  }

  function renderRecentTargets() {
    byId("recentTargets").innerHTML = appState.recent.length
      ? appState.recent.map((key) => `<button class="quick-chip" type="button" data-recent-target="${escapeHtml(key)}">${escapeHtml(palName(key))}</button>`).join("")
      : "";
  }

  function renderSavedRouteShelf() {
    const shelf = byId("savedRouteShelf");
    if (!shelf) return;
    const favorites = appState.favoriteRoutes.slice(0, 3).map((item) => ({ ...item, favorite: true }));
    const favoriteHashes = new Set(favorites.map((item) => item.hash));
    const recent = appState.routeHistory.filter((item) => !favoriteHashes.has(item.hash)).slice(0, 3);
    const rows = [...favorites, ...recent].filter((item) => PD.pals[item.target]);
    shelf.innerHTML = rows.length ? `<span class="saved-route-label">路线快捷入口</span><div>${rows.map((item) => `<button class="quick-chip ${item.favorite ? "is-favorite" : ""}" type="button" data-saved-route-target="${escapeHtml(item.target)}" data-saved-route-strategy="${escapeHtml(item.strategy)}" data-saved-route-hash="${escapeHtml(item.hash)}">${item.favorite ? "★ " : ""}${escapeHtml(palName(item.target))} · ${escapeHtml(strategyLabel(item.strategy))}</button>`).join("")}</div>` : "";
  }

  function applyRouteDensity() {
    const compact = appState.routeDensity === "compact";
    document.documentElement.classList.toggle("route-density-compact", compact);
    const button = byId("routeDensity");
    if (button) {
      button.setAttribute("aria-pressed", String(compact));
      button.textContent = compact ? "舒适显示" : "紧凑显示";
    }
  }

  function routeSnapshot(result) {
    return {
      hash: result.hash,
      target: result.target,
      strategy: result.strategy,
      operations: result.operations.size,
      extra: result.extra.size,
      savedAt: new Date().toISOString(),
    };
  }

  function rememberRoute(result) {
    const snapshot = routeSnapshot(result);
    appState.routeHistory = [snapshot, ...appState.routeHistory.filter((item) => item.hash !== snapshot.hash)].slice(0, 8);
    renderSavedRouteShelf();
  }

  function toggleCurrentRouteFavorite() {
    if (!currentPlan) return;
    const index = appState.favoriteRoutes.findIndex((item) => item.hash === currentPlan.hash);
    if (index >= 0) appState.favoriteRoutes.splice(index, 1);
    else appState.favoriteRoutes.unshift(routeSnapshot(currentPlan));
    appState.favoriteRoutes = appState.favoriteRoutes.slice(0, 20);
    updateCurrentRouteFavorite();
    renderSavedRouteShelf();
    persistState();
  }

  function updateCurrentRouteFavorite() {
    const button = byId("favoriteCurrentRoute");
    const active = currentPlan && appState.favoriteRoutes.some((item) => item.hash === currentPlan.hash);
    button.disabled = !currentPlan;
    button.setAttribute("aria-pressed", String(Boolean(active)));
    button.textContent = active ? "已收藏路线" : "收藏路线";
  }

  function rememberTarget(key) {
    appState.recent = [key, ...appState.recent.filter((item) => item !== key)].slice(0, 6);
    renderRecentTargets();
  }

  function setPlannerTarget(key, solveNow) {
    if (!PD.pals[key]) return;
    const previousKey = currentPlan?.target || resolveKey(appState.target);
    const targetChanged = previousKey !== key;
    appState.target = palName(key);
    appState.recipeTarget = appState.target;
    byId("targetInput").value = appState.target;
    byId("recipeTargetInput").value = appState.target;
    byId("targetError").textContent = "";
    updateFavoriteTargetButton();
    renderPlannerTargetSummary();
    renderTargetRecommendations();
    if (byId("targetPickerDialog").open) renderTargetPicker();
    if (targetChanged) preparePlannerForTarget(key);
    schedulePersistState();
    activateView("planner", { focus: false });
    const needsSolve = !currentPlan || currentPlan.target !== key || !appState.plannerRan;
    if (solveNow && needsSolve) solvePlanner();
    else if (solveNow) showToast(`已回到${palName(key)}的现有路线`);
    else showToast(`已选择${palName(key)}，下一步设置路线条件`);
  }

  function bindTargetPicker() {
    const dialog = byId("targetPickerDialog");
    const open = () => {
      renderTargetPickerFilters();
      if (!dialog.open) dialog.showModal();
      if (targetPickerDirty || !byId("targetPickerGrid").children.length) {
        byId("targetPickerStatus").textContent = "正在准备目标列表…";
        byId("targetPickerGrid").innerHTML = '<div class="ui-loading" role="status"><img src="images/pals/70.webp" alt=""><span></span><strong>正在载入目标</strong><small>弹窗已经可以滚动和关闭</small></div>';
        byId("targetPickerGrid").setAttribute("aria-busy", "true");
        targetPickerRestoreScroll = true;
        scheduleTargetPickerRender(0);
      } else {
        dialog.scrollTop = appState.targetPickerScrollTop;
      }
    };
    const openAllForSelectedElement = () => {
      appState.targetPickerMode = "all";
      appState.targetPickerSearch = "";
      byId("targetPickerSearch").value = "";
      targetPickerVisibleCount = TARGET_PICKER_PAGE_SIZE;
      appState.targetPickerVisibleCount = targetPickerVisibleCount;
      appState.targetPickerScrollTop = 0;
      targetPickerDirty = true;
      open();
      schedulePersistState();
    };
    byId("openTargetPicker").addEventListener("click", open);
    byId("openAllTargetsForElement").addEventListener("click", openAllForSelectedElement);
    byId("closeTargetPicker").addEventListener("click", () => dialog.close());
    dialog.addEventListener("scroll", () => {
      appState.targetPickerScrollTop = normalizeScrollPosition(dialog.scrollTop);
    }, { passive: true });
    dialog.addEventListener("close", () => {
      schedulePersistState();
      if (targetPickerRenderTimer) root.clearTimeout(targetPickerRenderTimer);
      targetPickerRenderTimer = null;
    });
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) {
        const rect = dialog.getBoundingClientRect();
        const inside = event.clientX >= rect.left && event.clientX <= rect.right && event.clientY >= rect.top && event.clientY <= rect.bottom;
        if (!inside) dialog.close();
      }
    });
    for (const button of document.querySelectorAll("[data-target-recommendation]")) {
      button.addEventListener("click", () => {
        appState.targetRecommendationMode = button.dataset.targetRecommendation;
        renderTargetRecommendations();
        schedulePersistState();
      });
    }
    for (const id of ["homeCombatFilter", "homeWorkFilter"]) {
      byId(id).addEventListener("change", () => {
        appState.homeCombatFilter = byId("homeCombatFilter").value;
        appState.homeWorkFilter = byId("homeWorkFilter").value;
        renderTargetRecommendations();
        schedulePersistState();
      });
    }
    for (const button of document.querySelectorAll("[data-target-mode]")) {
      button.addEventListener("click", () => {
        appState.targetPickerMode = button.dataset.targetMode;
        targetPickerVisibleCount = TARGET_PICKER_PAGE_SIZE;
        appState.targetPickerVisibleCount = targetPickerVisibleCount;
        appState.targetPickerScrollTop = 0;
        dialog.scrollTop = 0;
        targetPickerDirty = true;
        scheduleTargetPickerRender(0);
        schedulePersistState();
      });
    }
    byId("targetPickerSearch").addEventListener("input", () => {
      appState.targetPickerSearch = byId("targetPickerSearch").value;
      targetPickerVisibleCount = TARGET_PICKER_PAGE_SIZE;
      appState.targetPickerVisibleCount = targetPickerVisibleCount;
      appState.targetPickerScrollTop = 0;
      dialog.scrollTop = 0;
      targetPickerDirty = true;
      scheduleTargetPickerRender(90);
      schedulePersistState();
    });
    for (const container of [byId("homeTargetElements"), byId("targetPickerElements")]) {
      container.addEventListener("click", (event) => {
        const button = event.target.closest("[data-element]");
        if (!button) return;
        const type = button.dataset.element;
        toggleSingleElement(selectedTargetElements, type);
        appState.targetPickerElements = [...selectedTargetElements];
        renderTargetPickerFilters();
        renderTargetRecommendations();
        if (dialog.open) {
          targetPickerVisibleCount = TARGET_PICKER_PAGE_SIZE;
          appState.targetPickerVisibleCount = targetPickerVisibleCount;
          appState.targetPickerScrollTop = 0;
          dialog.scrollTop = 0;
          targetPickerDirty = true;
          scheduleTargetPickerRender(0);
        } else {
          targetPickerDirty = true;
        }
        schedulePersistState();
      });
    }
    for (const container of [byId("targetRecommendations"), byId("targetPickerGrid")]) {
      container.addEventListener("click", (event) => {
        if (event.target.closest("[data-show-more-targets]")) {
          targetPickerVisibleCount += TARGET_PICKER_PAGE_SIZE;
          appState.targetPickerVisibleCount = targetPickerVisibleCount;
          renderTargetPicker();
          schedulePersistState();
          return;
        }
        const button = event.target.closest("[data-target-pick]");
        if (!button) return;
        if (dialog.open) dialog.close();
        setPlannerTarget(button.dataset.targetPick, false);
      });
    }
  }

  function scheduleTargetPickerRender(delay) {
    if (targetPickerRenderTimer) root.clearTimeout(targetPickerRenderTimer);
    targetPickerRenderTimer = root.setTimeout(() => {
      targetPickerRenderTimer = null;
      if (byId("targetPickerDialog").open) renderTargetPicker();
    }, delay);
  }

  function combatScore(key) {
    const stats = (PD.pals[key] && PD.pals[key].stats) || {};
    return (Number(stats.attack) || 0) * 1.35
      + (Number(stats.hp) || 0)
      + (Number(stats.defense) || 0);
  }

  function workProfile(key) {
    const rows = workRows(key);
    return {
      max: rows.reduce((value, item) => Math.max(value, Number(item.lv) || 0), 0),
      total: rows.reduce((value, item) => value + (Number(item.lv) || 0), 0),
      count: rows.length,
    };
  }

  function rankedTargetKeys(mode) {
    if (targetRankCache.has(mode)) return targetRankCache.get(mode);
    const keys = [...allKeys];
    if (mode === "battle") {
      keys.sort((a, b) => combatScore(b) - combatScore(a) || comparePalKeys(a, b));
      targetRankCache.set(mode, keys);
      return keys;
    }
    if (mode === "work") {
      keys.sort((a, b) => {
        const left = workProfile(a);
        const right = workProfile(b);
        return right.max - left.max || right.total - left.total || right.count - left.count || comparePalKeys(a, b);
      });
      targetRankCache.set(mode, keys);
      return keys;
    }
    keys.sort(comparePalKeys);
    targetRankCache.set(mode, keys);
    return keys;
  }

  function matchesCombatRole(key, role) {
    if (!role) return true;
    const pal = PD.pals[key] || {};
    const stats = pal.stats || {};
    const attack = Number(stats.attack) || 0;
    const hp = Number(stats.hp) || 0;
    const defense = Number(stats.defense) || 0;
    const speed = Math.max(Number(stats.runSpeed) || 0, Number(stats.rideSprintSpeed) || 0);
    if (role === "attack") return attack >= 120;
    if (role === "tank") return hp >= 120 || defense >= 120;
    if (role === "speed") return speed >= 1000;
    if (role === "balanced") return attack >= 100 && hp >= 100 && defense >= 100;
    return true;
  }

  function targetMetricHtml(key, mode) {
    if (mode === "work") {
      const rows = [...workRows(key)].sort((a, b) => Number(b.lv) - Number(a.lv)).slice(0, 2);
      return rows.length
        ? rows.map((item) => `<span class="target-metric">${workIcon(item.en)}${escapeHtml(item.zh)} ${escapeHtml(item.lv)}</span>`).join("")
        : '<span class="target-metric">无工作适性</span>';
    }
    if (mode === "battle") {
      const stats = (PD.pals[key] && PD.pals[key].stats) || {};
      return `<span class="target-metric">攻 ${escapeHtml(stats.attack || 0)}</span><span class="target-metric">体 ${escapeHtml(stats.hp || 0)}</span><span class="target-metric">防 ${escapeHtml(stats.defense || 0)}</span>`;
    }
    return palTypes(key).map((type) => `<span class="type-badge type-${type}">${escapeHtml(TYPE_LABELS[type])}</span>`).join("");
  }

  function targetChoiceCard(key, mode, compact = false) {
    const selected = resolveKey(appState.target) === key;
    return `<button class="target-choice-card ${compact ? "is-compact" : ""} ${selected ? "is-selected" : ""}" type="button" data-target-pick="${escapeHtml(key)}" aria-pressed="${selected}">
      ${palImage(key) ? `<img src="${escapeHtml(palImage(key))}" alt="" loading="lazy" decoding="async">` : "<span></span>"}
      <span class="target-choice-copy"><strong>${escapeHtml(palName(key))}</strong><small>#${escapeHtml(palNumber(key))} · ${escapeHtml(palEnglish(key))}</small><span class="target-metrics">${targetMetricHtml(key, mode)}</span>${selected ? '<span class="target-selected-badge">当前目标</span>' : ""}</span>
    </button>`;
  }

  function renderTargetRecommendations() {
    const mode = appState.targetRecommendationMode;
    for (const button of document.querySelectorAll("[data-target-recommendation]")) {
      button.setAttribute("aria-pressed", String(button.dataset.targetRecommendation === mode));
    }
    const rows = rankedTargetKeys(mode)
      .filter((key) => !selectedTargetElements.size || palTypes(key).some((type) => selectedTargetElements.has(type)))
      .filter((key) => matchesCombatRole(key, appState.homeCombatFilter))
      .filter((key) => !appState.homeWorkFilter || workRows(key).some((item) => item.en === appState.homeWorkFilter))
      .slice(0, 4);
    const selectedType = [...selectedTargetElements][0];
    const context = byId("targetRecommendationContext");
    const roleLabels = { attack: "高攻击", tank: "高生存", speed: "高速坐骑", balanced: "均衡战斗" };
    const purpose = [
      roleLabels[appState.homeCombatFilter],
      appState.homeWorkFilter ? WORK_LABELS[appState.homeWorkFilter] : "",
    ].filter(Boolean).join(" · ");
    if (context) context.textContent = `${selectedType ? `${TYPE_LABELS[selectedType]}属性` : "全部属性"} · ${purpose || (mode === "work" ? "强力工作" : "强力战斗")}推荐`;
    const homeSummary = byId("homeFilterSummary");
    if (homeSummary) homeSummary.innerHTML = `<strong>${rows.length} 个推荐</strong><span>${escapeHtml([selectedType ? `属性：${TYPE_LABELS[selectedType]}` : "全部属性", purpose || (mode === "work" ? "强力工作" : "强力战斗")].join(" · "))}</span>`;
    const allElementRows = selectedType
      ? allKeys.filter((key) => palTypes(key).includes(selectedType))
      : allKeys;
    const allTargetButton = byId("openAllTargetsForElement");
    const allTargetHint = byId("targetAllActionHint");
    if (allTargetButton) {
      allTargetButton.textContent = selectedType
        ? `查看${TYPE_LABELS[selectedType]}属性全部 ${allElementRows.length} 只`
        : `查看全部 ${allElementRows.length} 只帕鲁`;
    }
    if (allTargetHint) {
      allTargetHint.textContent = selectedType
        ? `上方仅展示快捷推荐；这里可查看${TYPE_LABELS[selectedType]}属性的全部 ${allElementRows.length} 只帕鲁。`
        : `上方仅展示快捷推荐；这里可查看全部 ${allElementRows.length} 只帕鲁。`;
    }
    byId("targetRecommendations").innerHTML = rows.length
      ? rows.map((key) => targetChoiceCard(key, mode, true)).join("")
      : '<p class="field-hint">当前属性下没有推荐目标。</p>';
  }

  function renderTargetPickerFilters() {
    if (!elementsAvailable) {
      selectedTargetElements.clear();
      const unavailable = '<div class="element-unavailable" role="status">当前数据包未包含已验证属性字段，属性筛选已停用。</div>';
      byId("homeTargetElements").innerHTML = unavailable;
      byId("targetPickerElements").innerHTML = unavailable;
      return;
    }
    renderElementFilterButtons(byId("homeTargetElements"), selectedTargetElements);
    renderElementFilterButtons(byId("targetPickerElements"), selectedTargetElements);
  }

  function renderTargetPicker() {
    const mode = appState.targetPickerMode;
    const query = String(byId("targetPickerSearch") && byId("targetPickerSearch").value || appState.targetPickerSearch).trim().toLowerCase();
    for (const button of document.querySelectorAll("[data-target-mode]")) {
      button.setAttribute("aria-pressed", String(button.dataset.targetMode === mode));
    }
    const matchingRows = rankedTargetKeys(mode).filter((key) => {
      if (query && !palSearchText(key).includes(query.replace(/^#/, ""))) return false;
      if (selectedTargetElements.size && !palTypes(key).some((type) => selectedTargetElements.has(type))) return false;
      return true;
    });
    const total = matchingRows.length;
    const resultLimit = mode === "all" ? total : Math.min(48, total);
    const visibleLimit = mode === "all" ? Math.min(targetPickerVisibleCount, resultLimit) : resultLimit;
    const rows = matchingRows.slice(0, visibleLimit);
    byId("targetPickerStatus").textContent = mode === "all"
      ? `已显示 ${rows.length} / ${total} 只${total !== allKeys.length ? `（全部图鉴 ${allKeys.length} 只）` : ""}`
      : `显示当前条件下排名前 ${rows.length} 只${total > rows.length ? `（共匹配 ${total} 只）` : ""}`;
    byId("targetPickerGrid").innerHTML = rows.length
      ? rows.map((key) => targetChoiceCard(key, mode)).join("") + (rows.length < resultLimit ? `<button class="dex-load-more" type="button" data-show-more-targets>继续显示 ${Math.min(TARGET_PICKER_PAGE_SIZE, resultLimit - rows.length)} 只<span>已显示 ${rows.length} / ${resultLimit}</span></button>` : "")
      : '<div class="empty-state compact-empty"><img src="images/pals/70.webp" alt=""><h3>没有符合条件的目标</h3><p>请取消当前属性或更换关键词。</p></div>';
    byId("targetPickerGrid").removeAttribute("aria-busy");
    targetPickerDirty = false;
    if (targetPickerRestoreScroll) {
      targetPickerRestoreScroll = false;
      root.requestAnimationFrame(() => {
        if (byId("targetPickerDialog").open) byId("targetPickerDialog").scrollTop = appState.targetPickerScrollTop;
      });
    }
  }

  function preparePlannerForTarget(key) {
    if (plannerSolveTimer) {
      root.clearTimeout(plannerSolveTimer);
      plannerSolveTimer = null;
    }
    plannerGeneration += 1;
    currentPlan = null;
    currentRouteOptions = [];
    currentPlanText = "";
    appState.plannerRan = false;
    safeStorageRemove(PLANNER_CACHE_KEY);
    const solve = byId("solve");
    solve.disabled = false;
    solve.removeAttribute("aria-busy");
    byId("copyCurrentPlan").disabled = true;
    byId("copyCompactPlan").disabled = true;
    byId("favoriteCurrentRoute").disabled = true;
    byId("printCurrentPlan").disabled = true;
    byId("plannerResultsHeading").textContent = `已选择${palName(key)}`;
    byId("plannerResults").innerHTML = `<div class="empty-state compact-empty"><img src="images/pals/128.webp" alt=""><h3>目标已经切换</h3><p>当前目标是${escapeHtml(palName(key))}。确认路线策略后即可生成，不需要重新选择目标。</p></div>`;
    byId("plannerStatus").textContent = `已选择${palName(key)}，等待生成路线。`;
    updatePlannerAction(key);
  }

  function schedulePlannerSolve(delay) {
    if (plannerSolveTimer) root.clearTimeout(plannerSolveTimer);
    plannerSolveTimer = root.setTimeout(() => {
      plannerSolveTimer = null;
      if (resolveKey(byId("targetInput").value)) solvePlanner({ focusResult: false });
    }, delay);
  }

  function markPlannerDirty(message, force) {
    plannerGeneration += 1;
    const hadDisplayedResult = Boolean(currentPlan || appState.plannerRan || byId("plannerResultsHeading").textContent !== "先选择目标并生成路线");
    appState.plannerRan = false;
    safeStorageRemove(PLANNER_CACHE_KEY);
    const solving = byId("solve").getAttribute("aria-busy") === "true";
    if (solving) {
      byId("solve").disabled = false;
      byId("solve").removeAttribute("aria-busy");
      byId("plannerStatus").textContent = "条件已变化，旧计算已作废。";
    }
    updatePlannerAction();
    if (!hadDisplayedResult && !force) return;
    currentPlan = null;
    currentRouteOptions = [];
    currentPlanText = "";
    byId("copyCurrentPlan").disabled = true;
    byId("copyCompactPlan").disabled = true;
    byId("favoriteCurrentRoute").disabled = true;
    byId("printCurrentPlan").disabled = true;
    const refreshing = message.includes("正在刷新路线");
    byId("plannerResultsHeading").textContent = refreshing ? "正在刷新路线" : "路线条件已变化";
    byId("plannerResults").innerHTML = refreshing
      ? `<div class="route-notice"><strong>条件已经更新。</strong> ${escapeHtml(message)}</div>`
      : `<div class="stale-notice"><strong>路线需要更新。</strong> ${escapeHtml(message)}</div>`;
    byId("plannerStatus").textContent = message;
  }

  function solvePlanner(options = {}) {
    const targetInput = byId("targetInput");
    const detail = resolveKeyDetailed(targetInput.value);
    const error = byId("targetError");
    error.textContent = "";
    if (!detail.key) {
      error.textContent = detail.ambiguous.length
        ? `名称不唯一，请选择：${detail.ambiguous.map(palName).join("、")}`
        : "找不到目标帕鲁，请检查名称。";
      targetInput.setAttribute("aria-invalid", "true");
      targetInput.focus();
      return;
    }
    targetInput.removeAttribute("aria-invalid");
    const strategy = document.querySelector('input[name="strategy"]:checked').value;
    if (strategy === PalSolver.STRATEGIES.ZERO_EXTRA && !effectiveOwned.size) {
      error.textContent = "“零补充”需要先载入至少一种库存帕鲁。";
      byId("inventoryDetails").open = true;
      return;
    }
    appState.target = palName(detail.key);
    appState.recipeTarget = appState.target;
    targetInput.value = appState.target;
    byId("recipeTargetInput").value = appState.target;
    appState.strategy = strategy;
    appState.passives = byId("passives").value;
    appState.requireOwned = byId("requireOwned").checked || Boolean(appState.passives.trim());
    appState.plannerRan = true;
    byId("requireOwned").checked = appState.requireOwned;
    renderPlannerTargetSummary();
    renderTargetRecommendations();
    const runId = ++plannerGeneration;
    const ownedSnapshot = new Set(effectiveOwned.keys());
    const requireOwnedSnapshot = appState.requireOwned;
    const button = byId("solve");
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    button.textContent = "正在计算…";
    byId("plannerStatus").textContent = "正在比较配方与去重后的操作集合。";
    const started = performance.now();
    root.setTimeout(async () => {
      try {
        if (runId !== plannerGeneration) return;
        const payload = { owned: [...ownedSnapshot], target: detail.key, strategy, requireOwned: requireOwnedSnapshot };
        let candidates;
        if (strategy === PalSolver.STRATEGIES.FASTEST && !requireOwnedSnapshot) {
          candidates = PalSolver.solveRoutes({
            pd: PD,
            owned: ownedSnapshot,
            target: detail.key,
            strategy,
            requireOwned: false,
            limit: 2,
          });
        } else {
          byId("plannerStatus").textContent = "正在建立候选路线…";
          try {
            candidates = await runSolverWorker("plan-options", payload);
          } catch (_) {
            byId("plannerStatus").textContent = "正在兼容模式下比较路线…";
            candidates = await solveOptionsCooperatively(payload);
          }
        }
        if (!Array.isArray(candidates)) candidates = await solveOptionsCooperatively(payload);
        currentRouteOptions = candidates.slice(0, 4);
        const preferredIndex = preferredRouteHash ? currentRouteOptions.findIndex((route) => route.hash === preferredRouteHash) : -1;
        selectedRouteOption = preferredIndex >= 0 ? preferredIndex : 0;
        preferredRouteHash = "";
        const result = currentRouteOptions[selectedRouteOption] || null;
        if (runId !== plannerGeneration) return;
        if (!result) renderNoRoute(detail.key, strategy);
        else renderPlan(result, performance.now() - started, options);
        rememberTarget(detail.key);
        schedulePersistState();
      } catch (solverError) {
        renderSolverError(solverError);
      } finally {
        if (runId === plannerGeneration) {
          button.disabled = false;
          button.removeAttribute("aria-busy");
          updatePlannerAction(detail.key);
        }
      }
    }, 0);
  }

  function renderNoRoute(target, strategy) {
    currentPlan = null;
    currentRouteOptions = [];
    safeStorageRemove(PLANNER_CACHE_KEY);
    currentPlanText = "";
    const recipes = PalSolver.pairEntries(PD, target);
    const requiresTarget = recipes.length && recipes.every((pair) => pair.a === target || pair.b === target);
    let reason = "当前库存与策略下没有找到可行路线。";
    if (requiresExternalStart(target) && !effectiveOwned.has(target)) {
      reason = "该帕鲁无法由其他物种配出。库存为零时，必须先捕捉或通过特殊来源取得至少两只异性个体，之后才能同种自繁。";
    } else if (requiresTarget && !effectiveOwned.has(target)) {
      reason = "当前配方都要求先拥有该目标。请在图鉴中确认它的特殊获取来源；工具不会把来源未知的帕鲁笼统写成“野外可抓”。";
    } else if (strategy === PalSolver.STRATEGIES.ZERO_EXTRA) {
      reason = "只用当前库存无法完成。可以改用“少补充”，查看至少还需额外获取哪些物种。";
    } else if (appState.requireOwned) {
      reason = "没有找到既满足当前策略、又能使用库存血脉的路线。可关闭“必须使用库存帕鲁”后重试。";
    }
    byId("plannerResultsHeading").textContent = `未找到配出“${palName(target)}”的路线`;
    byId("plannerResults").innerHTML = `<div class="empty-state compact-empty"><img src="images/pals/111.webp" alt=""><h3>没有可执行路线</h3><p>${escapeHtml(reason)}</p><button class="button secondary" type="button" data-open-recipes="${escapeHtml(target)}">查看目标全部配方</button></div>`;
    byId("plannerStatus").textContent = reason;
    byId("copyCurrentPlan").disabled = true;
    byId("copyCompactPlan").disabled = true;
    byId("favoriteCurrentRoute").disabled = true;
    byId("printCurrentPlan").disabled = true;
    persistState();
  }

  function renderSolverError(error) {
    currentPlan = null;
    currentRouteOptions = [];
    appState.plannerRan = false;
    safeStorageRemove(PLANNER_CACHE_KEY);
    byId("plannerResultsHeading").textContent = "求解失败";
    byId("plannerResults").innerHTML = '<div class="empty-state compact-empty"><h3>计算未完成</h3><p>数据结构可能与当前求解器不兼容，请检查配方数据后重试。</p></div>';
    byId("plannerStatus").textContent = `求解失败：${error && error.message ? error.message : "未知错误"}`;
    persistState();
  }

  function strategyLabel(strategy) {
    if (strategy === PalSolver.STRATEGIES.FEW_EXTRA) return "少补充";
    if (strategy === PalSolver.STRATEGIES.ZERO_EXTRA) return "零补充";
    if (strategy === PalSolver.STRATEGIES.BALANCED) return "综合权衡";
    return "最快成型";
  }

  function renderPlan(result, elapsed, options = {}) {
    currentPlan = result;
    const operations = PalSolver.orderedOperations(result);
    const extra = [...result.extra].sort(comparePalKeys);
    const ownedUsed = [...result.owned].sort(comparePalKeys);
    const target = result.target;
    const steps = operations.map((operation, index) => renderOperation(operation, index + 1, result)).join("");
    const unknownSources = extra.filter((key) => acquisitionText(key).unknown);
    const legacyGender = operations.some((operation) => operation.legacy || (!operation.ga && !operation.gb));
    const constrainedGender = operations.some((operation) => [operation.ga, operation.gb].some((gender) => gender && gender !== "any"));
    const externalStartOnly = extra.filter(requiresExternalStart);
    const minimumExtraIndividuals = extra.reduce((sum, key) => sum + (requiresExternalStart(key) ? 2 : 1), 0);
    let notice = "";
    if (unknownSources.length) {
      notice += `<div class="route-notice"><strong>获取来源未完全注明。</strong> ${escapeHtml(unknownSources.map(palName).join("、"))} 只表示不在当前库存；请在游戏或已核验图鉴中确认具体来源。</div>`;
    }
    if (legacyGender) {
      notice += '<div class="route-notice"><strong>部分旧配方没有性别字段。</strong> 实际入场前请确认亲本性别满足游戏要求。</div>';
    }
    if (constrainedGender) {
      const missing = routeGenderGaps(operations);
      notice += missing.length
        ? `<div class="route-notice"><strong>路线所需个体性别尚未全部准备。</strong> ${escapeHtml(missing.join("、"))}；取得后可在“我的库存”中补充个体资料。</div>`
        : '<div class="route-notice"><strong>已按库存个体核对性别。</strong> 当前已记录的雄性、雌性个体可以覆盖路线中的明确性别要求。</div>';
    }
    if (externalStartOnly.length) {
      notice += `<div class="route-notice critical-notice"><strong>有 ${externalStartOnly.length} 种无法由其他物种配出。</strong> ${escapeHtml(externalStartOnly.map(palName).join("、"))} 必须先捕捉或通过特殊来源取得；当前无库存时，每种至少需要两只异性个体才能同种自繁，不能按“补 1 种”理解成只补 1 只。</div>`;
    }
    if (appState.passives.trim() && !ownedUsed.length) {
      notice += '<div class="route-notice"><strong>本路线没有使用库存血脉。</strong> 目标词条无法从你的现有帕鲁沿路线传递。</div>';
    }
    const extraHtml = extra.length
      ? `<section class="extra-section"><div class="extra-heading"><div><h3>需额外获取 ${extra.length} 种</h3><p>最低 ${minimumExtraIndividuals} 只起步个体；实际数量受性别与获取方式影响。</p></div></div><div class="extra-list">${extra.map((key) => {
        const source = acquisitionText(key);
        const rule = requiresExternalStart(key);
        return `<button class="pal-link is-extra extra-pal-card ${rule ? "is-restricted" : ""}" type="button" data-pal="${escapeHtml(key)}">${palThumb(key)}<span class="extra-pal-copy"><strong>${escapeHtml(palName(key))}</strong><small>${rule ? "无法由其他物种配出 · 至少先获取 2 只异性个体" : "需先取得 1 只起步个体"}</small></span><span class="availability-badge">${escapeHtml(source.text)}</span></button>`;
      }).join("")}</div></section>`
      : '<section class="extra-section"><h3>无需额外获取</h3><p class="field-hint">路线只使用当前库存和沿途配出的帕鲁。</p></section>';
    const optionHtml = renderRouteOptions();
    const checklistHtml = renderRouteChecklist(result, operations, extra);
    const dependencyHtml = renderDependencyGraph(operations);
    const statsHtml = renderTargetStatsComparison(target);
    byId("plannerResultsHeading").textContent = `配出“${palName(target)}”的路线`;
    byId("plannerResults").innerHTML = `
      ${optionHtml}
      <div class="route-summary">
        <div class="summary-card primary-summary"><span>目标与策略</span><strong>${escapeHtml(palName(target))}</strong><small>${escapeHtml(strategyLabel(result.strategy))}</small></div>
        <div class="summary-card"><span>配种操作</span><strong>${operations.length}</strong><small>按最终操作集合去重</small></div>
        <div class="summary-card"><span>额外获取</span><strong>${extra.length} 种</strong><small>最低 ${minimumExtraIndividuals} 只起步个体</small></div>
        <div class="summary-card"><span>库存血脉</span><strong>${ownedUsed.length}</strong><small>使用的库存物种</small></div>
      </div>
      ${statsHtml}
      ${notice}
      ${checklistHtml}
      <details class="dependency-panel"><summary><strong>查看路线依赖图</strong><span>从起步亲本到最终目标</span></summary>${dependencyHtml}</details>
      <div class="route-steps">${steps}</div>
      ${extraHtml}`;
    currentPlanText = planToText(result, operations);
    byId("copyCurrentPlan").disabled = false;
    byId("copyCompactPlan").disabled = false;
    byId("printCurrentPlan").disabled = false;
    updateCurrentRouteFavorite();
    if (!options.restored) rememberRoute(result);
    updateChecklistProgress();
    byId("plannerStatus").textContent = options.restored
      ? "已立即恢复上次路线，条件变化时才会重新计算。"
      : `已完成：${operations.length} 个去重操作，计算用时 ${Math.round(elapsed)} 毫秒。`;
    if (!options.restored) root.setTimeout(persistPlannerResultCache, 0);
    if (options.focusResult !== false) {
      const heading = byId("plannerResultsHeading");
      heading.tabIndex = -1;
      heading.focus({ preventScroll: true });
      if (root.matchMedia("(max-width: 1020px)").matches) heading.scrollIntoView({ block: "start", behavior: root.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    }
  }

  function renderOperation(operation, number, result) {
    const genderA = operation.ga && operation.ga !== "any" ? `<span class="gender-badge">${escapeHtml(PalSolver.genderLabel(operation.ga))}</span>` : "";
    const genderB = operation.gb && operation.gb !== "any" ? `<span class="gender-badge">${escapeHtml(PalSolver.genderLabel(operation.gb))}</span>` : "";
    const note = operation.ga || operation.gb ? "" : '<p class="step-note">此条旧配方未注明亲本性别。</p>';
    const checkKey = `${result.hash}:breed:${operation.signature}`;
    return `<article class="route-step ${appState.routeChecks[checkKey] ? "is-complete" : ""}">
      <div class="step-number" aria-hidden="true">${number}</div>
      <div>
        <div class="breeding-equation">
          ${palButton(operation.a, result, genderA)}
          <span class="equation-symbol" aria-label="和">×</span>
          ${palButton(operation.b, result, genderB)}
          <span class="equation-symbol" aria-label="得到">→</span>
          ${palButton(operation.child, result, "")}
        </div>
        ${note}
      </div>
      <label class="route-step-check"><input type="checkbox" data-route-check="${escapeHtml(checkKey)}"${appState.routeChecks[checkKey] ? " checked" : ""}><span>完成</span></label>
    </article>`;
  }

  function renderRouteOptions() {
    if (currentRouteOptions.length <= 1) return "";
    return `<section class="route-options"><div><strong>可选路线</strong><span>对比操作数与需要补充的帕鲁</span></div><div class="route-option-tabs">${currentRouteOptions.map((route, index) => {
      const label = index > 0 && route.strategy === currentRouteOptions[0].strategy ? "同策略备选" : strategyLabel(route.strategy);
      return `<button type="button" data-route-option="${index}" aria-pressed="${index === selectedRouteOption}"><strong>${escapeHtml(label)}</strong><small>${route.operations.size} 步 · 补 ${route.extra.size} 种</small></button>`;
    }).join("")}</div></section>`;
  }

  function renderRouteChecklist(result, operations, extra) {
    const shopping = extra.map((key) => {
      const restricted = requiresExternalStart(key);
      const checkKey = `${result.hash}:get:${key}`;
      const genders = requiredGendersForPal(operations, key);
      const preparation = restricted
        ? "至少 2 只：雄性 1 + 雌性 1"
        : genders.length
          ? `至少 1 只：${genders.map(PalSolver.genderLabel).join(" / ")}`
          : "至少 1 只；配方未限定性别";
      return `<label class="checklist-row is-shopping"><input type="checkbox" data-route-check="${escapeHtml(checkKey)}"${appState.routeChecks[checkKey] ? " checked" : ""}><span>${palThumb(key)}<strong>取得${escapeHtml(palName(key))}</strong><small>${escapeHtml(preparation)}</small></span></label>`;
    }).join("");
    const steps = operations.map((operation, index) => {
      const checkKey = `${result.hash}:breed:${operation.signature}`;
      return `<label class="checklist-row is-step"><input type="checkbox" data-route-check="${escapeHtml(checkKey)}"${appState.routeChecks[checkKey] ? " checked" : ""}><span><strong>第 ${index + 1} 步：${escapeHtml(palName(operation.a))} × ${escapeHtml(palName(operation.b))}</strong><small>得到 ${escapeHtml(palName(operation.child))}</small></span></label>`;
    }).join("");
    return `<details class="execution-checklist" open><summary><span><strong>路线执行清单</strong><small id="checklistProgress">0 / ${extra.length + operations.length} 已完成</small></span><span>逐项勾选</span></summary><div class="checklist-groups">${shopping ? `<section><h3>先准备</h3>${shopping}</section>` : ""}<section><h3>再配种</h3>${steps}</section></div></details>`;
  }

  function requiredGendersForPal(operations, key) {
    const genders = new Set();
    for (const operation of operations) {
      if (operation.a === key && ["male", "female"].includes(operation.ga)) genders.add(operation.ga);
      if (operation.b === key && ["male", "female"].includes(operation.gb)) genders.add(operation.gb);
    }
    return [...genders];
  }

  function updateChecklistProgress() {
    const progress = byId("checklistProgress");
    if (!progress) return;
    const checks = [...byId("plannerResults").querySelectorAll("[data-route-check]")];
    const unique = new Map(checks.map((check) => [check.dataset.routeCheck, check.checked]));
    const done = [...unique.values()].filter(Boolean).length;
    progress.textContent = `${done} / ${unique.size} 已完成`;
    for (const check of checks) check.closest(".route-step, .checklist-row")?.classList.toggle("is-complete", check.checked);
  }

  function renderDependencyGraph(operations) {
    if (!operations.length) return '<p class="field-hint">目标无需配种操作。</p>';
    return `<div class="dependency-graph">${operations.map((operation, index) => `<div class="dependency-node"><span>第 ${index + 1} 步</span><strong>${escapeHtml(palName(operation.a))} × ${escapeHtml(palName(operation.b))}</strong><i aria-hidden="true">↓</i><b>${escapeHtml(palName(operation.child))}</b></div>`).join("")}</div>`;
  }

  function renderTargetStatsComparison(key) {
    const stats = (PD.pals[key] && PD.pals[key].stats) || {};
    const fields = [["生命", "hp"], ["攻击", "attack"], ["防御", "defense"]];
    const valuesByField = Object.values(PD.pals).map((pal) => pal.stats || {});
    return `<section class="target-stat-comparison"><div><strong>目标基础能力</strong><span>与全部正式帕鲁对比</span></div><div>${fields.map(([label, field]) => {
      const value = Number(stats[field]) || 0;
      const below = valuesByField.filter((item) => (Number(item[field]) || 0) <= value).length;
      const percentile = Math.round(below / valuesByField.length * 100);
      return `<span><small>${label}</small><strong>${value}</strong><i><b style="width:${percentile}%"></b></i><em>高于约 ${percentile}%</em></span>`;
    }).join("")}</div></section>`;
  }

  function routeGenderGaps(operations) {
    const gaps = new Set();
    for (const operation of operations) {
      for (const [key, gender] of [[operation.a, operation.ga], [operation.b, operation.gb]]) {
        if (!gender || gender === "any") continue;
        if (!effectiveOwned.has(key)) {
          gaps.add(`${palName(key)}需准备${PalSolver.genderLabel(gender)}个体`);
          continue;
        }
        const record = effectiveOwned.get(key);
        if ((gender === "male" && !record.male) || (gender === "female" && !record.female)) {
          gaps.add(`${palName(key)}缺少已记录的${PalSolver.genderLabel(gender)}个体`);
        }
      }
    }
    return [...gaps];
  }

  function palButton(key, result, suffix) {
    const className = result.extra.has(key) ? "is-extra" : effectiveOwned.has(key) ? "is-owned" : "";
    return `<button class="pal-link ${className}" type="button" data-pal="${escapeHtml(key)}">${palThumb(key)}<span>${escapeHtml(palName(key))}</span>${suffix}</button>`;
  }

  function palThumb(key) {
    return palImage(key) ? `<img class="pal-thumb" src="${escapeHtml(palImage(key))}" alt="" loading="lazy" decoding="async">` : "";
  }

  function planToText(result, operations) {
    const extra = [...result.extra].sort(comparePalKeys);
    const rows = [
      `${palName(result.target)} · ${strategyLabel(result.strategy)}`,
      `配种操作：${operations.length}`,
      `需额外获取：${extra.length ? extra.map((key) => `${palName(key)}${requiresExternalStart(key) ? "（无法由其他物种配出，至少先获取两只异性个体）" : ""}`).join("、") : "无"}`,
      "步骤：",
    ];
    operations.forEach((operation, index) => {
      const ga = operation.ga === "any" ? "" : operation.ga ? `（${PalSolver.genderLabel(operation.ga)}）` : "（性别未注明）";
      const gb = operation.gb === "any" ? "" : operation.gb ? `（${PalSolver.genderLabel(operation.gb)}）` : "（性别未注明）";
      rows.push(`${index + 1}. ${palName(operation.a)}${ga} × ${palName(operation.b)}${gb} → ${palName(operation.child)}`);
    });
    rows.push("注：‘需额外获取’不代表一定能在野外直接捕捉；同种自繁限定帕鲁无库存时至少要先取得两只异性个体。 ");
    return rows.join("\n");
  }

  function planToCompactText(result, operations) {
    const extra = [...result.extra].sort(comparePalKeys);
    const rows = [`【${palName(result.target)}】${strategyLabel(result.strategy)}｜${operations.length} 步｜补 ${extra.length} 种`];
    if (extra.length) rows.push(`准备：${extra.map((key) => `${palName(key)}${requiresExternalStart(key) ? "×2（雄1雌1）" : "×1"}`).join("；")}`);
    operations.forEach((operation, index) => {
      const ga = operation.ga && operation.ga !== "any" ? `(${PalSolver.genderLabel(operation.ga)})` : "";
      const gb = operation.gb && operation.gb !== "any" ? `(${PalSolver.genderLabel(operation.gb)})` : "";
      rows.push(`${index + 1}. ${palName(operation.a)}${ga}×${palName(operation.b)}${gb}→${palName(operation.child)}`);
    });
    return rows.join("\n");
  }

  function acquisitionText(key) {
    const pal = PD.pals[key] || {};
    const stats = pal.stats || {};
    const hasWildLevels = stats.minWildLevel !== null && stats.minWildLevel !== undefined
      || stats.maxWildLevel !== null && stats.maxWildLevel !== undefined;
    if (requiresExternalStart(key)) {
      return { text: hasWildLevels ? "野外捕捉起步 / 特殊获取" : "特殊获取起步（具体来源待核验）", unknown: !hasWildLevels, restricted: true, categories: hasWildLevels ? ["捕捉", "特殊获取"] : ["特殊获取"] };
    }
    const deck = PALDECK[key] || {};
    const raw = deck.acquisition || deck.sources || pal.acquisition || pal.sources;
    if (!raw) return { text: hasWildLevels ? "野外捕捉 / 配种" : "配种 / 特殊来源", unknown: false, categories: hasWildLevels ? ["捕捉", "配种"] : ["配种", "特殊来源"] };
    if (typeof raw === "string") return { text: raw, unknown: false };
    if (Array.isArray(raw)) {
      const names = raw.map((item) => typeof item === "string" ? item : item.name || item.label || item.type).filter(Boolean);
      return names.length ? { text: names.slice(0, 2).join(" / "), unknown: false } : { text: "来源待核验", unknown: true };
    }
    const label = raw.name || raw.label || raw.type || raw.note;
    return label ? { text: label, unknown: false } : { text: "来源待核验", unknown: true };
  }

  function requiresExternalStart(key) {
    if (acquisitionRuleCache.has(key)) return acquisitionRuleCache.get(key);
    const pairs = PalSolver.pairEntries(PD, key);
    const restricted = pairs.length > 0 && pairs.every((pair) => pair.a === key && pair.b === key);
    acquisitionRuleCache.set(key, restricted);
    return restricted;
  }

  function bindReverse() {
    byId("runReverse").addEventListener("click", runReverse);
    byId("reverseInventoryBanner").addEventListener("click", (event) => {
      if (event.target.closest("[data-manage-inventory]")) goToInventory();
    });
    for (const id of ["only5", "reverseWork", "reverseMaxExtra", "reverseSort"]) {
      byId(id).addEventListener("change", () => {
        appState.reverseOnly5 = byId("only5").checked;
        appState.reverseWork = byId("reverseWork").value;
        appState.reverseMaxExtra = byId("reverseMaxExtra").value;
        appState.reverseSort = byId("reverseSort").value;
        renderReverseFilterSummary();
        schedulePersistState();
        if (appState.reverseRan || reverseHasRun) scheduleReverseRun();
      });
    }
    byId("reverseElements").addEventListener("click", (event) => {
      const button = event.target.closest("[data-element]");
      if (!button) return;
      const type = button.dataset.element;
      toggleSingleElement(selectedReverseElements, type);
      appState.reverseElements = [...selectedReverseElements];
      renderReverseFilters();
      schedulePersistState();
      if (appState.reverseRan || reverseHasRun) scheduleReverseRun();
    });
    byId("reverseReset").addEventListener("click", () => {
      appState.reverseOnly5 = true;
      appState.reverseWork = "";
      appState.reverseMaxExtra = "2";
      appState.reverseElements = [];
      appState.reverseSort = "cost";
      selectedReverseElements.clear();
      byId("only5").checked = true;
      byId("reverseWork").value = "";
      byId("reverseMaxExtra").value = "2";
      byId("reverseSort").value = "cost";
      renderReverseFilters();
      renderReverseFilterSummary();
      schedulePersistState();
      if (appState.reverseRan || reverseHasRun) scheduleReverseRun();
    });
    byId("reverseResults").addEventListener("click", (event) => {
      if (event.target.closest("[data-manage-inventory]")) {
        goToInventory();
        return;
      }
      if (event.target.closest("[data-show-more-reverse]")) {
        reverseVisibleCount += REVERSE_PAGE_SIZE;
        appState.reverseVisibleCount = reverseVisibleCount;
        renderReverseRows();
        schedulePersistState();
        return;
      }
      if (event.target.closest("[data-reset-reverse]")) {
        byId("reverseReset").click();
        return;
      }
      const pin = event.target.closest("[data-pin-reverse]");
      if (pin) {
        toggleReversePin(pin.dataset.pinReverse);
        return;
      }
      const unpin = event.target.closest("[data-unpin-reverse]");
      if (unpin) {
        toggleReversePin(unpin.dataset.unpinReverse);
        return;
      }
      const button = event.target.closest("[data-reverse-target]");
      if (!button) return;
      setPlannerTarget(button.dataset.reverseTarget, true);
    });
    byId("reverseCompareTray").addEventListener("click", (event) => {
      const button = event.target.closest("[data-unpin-reverse]");
      if (button) toggleReversePin(button.dataset.unpinReverse);
    });
  }

  function renderReverseInventoryBanner() {
    const banner = byId("reverseInventoryBanner");
    if (!banner) return;
    if (effectiveOwned.size) {
      banner.classList.remove("is-empty");
      banner.innerHTML = `<div><span>当前反查基础</span><strong>已载入 ${effectiveOwned.size} 种库存帕鲁</strong><small>${appState.showCrossWorldGenes ? "已临时纳入跨界基因 · " : ""}修改筛选后会自动更新结果</small></div><button class="button quiet" type="button" data-manage-inventory>管理库存</button>`;
    } else {
      banner.classList.add("is-empty");
      banner.innerHTML = '<div><span>开始前需要库存</span><strong>尚未载入任何帕鲁</strong><small>先添加或导入库存，才能判断可以配出什么。</small></div><button class="button primary" type="button" data-manage-inventory>去添加库存</button>';
    }
  }

  function goToInventory() {
    activateView("planner", { focus: false });
    byId("inventoryDetails").open = true;
    const summary = byId("inventoryDetails").querySelector("summary");
    summary.scrollIntoView({ block: "center", behavior: root.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    summary.focus({ preventScroll: true });
  }

  function runReverse() {
    if (!effectiveOwned.size) {
      appState.reverseRan = false;
      reverseHasRun = false;
      byId("reverseStatus").textContent = "请先在配种规划中添加或导入库存。";
      byId("reverseResults").innerHTML = '<div class="empty-state compact-empty"><img src="images/pals/10.webp" alt=""><h2>先载入库存</h2><p>反向发现需要以现有帕鲁为起点。</p><button class="button primary" type="button" data-manage-inventory>去添加库存</button></div>';
      byId("reverseStatus").classList.remove("is-success");
      persistState();
      return;
    }
    appState.reverseRan = true;
    const button = byId("runReverse");
    const runId = ++reverseGeneration;
    const ownedSnapshot = new Set(effectiveOwned.keys());
    const cacheKey = [...ownedSnapshot].sort(comparePalKeys).join("|");
    const maxExtra = Number(byId("reverseMaxExtra").value);
    const only5 = byId("only5").checked;
    const work = byId("reverseWork").value;
    const elements = new Set(selectedReverseElements);
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    button.textContent = "正在反查…";
    byId("reverseStatus").textContent = "正在比较可配子代。";
    byId("reverseStatus").classList.remove("is-success");
    root.setTimeout(async () => {
      const started = performance.now();
      try {
        if (runId !== reverseGeneration) return;
        if (reverseRouteCache.key !== cacheKey || !reverseRouteCache.rows) {
          const restored = restoreReverseResultCache(cacheKey);
          if (restored) reverseRouteCache = { key: cacheKey, rows: restored };
        }
        if (reverseRouteCache.key !== cacheKey || !reverseRouteCache.rows) {
          if (!reverseDiscoverPromise || reverseDiscoverKey !== cacheKey) {
            reverseDiscoverKey = cacheKey;
            reverseDiscoverPromise = discoverRoutesInBackground(ownedSnapshot);
          }
          const discovered = await reverseDiscoverPromise;
          if (reverseDiscoverKey === cacheKey) {
            reverseRouteCache = { key: cacheKey, rows: discovered };
            root.setTimeout(() => persistReverseResultCache(cacheKey, discovered), 0);
            reverseDiscoverPromise = null;
            reverseDiscoverKey = "";
          }
        }
        if (runId !== reverseGeneration) return;
        let rows = [...reverseRouteCache.rows];
        rows = rows.filter((result) => result.extra.size <= maxExtra);
        if (only5) rows = rows.filter((result) => highWork(result.target).length);
        if (work) rows = rows.filter((result) => workRows(result.target).some((item) => item.en === work));
        if (elements.size) rows = rows.filter((result) => palTypes(result.target).some((type) => elements.has(type)));
        rows.sort(reverseSortComparator(appState.reverseSort));
        setReverseRows(rows, maxExtra, only5, work, elements);
        renderReverseFilterSummary(rows.length);
        renderReverseCompareTray();
        reverseHasRun = true;
        persistState();
        byId("reverseStatus").textContent = `找到 ${rows.length} 种结果，用时 ${Math.round(performance.now() - started)} 毫秒。`;
        byId("reverseStatus").classList.toggle("is-success", rows.length > 0);
      } catch (error) {
        if (reverseDiscoverKey === cacheKey) {
          reverseDiscoverPromise = null;
          reverseDiscoverKey = "";
        }
        appState.reverseRan = false;
        reverseHasRun = false;
        byId("reverseStatus").textContent = `反查失败：${error.message || "未知错误"}`;
        byId("reverseStatus").classList.remove("is-success");
        persistState();
      } finally {
        if (runId === reverseGeneration) {
          button.disabled = false;
          button.removeAttribute("aria-busy");
          button.textContent = reverseHasRun ? "重新反查" : "开始反查";
          updateMobileActionBar();
        }
      }
    }, 0);
  }

  function scheduleReverseRun() {
    if (reverseRenderTimer) root.clearTimeout(reverseRenderTimer);
    reverseRenderTimer = root.setTimeout(() => {
      reverseRenderTimer = null;
      runReverse();
    }, 90);
  }

  async function discoverRoutesInBackground(ownedSnapshot) {
    let discovered;
    try {
      discovered = await runSolverWorker("discover", { owned: [...ownedSnapshot] });
    } catch (_) {
      discovered = null;
    }
    if (!Array.isArray(discovered)) {
      byId("reverseStatus").textContent = "正在兼容模式下反查…";
      await new Promise((resolve) => root.setTimeout(resolve, 0));
      discovered = PalSolver.discoverRoutes({
        pd: PD,
        owned: ownedSnapshot,
        strategy: PalSolver.STRATEGIES.FEW_EXTRA,
        frontierLimit: 1,
        maxIterations: 9,
      });
    }
    return Array.isArray(discovered) ? discovered : [];
  }

  function setReverseRows(rows, maxExtra, only5, work, elements = new Set()) {
    reverseRowsCache = rows;
    reverseRowsContext = { maxExtra, only5, work, elements: new Set(elements) };
    reverseVisibleCount = reverseHasRun ? REVERSE_PAGE_SIZE : Math.max(REVERSE_PAGE_SIZE, appState.reverseVisibleCount);
    appState.reverseVisibleCount = reverseVisibleCount;
    renderReverseRows();
  }

  function renderReverseRows() {
    const rows = reverseRowsCache;
    const { maxExtra, only5, work, elements } = reverseRowsContext;
    if (!rows.length) {
      const elementText = elements.size ? `，属性为${[...elements].map((type) => TYPE_LABELS[type]).join(" / ")}` : "";
      byId("reverseResults").innerHTML = `<div class="empty-state compact-empty"><img src="images/pals/17.webp" alt=""><h2>没有符合条件的结果</h2><p>当前最多补充 ${maxExtra} 种${only5 ? "，并要求基础工作适性至少 5 级" : ""}${work ? `，工作类型为${WORK_LABELS[work]}` : ""}${elementText}。</p><button class="button secondary" type="button" data-reset-reverse>重置筛选</button></div>`;
      return;
    }
    const visibleRows = rows.slice(0, reverseVisibleCount);
    const groups = new Map();
    for (const row of visibleRows) {
      const count = row.extra.size;
      if (!groups.has(count)) groups.set(count, []);
      groups.get(count).push(row);
    }
    byId("reverseResults").innerHTML = [...groups.entries()].sort((a, b) => a[0] - b[0]).map(([count, items]) => `
      <section class="reverse-group">
        <div class="reverse-group-header"><h2>${count ? `补充 ${count} 种` : "无需补充"}</h2><span class="field-hint">${items.length} 种结果</span></div>
        <div class="reverse-grid">${items.map(renderReverseCard).join("")}</div>
      </section>`).join("") + (visibleRows.length < rows.length ? `<button class="dex-load-more result-load-more" type="button" data-show-more-reverse>继续显示 ${Math.min(REVERSE_PAGE_SIZE, rows.length - visibleRows.length)} 个结果<span>已显示 ${visibleRows.length} / ${rows.length}</span></button>` : "");
  }

  function renderReverseFilters() {
    if (!elementsAvailable) {
      selectedReverseElements.clear();
      byId("reverseElements").innerHTML = '<div class="element-unavailable" role="status">当前数据包未包含已验证属性字段，属性筛选已停用。</div>';
      return;
    }
    renderElementFilterButtons(byId("reverseElements"), selectedReverseElements);
  }

  function reverseSortComparator(mode) {
    if (mode === "operations") return (a, b) => routeOperationCount(a) - routeOperationCount(b) || a.extra.size - b.extra.size || comparePalKeys(a.target, b.target);
    if (mode === "work") return (a, b) => maxWorkLevel(b.target) - maxWorkLevel(a.target) || a.extra.size - b.extra.size || comparePalKeys(a.target, b.target);
    if (mode === "combat") return (a, b) => combatScore(b.target) - combatScore(a.target) || a.extra.size - b.extra.size || comparePalKeys(a.target, b.target);
    if (mode === "number") return (a, b) => comparePalKeys(a.target, b.target);
    return (a, b) => a.extra.size - b.extra.size || minimumIndividuals(a.extra) - minimumIndividuals(b.extra) || routeOperationCount(a) - routeOperationCount(b) || maxWorkLevel(b.target) - maxWorkLevel(a.target) || comparePalKeys(a.target, b.target);
  }

  function renderReverseFilterSummary(resultCount = null) {
    const parts = [];
    const type = [...selectedReverseElements][0];
    if (type) parts.push(`属性：${TYPE_LABELS[type]}`);
    if (appState.reverseWork) parts.push(`工作：${WORK_LABELS[appState.reverseWork]}`);
    if (appState.reverseOnly5) parts.push("基础工作适性 ≥ 5");
    parts.push(`最多补 ${appState.reverseMaxExtra} 种`);
    const sortLabels = { cost: "补充最少", operations: "操作最少", work: "工作最强", combat: "战斗最强", number: "图鉴编号" };
    parts.push(`排序：${sortLabels[appState.reverseSort]}`);
    byId("reverseFilterSummary").innerHTML = `<strong>${resultCount === null ? "当前条件" : `${resultCount} 个结果`}</strong><span>${escapeHtml(parts.join(" · "))}</span>`;
  }

  function toggleReversePin(key) {
    if (appState.reversePinned.includes(key)) appState.reversePinned = appState.reversePinned.filter((item) => item !== key);
    else if (appState.reversePinned.length < 3) appState.reversePinned.push(key);
    else {
      showToast("最多同时对比 3 只帕鲁");
      return;
    }
    renderReverseCompareTray();
    syncReversePinControls();
    persistState();
  }

  function syncReversePinControls() {
    for (const button of byId("reverseResults").querySelectorAll("[data-pin-reverse]")) {
      const active = appState.reversePinned.includes(button.dataset.pinReverse);
      button.setAttribute("aria-pressed", String(active));
      button.textContent = active ? "已固定" : "对比";
      button.closest(".reverse-card-shell")?.classList.toggle("is-pinned", active);
    }
  }

  function renderReverseCompareTray() {
    const tray = byId("reverseCompareTray");
    const rows = appState.reversePinned.filter((key) => PD.pals[key]);
    tray.hidden = !rows.length;
    if (!rows.length) {
      tray.innerHTML = "";
      return;
    }
    tray.innerHTML = `<div class="compare-tray-heading"><strong>已固定对比 ${rows.length} / 3</strong><span>生命 / 攻击 / 防御 / 最高工作</span></div><div class="compare-cards">${rows.map((key) => {
      const stats = PD.pals[key].stats || {};
      return `<article>${palThumb(key)}<div><strong>${escapeHtml(palName(key))}</strong><small>体 ${stats.hp || 0} · 攻 ${stats.attack || 0} · 防 ${stats.defense || 0} · 工作 ${maxWorkLevel(key)}</small></div><button type="button" data-unpin-reverse="${escapeHtml(key)}" aria-label="取消固定${escapeHtml(palName(key))}">×</button></article>`;
    }).join("")}</div>`;
  }

  function renderReverseCard(result) {
    const work = highWork(result.target).slice(0, 3);
    const workHtml = work.length ? `<span class="work-inline">${work.map((item) => `<span class="work-badge">${workIcon(item.en)}${escapeHtml(item.zh)} ${item.lv}</span>`).join("")}</span>` : "";
    const restricted = [...result.extra].filter(requiresExternalStart).length;
    const individuals = minimumIndividuals(result.extra);
    const cost = result.extra.size ? `补充 ${result.extra.size} 种 · 最低 ${individuals} 只` : "无需额外获取";
    return `<article class="reverse-card-shell ${appState.reversePinned.includes(result.target) ? "is-pinned" : ""}"><button class="reverse-card" type="button" data-reverse-target="${escapeHtml(result.target)}">
      ${palImage(result.target) ? `<img src="${escapeHtml(palImage(result.target))}" alt="" loading="lazy" decoding="async">` : "<span></span>"}
      <span><strong>${escapeHtml(palName(result.target))}</strong><small>${routeOperationCount(result)} 个操作 · ${cost}</small>${restricted ? `<small class="restricted-note">含 ${restricted} 种同种自繁限定</small>` : ""}${workHtml}<span class="reverse-card-action">生成路线 →</span></span>
    </button><button class="reverse-pin" type="button" data-pin-reverse="${escapeHtml(result.target)}" aria-pressed="${appState.reversePinned.includes(result.target)}">${appState.reversePinned.includes(result.target) ? "已固定" : "对比"}</button></article>`;
  }

  function minimumIndividuals(keys) {
    return [...keys].reduce((sum, key) => sum + (requiresExternalStart(key) ? 2 : 1), 0);
  }

  function workRows(key) {
    return Array.isArray(PALDECK[key] && PALDECK[key].work) ? PALDECK[key].work : [];
  }

  function highWork(key) {
    return workRows(key).filter((item) => Number(item.lv) >= 5).sort((a, b) => Number(b.lv) - Number(a.lv));
  }

  function maxWorkLevel(key) {
    return workRows(key).reduce((max, item) => Math.max(max, Number(item.lv) || 0), 0);
  }

  function workIcon(name) {
    const path = root.WORKICONS && root.WORKICONS[name];
    return path ? `<img class="work-icon" src="${escapeHtml(path)}" alt="">` : "";
  }

  function bindDex() {
    byId("dexSearch").addEventListener("input", () => {
      appState.dexSearch = byId("dexSearch").value;
      scheduleDexRender();
      schedulePersistState();
    });
    byId("dexWork").addEventListener("change", () => {
      appState.dexWork = byId("dexWork").value;
      renderDex();
      schedulePersistState();
    });
    for (const id of ["dexWorkLevel", "dexCombatRole", "dexAcquisition", "dexSort"]) {
      byId(id).addEventListener("change", () => {
        appState.dexWorkLevel = byId("dexWorkLevel").value;
        appState.dexCombatRole = byId("dexCombatRole").value;
        appState.dexAcquisition = byId("dexAcquisition").value;
        appState.dexSort = byId("dexSort").value;
        renderDex();
        schedulePersistState();
      });
    }
    byId("dexOwnOnly").addEventListener("change", () => {
      appState.dexOwnOnly = byId("dexOwnOnly").checked;
      renderDex();
      schedulePersistState();
    });
    byId("dexFavoriteOnly").addEventListener("change", () => {
      appState.dexFavoriteOnly = byId("dexFavoriteOnly").checked;
      renderDex();
      schedulePersistState();
    });
    byId("dexReset").addEventListener("click", resetDexFilters);
    byId("dexElements").addEventListener("click", (event) => {
      const button = event.target.closest("[data-element]");
      if (!button) return;
      const type = button.dataset.element;
      toggleSingleElement(selectedDexElements, type);
      appState.dexElements = [...selectedDexElements];
      renderDexFilters();
      renderDex();
      schedulePersistState();
    });
    byId("dexGrid").addEventListener("click", (event) => {
      if (event.target.closest("[data-reset-dex]")) {
        resetDexFilters();
        return;
      }
      const button = event.target.closest("[data-pal]");
      if (button) showPalDetail(button.dataset.pal);
      if (event.target.closest("[data-show-more-dex]")) {
        dexVisibleCount += 72;
        appState.dexVisibleCount = dexVisibleCount;
        renderDexRows();
        schedulePersistState();
      }
    });
  }

  function resetDexFilters() {
    appState.dexSearch = "";
    appState.dexWork = "";
    appState.dexOwnOnly = false;
    appState.dexFavoriteOnly = false;
    appState.dexElements = [];
    appState.dexWorkLevel = "0";
    appState.dexCombatRole = "";
    appState.dexAcquisition = "";
    appState.dexSort = "number";
    selectedDexElements.clear();
    syncControlsFromState();
    renderDexFilters();
    renderDex();
    schedulePersistState();
  }

  function renderDexFilters() {
    if (!elementsAvailable) {
      selectedDexElements.clear();
      byId("dexElements").innerHTML = '<div class="element-unavailable" role="status">当前数据包未包含已验证元素字段，属性筛选已停用。</div>';
      return;
    }
    renderElementFilterButtons(byId("dexElements"), selectedDexElements);
  }

  function renderDex(options = {}) {
    if (!PD) return;
    dexDirty = false;
    const query = (byId("dexSearch") && byId("dexSearch").value || "").trim().toLowerCase();
    const work = byId("dexWork") ? byId("dexWork").value : "";
    const ownOnly = byId("dexOwnOnly") && byId("dexOwnOnly").checked;
    const favoriteOnly = byId("dexFavoriteOnly") && byId("dexFavoriteOnly").checked;
    const workLevel = Number(byId("dexWorkLevel").value || 0);
    const combatRole = byId("dexCombatRole").value;
    const acquisition = byId("dexAcquisition").value;
    const sort = byId("dexSort").value;
    const hasFilters = Boolean(query || work || workLevel || combatRole || acquisition || ownOnly || favoriteOnly || selectedDexElements.size || sort !== "number");
    const rows = allKeys.filter((key) => {
      if (query && !palSearchText(key).includes(query.replace(/^#/, ""))) return false;
      if (elementsAvailable && selectedDexElements.size && !palTypes(key).some((type) => selectedDexElements.has(type))) return false;
      if (work && !workRows(key).some((item) => item.en === work)) return false;
      if (workLevel && !workRows(key).some((item) => (!work || item.en === work) && Number(item.lv) >= workLevel)) return false;
      if (combatRole && !matchesCombatRole(key, combatRole)) return false;
      if (acquisition === "external" && !requiresExternalStart(key)) return false;
      if (acquisition === "breedable" && requiresExternalStart(key)) return false;
      if (acquisition === "wild" && !hasWildLevelRecord(key)) return false;
      if (ownOnly && !effectiveOwned.has(key)) return false;
      if (favoriteOnly && !appState.favorites.has(key)) return false;
      return true;
    });
    rows.sort(dexSortComparator(sort));
    byId("dexCount").innerHTML = hasFilters
      ? `筛选结果 <strong>${rows.length}</strong> / ${allKeys.length} 只${effectiveOwned.size ? ` · 库存 ${effectiveOwned.size} 种` : ""}`
      : `共 <strong>${allKeys.length}</strong> 只正式帕鲁${effectiveOwned.size ? ` · 库存 ${effectiveOwned.size} 种` : ""}`;
    byId("dexReset").disabled = !hasFilters;
    renderDexFilterSummary(rows.length);
    dexRowsCache = rows;
    dexVisibleCount = options.preserveVisible ? Math.max(72, appState.dexVisibleCount) : 72;
    appState.dexVisibleCount = dexVisibleCount;
    renderDexRows();
  }

  function renderDexRows() {
    const rows = dexRowsCache;
    const visible = rows.slice(0, dexVisibleCount);
    byId("dexGrid").innerHTML = rows.length ? visible.map((key) => `
      <button class="dex-card ${effectiveOwned.has(key) ? "is-owned" : ""} ${appState.favorites.has(key) ? "is-favorite" : ""} ${requiresExternalStart(key) ? "is-restricted" : ""}" type="button" data-pal="${escapeHtml(key)}">
        ${palImage(key) ? `<img src="${escapeHtml(palImage(key))}" alt="" loading="lazy" decoding="async">` : "<span></span>"}
        <span class="dex-card-copy"><strong>${escapeHtml(palName(key))}</strong><small>#${escapeHtml(palNumber(key))} · ${escapeHtml(palEnglish(key))}</small><span class="dex-types">${elementsAvailable ? palTypes(key).map((type) => `<span class="type-badge type-${type}">${escapeHtml(TYPE_LABELS[type] || type)}</span>`).join("") : '<span class="availability-badge">属性字段未验证</span>'}</span>${requiresExternalStart(key) ? '<small class="restricted-note">需先获取两只异性个体</small>' : ""}</span>
      </button>`).join("") + (visible.length < rows.length ? `<button class="dex-load-more" id="dexLoadMore" type="button" data-show-more-dex>继续显示 ${Math.min(72, rows.length - visible.length)} 只<span>已显示 ${visible.length} / ${rows.length}</span></button>` : "") : '<div class="empty-state compact-empty"><img src="images/pals/1.webp" alt=""><h2>没有符合条件的帕鲁</h2><p>当前筛选组合没有结果，可以一键恢复全部图鉴。</p><button class="button secondary" type="button" data-reset-dex>清除全部筛选</button></div>';
  }

  function renderDexFilterSummary(resultCount) {
    const parts = [];
    const query = byId("dexSearch").value.trim();
    const type = [...selectedDexElements][0];
    if (query) parts.push(`搜索：${query}`);
    if (type) parts.push(`属性：${TYPE_LABELS[type]}`);
    if (appState.dexWork) parts.push(`工作：${WORK_LABELS[appState.dexWork]}`);
    if (appState.dexWorkLevel !== "0") parts.push(`等级 ≥ ${appState.dexWorkLevel}`);
    const roleLabels = { attack: "高攻击", tank: "高生存", speed: "高速坐骑", balanced: "均衡战斗" };
    const acquisitionLabels = { breedable: "可跨种配出", external: "需外部起步", wild: "有野外等级记录" };
    const sortLabels = { number: "图鉴编号", combat: "战斗能力", work: "工作能力", speed: "移动速度" };
    if (appState.dexCombatRole) parts.push(`定位：${roleLabels[appState.dexCombatRole]}`);
    if (appState.dexAcquisition) parts.push(`来源：${acquisitionLabels[appState.dexAcquisition]}`);
    if (appState.dexOwnOnly) parts.push("只看已有");
    if (appState.dexFavoriteOnly) parts.push("只看收藏");
    parts.push(`排序：${sortLabels[appState.dexSort]}`);
    byId("dexFilterSummary").innerHTML = `<strong>${resultCount} 只</strong><span>${escapeHtml(parts.join(" · ") || "全部图鉴，无筛选条件")}</span>`;
  }

  function hasWildLevelRecord(key) {
    const pal = PD.pals[key] || {};
    const stats = pal.stats || {};
    return stats.minWildLevel !== null && stats.minWildLevel !== undefined
      || stats.maxWildLevel !== null && stats.maxWildLevel !== undefined;
  }

  function palSpeed(key) {
    const pal = PD.pals[key] || {};
    const stats = pal.stats || {};
    return Math.max(Number(stats.runSpeed) || 0, Number(stats.rideSprintSpeed) || 0, Number(stats.transportSpeed) || 0);
  }

  function dexSortComparator(mode) {
    if (mode === "combat") return (a, b) => combatScore(b) - combatScore(a) || comparePalKeys(a, b);
    if (mode === "work") return (a, b) => maxWorkLevel(b) - maxWorkLevel(a) || workProfile(b).total - workProfile(a).total || comparePalKeys(a, b);
    if (mode === "speed") return (a, b) => palSpeed(b) - palSpeed(a) || comparePalKeys(a, b);
    return comparePalKeys;
  }

  function showPalDetail(key) {
    if (!PD.pals[key]) return;
    const deck = PALDECK[key] || {};
    const work = workRows(key);
    const drops = Array.isArray(deck.drops) ? deck.drops : [];
    const source = acquisitionText(key);
    const breedingAvailability = requiresExternalStart(key)
      ? '<span class="restriction-copy"><strong>无法由其他物种配出</strong><small>库存为零时，至少先捕捉或特殊获取两只异性个体，之后才能同种自繁。</small></span>'
      : "可由其他物种配种路线获得";
    byId("palDialogBody").innerHTML = `
      <div class="detail-hero">
        ${palImage(key) ? `<img src="${escapeHtml(palImage(key))}" alt="${escapeHtml(palName(key))}">` : "<span></span>"}
        <div><p class="eyebrow">#${escapeHtml(palNumber(key))}</p><h2 id="palDialogTitle">${escapeHtml(palName(key))}</h2><p>${escapeHtml(palEnglish(key))}</p><div class="detail-types">${elementsAvailable ? palTypes(key).map((type) => `<span class="type-badge type-${type}">${escapeHtml(TYPE_LABELS[type] || type)}</span>`).join(" ") : '<span class="availability-badge">属性字段未验证</span>'}</div></div>
      </div>
      <dl class="detail-grid">
        <dt>工作适性</dt><dd>${work.length ? work.map((item) => `<span class="work-badge">${workIcon(item.en)}${escapeHtml(item.zh)} ${escapeHtml(item.lv)}</span>`).join(" ") : "—"}</dd>
        <dt>进食量</dt><dd>${deck.food ?? "—"}</dd>
        <dt>帕鲁蛋</dt><dd>${escapeHtml(deck.egg || "—")}</dd>
        <dt>掉落</dt><dd>${drops.length ? drops.map((item) => `${escapeHtml(item.name)} × ${escapeHtml(item.qty)}（${escapeHtml(item.rate)}）`).join("、") : "—"}</dd>
        <dt>获取来源</dt><dd>${escapeHtml(source.text)}</dd>
        <dt>配种起步</dt><dd>${breedingAvailability}</dd>
      </dl>
      ${deck.desc ? `<div class="detail-description">${escapeHtml(deck.desc)}</div>` : ""}
      <div class="detail-actions">
        <button class="button primary" type="button" data-detail-target="${escapeHtml(key)}">立即规划路线</button>
        <button class="button secondary" type="button" data-detail-recipes="${escapeHtml(key)}">查看全部配方</button>
        <button class="button secondary" type="button" data-detail-own="${escapeHtml(key)}">${appState.owned.has(key) ? "移出库存" : effectiveOwned.has(key) ? "加入本世界库存" : "加入库存"}</button>
        <button class="button quiet" type="button" data-detail-favorite="${escapeHtml(key)}">${appState.favorites.has(key) ? "取消收藏" : "收藏"}</button>
      </div>`;
    const dialog = byId("palDialog");
    if (!dialog.open) dialog.showModal();
  }

  function bindTools() {
    byId("lookupChild").addEventListener("click", lookupChild);
    byId("lookupRecipes").addEventListener("click", lookupRecipes);
    byId("recipesOwnedFirst").addEventListener("change", () => {
      appState.recipesOwnedFirst = byId("recipesOwnedFirst").checked;
      persistState();
      if (resolveKey(byId("recipeTargetInput").value)) lookupRecipes();
    });
    for (const id of ["parentAInput", "parentBInput", "recipeTargetInput"]) {
      byId(id).addEventListener("input", () => {
        appState.parentA = byId("parentAInput").value;
        appState.parentB = byId("parentBInput").value;
        appState.recipeTarget = byId("recipeTargetInput").value;
        if (id !== "recipeTargetInput") {
          appState.childLookupRan = false;
          byId("childResults").innerHTML = '<div class="tool-empty">亲本已变化，请重新查询子代。</div>';
        } else {
          appState.recipeLookupRan = false;
          recipeRowsCache = [];
          recipeTargetKey = "";
          byId("recipeResults").innerHTML = '<div class="tool-empty">目标已变化，请重新查看全部配方。</div>';
        }
        schedulePersistState();
      });
    }
    for (const id of ["parentAInput", "parentBInput"]) {
      byId(id).addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          lookupChild();
        }
      });
    }
    byId("recipeTargetInput").addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        lookupRecipes();
      }
    });
    for (const container of [byId("childResults"), byId("recipeResults")]) {
      container.addEventListener("click", (event) => {
        if (event.target.closest("[data-show-more-recipes]")) {
          recipeVisibleCount += RECIPE_PAGE_SIZE;
          appState.recipeVisibleCount = recipeVisibleCount;
          renderRecipeRows();
          schedulePersistState();
          return;
        }
        const pal = event.target.closest("[data-pal]");
        if (pal) showPalDetail(pal.dataset.pal);
        const target = event.target.closest("[data-use-target]");
        if (target) setPlannerTarget(target.dataset.useTarget, true);
      });
    }
  }

  function buildPairIndex() {
    if (pairIndex) return pairIndex;
    pairIndex = new Map();
    for (const child of Object.keys(PD.breed)) {
      for (const pair of PalSolver.pairEntries(PD, child)) {
        const signature = [pair.a, pair.b].sort().join("|");
        if (!pairIndex.has(signature)) pairIndex.set(signature, []);
        pairIndex.get(signature).push({ child, pair });
      }
    }
    return pairIndex;
  }

  function lookupChild() {
    const a = resolveKey(byId("parentAInput").value);
    const b = resolveKey(byId("parentBInput").value);
    if (!a || !b) {
      appState.childLookupRan = false;
      byId("childResults").innerHTML = '<p class="field-error">请为两名亲本选择有效帕鲁。</p>';
      return;
    }
    appState.parentA = byId("parentAInput").value;
    appState.parentB = byId("parentBInput").value;
    appState.childLookupRan = true;
    const rows = buildPairIndex().get([a, b].sort().join("|")) || [];
    byId("childResults").innerHTML = rows.length ? `<div class="formula-list">${rows.map(({ child, pair }) => `
      <div class="formula-row">${formulaPal(pair.a, pair.ga)}<span class="equation-symbol">×</span>${formulaPal(pair.b, pair.gb)}<span class="equation-symbol">→</span>${formulaPal(child, "")}<button class="button quiet" type="button" data-use-target="${escapeHtml(child)}">规划路线</button></div>`).join("")}</div>`
      : '<p class="field-hint">当前数据中没有找到这组亲本的子代记录。</p>';
    persistState();
  }

  function lookupRecipes(options = {}) {
    const target = resolveKey(byId("recipeTargetInput").value);
    if (!target) {
      appState.recipeLookupRan = false;
      byId("recipeResults").innerHTML = '<p class="field-error">请选择有效的目标帕鲁。</p>';
      return;
    }
    appState.recipeTarget = byId("recipeTargetInput").value;
    appState.recipesOwnedFirst = byId("recipesOwnedFirst").checked;
    appState.recipeLookupRan = true;
    let rows = [...PalSolver.pairEntries(PD, target)];
    const ownedFirst = byId("recipesOwnedFirst").checked;
    if (ownedFirst) {
      rows = rows.sort((left, right) => recipeExtraCount(left) - recipeExtraCount(right) || comparePalKeys(left.a, right.a) || comparePalKeys(left.b, right.b));
    }
    recipeRowsCache = rows;
    recipeVisibleCount = options.preserveVisible ? Math.max(RECIPE_PAGE_SIZE, appState.recipeVisibleCount) : RECIPE_PAGE_SIZE;
    appState.recipeVisibleCount = recipeVisibleCount;
    recipeTargetKey = target;
    recipeRestrictionNotice = requiresExternalStart(target) && !effectiveOwned.has(target)
      ? '<div class="route-notice critical-notice"><strong>此目标无法由其他物种配出。</strong> 下方唯一配方是同种自繁；当前无库存时，至少要先捕捉或特殊获取两只异性个体。</div>'
      : "";
    renderRecipeRows();
    persistState();
  }

  function renderRecipeRows() {
    const rows = recipeRowsCache;
    const target = recipeTargetKey;
    if (!target || !rows.length) {
      byId("recipeResults").innerHTML = '<p class="field-hint">当前数据中没有该目标的配方记录。</p>';
      return;
    }
    const visible = rows.slice(0, recipeVisibleCount);
    byId("recipeResults").innerHTML = `
      <p class="field-hint">共 ${rows.length} 条配方，已显示 ${visible.length} 条。库存可用的组合会优先。</p>
      ${recipeRestrictionNotice}
      <div class="formula-list">${visible.map((pair) => `<div class="formula-row">${formulaPal(pair.a, pair.ga)}<span class="equation-symbol">×</span>${formulaPal(pair.b, pair.gb)}<span class="equation-symbol">→</span>${formulaPal(target, "")}<span class="availability-badge">${escapeHtml(recipeRequirement(pair))}</span></div>`).join("")}</div>
      ${visible.length < rows.length ? `<button class="dex-load-more result-load-more" type="button" data-show-more-recipes>继续显示 ${Math.min(RECIPE_PAGE_SIZE, rows.length - visible.length)} 条配方<span>已显示 ${visible.length} / ${rows.length}</span></button>` : ""}
      <button class="button primary" type="button" data-use-target="${escapeHtml(target)}">立即规划此目标路线</button>`;
  }

  function recipeExtraCount(pair) {
    return new Set([pair.a, pair.b].filter((key) => !effectiveOwned.has(key))).size;
  }

  function recipeRequirement(pair) {
    const missing = [pair.a, pair.b].filter((key) => !effectiveOwned.has(key));
    const species = new Set(missing).size;
    if (!species) return "库存物种已齐";
    const individuals = missing.length;
    return `需补 ${species} 种 / 最低 ${individuals} 只`;
  }

  function formulaPal(key, gender) {
    return `<button class="pal-link ${effectiveOwned.has(key) ? "is-owned" : "is-extra"}" type="button" data-pal="${escapeHtml(key)}">${palThumb(key)}<span>${escapeHtml(palName(key))}</span>${gender && gender !== "any" ? `<span class="gender-badge">${escapeHtml(PalSolver.genderLabel(gender))}</span>` : ""}</button>`;
  }

  function bindSettings() {
    byId("exportInventory").addEventListener("click", exportState);
    byId("settingsImport").addEventListener("click", () => openInventoryFile("settings"));
    byId("resetLocalState").addEventListener("click", () => {
      if (!root.confirm("确定清除库存、收藏、最近目标和偏好吗？此操作不会删除游戏存档。")) return;
      if (persistTimer) {
        root.clearTimeout(persistTimer);
        persistTimer = null;
      }
      safeStorageRemove();
      clearResultCaches();
      try {
        root.localStorage.removeItem(THEME_KEY);
      } catch (_) {}
      applyTheme("night", false);
      appState.owned.clear();
      appState.showCrossWorldGenes = false;
      rebuildEffectiveInventory();
      renderCrossWorldToggle();
      appState.favorites.clear();
      appState.recent = [];
      appState.target = "";
      appState.passives = "";
      appState.strategy = PalSolver.STRATEGIES.FASTEST;
      appState.requireOwned = false;
      Object.assign(appState, {
        activeView: "planner",
        inventorySearch: "",
        inventoryOpen: false,
        advancedOpen: false,
        dexSearch: "",
        dexWork: "",
        dexOwnOnly: false,
        dexFavoriteOnly: false,
        dexElements: [],
        dexWorkLevel: "0",
        dexCombatRole: "",
        dexAcquisition: "",
        dexSort: "number",
        reverseOnly5: true,
        reverseWork: "",
        reverseMaxExtra: "2",
        reverseElements: [],
        reverseSort: "cost",
        reversePinned: [],
        parentA: "",
        parentB: "",
        recipeTarget: "",
        recipesOwnedFirst: true,
        plannerRan: false,
        reverseRan: false,
        childLookupRan: false,
        recipeLookupRan: false,
        targetRecommendationMode: "battle",
        targetPickerMode: "battle",
        targetPickerSearch: "",
        targetPickerElements: [],
        homeCombatFilter: "",
        homeWorkFilter: "",
        routeDensity: "comfortable",
        routeHistory: [],
        favoriteRoutes: [],
        routeChecks: {},
        onboardingSeen: false,
        dexVisibleCount: 72,
        reverseVisibleCount: REVERSE_PAGE_SIZE,
        recipeVisibleCount: RECIPE_PAGE_SIZE,
        targetPickerVisibleCount: TARGET_PICKER_PAGE_SIZE,
        targetPickerScrollTop: 0,
        viewScrollPositions: {},
      });
      selectedDexElements.clear();
      selectedReverseElements.clear();
      selectedTargetElements.clear();
      reverseHasRun = false;
      reverseRowsCache = [];
      reverseVisibleCount = REVERSE_PAGE_SIZE;
      recipeRowsCache = [];
      recipeVisibleCount = RECIPE_PAGE_SIZE;
      recipeTargetKey = "";
      targetPickerVisibleCount = TARGET_PICKER_PAGE_SIZE;
      targetPickerDirty = true;
      dexVisibleCount = 72;
      dexDirty = true;
      currentPlan = null;
      syncControlsFromState();
      renderInventory();
      renderRecentTargets();
      renderSavedRouteShelf();
      renderReverseCompareTray();
      applyRouteDensity();
      renderTargetRecommendations();
      renderTargetPickerFilters();
      renderReverseFilters();
      renderDexFilters();
      activateView("planner", { persist: false, focus: false });
      markPlannerDirty("本地状态已清除。", true);
      showToast("本地状态已清除，游戏存档未受影响");
    });
  }

  function exportState() {
    const payload = {
      schema: "pal-breed-helper-state-v6",
      exportedAt: new Date().toISOString(),
      gameVersion: (PD.meta && (PD.meta.gameVersion || PD.meta.version)) || "1.0",
      ownedKeys: [...appState.owned.keys()],
      owned: [...appState.owned.values()].map((item) => ({ ...item, zh: palName(item.key) })),
      favorites: [...appState.favorites],
      recent: appState.recent,
      routeHistory: appState.routeHistory,
      favoriteRoutes: appState.favoriteRoutes,
      routeChecks: appState.routeChecks,
      preferences: {
        strategy: appState.strategy,
        requireOwned: appState.requireOwned,
        passives: appState.passives,
        activeView: appState.activeView,
        dexSearch: appState.dexSearch,
        dexWork: appState.dexWork,
        dexOwnOnly: appState.dexOwnOnly,
        dexFavoriteOnly: appState.dexFavoriteOnly,
        dexElements: [...selectedDexElements],
        dexWorkLevel: appState.dexWorkLevel,
        dexCombatRole: appState.dexCombatRole,
        dexAcquisition: appState.dexAcquisition,
        dexSort: appState.dexSort,
        reverseOnly5: appState.reverseOnly5,
        reverseWork: appState.reverseWork,
        reverseMaxExtra: appState.reverseMaxExtra,
        reverseElements: [...selectedReverseElements],
        reverseSort: appState.reverseSort,
        homeCombatFilter: appState.homeCombatFilter,
        homeWorkFilter: appState.homeWorkFilter,
        routeDensity: appState.routeDensity,
        targetRecommendationMode: appState.targetRecommendationMode,
        targetPickerMode: appState.targetPickerMode,
        targetPickerSearch: appState.targetPickerSearch,
        targetPickerElements: [...selectedTargetElements],
      },
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `帕鲁配种助手-库存-${new Date().toISOString().slice(0, 10)}.json`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    showToast("库存与设置已导出");
  }

  function openInventoryFile(mode) {
    const input = byId("inventoryFile");
    input.dataset.mode = mode;
    input.click();
  }

  function bindGlobalActions() {
    byId("inventoryFile").addEventListener("change", handleInventoryFile);
    byId("closeCopyFallback").addEventListener("click", () => byId("copyFallbackDialog").close());
    byId("plannerResults").addEventListener("click", handleResultClick);
    byId("closePalDialog").addEventListener("click", () => byId("palDialog").close());
    byId("palDialog").addEventListener("click", (event) => {
      const dialog = byId("palDialog");
      if (event.target === dialog) {
        const rect = dialog.getBoundingClientRect();
        const inside = event.clientX >= rect.left && event.clientX <= rect.right && event.clientY >= rect.top && event.clientY <= rect.bottom;
        if (!inside) dialog.close();
        return;
      }
      const targetButton = event.target.closest("[data-detail-target]");
      if (targetButton) {
        dialog.close();
        setPlannerTarget(targetButton.dataset.detailTarget, true);
        return;
      }
      const recipesButton = event.target.closest("[data-detail-recipes]");
      if (recipesButton) {
        dialog.close();
        byId("recipeTargetInput").value = palName(recipesButton.dataset.detailRecipes);
        appState.recipeTarget = byId("recipeTargetInput").value;
        activateView("tools", { focus: false });
        lookupRecipes();
        return;
      }
      const ownButton = event.target.closest("[data-detail-own]");
      if (ownButton) {
        const key = ownButton.dataset.detailOwn;
        if (appState.owned.has(key)) {
          const previous = normalizeInventoryRecord(JSON.parse(JSON.stringify(appState.owned.get(key))), "local");
          appState.owned.delete(key);
          offerUndo("已移出库存，可撤销", () => {
            appState.owned.set(key, previous);
            inventoryChanged(`${palName(key)}已恢复`);
          });
        } else {
          appState.owned.set(key, normalizeInventoryRecord({
            key,
            count: 1,
            source: "manual",
            individuals: [createManualIndividual(key)],
          }, "manual"));
          offerUndo("已加入库存，可撤销", () => {
            appState.owned.delete(key);
            inventoryChanged(`${palName(key)}已移除`);
          });
        }
        inventoryChanged();
        showPalDetail(key);
        return;
      }
      const favoriteButton = event.target.closest("[data-detail-favorite]");
      if (favoriteButton) {
        const key = favoriteButton.dataset.detailFavorite;
        if (appState.favorites.has(key)) appState.favorites.delete(key);
        else appState.favorites.add(key);
        const active = appState.favorites.has(key);
        favoriteButton.textContent = active ? "取消收藏" : "收藏";
        for (const card of byId("dexGrid").querySelectorAll("[data-pal]")) {
          if (card.dataset.pal === key) card.classList.toggle("is-favorite", active);
        }
        dexDirty = dexDirty || appState.dexFavoriteOnly;
        if (appState.dexFavoriteOnly && appState.activeView === "dex") renderDex();
        persistState();
      }
    });
    root.addEventListener("scroll", scheduleScrollMemory, { passive: true });
    root.addEventListener("pagehide", () => {
      rememberActiveViewScroll();
      rememberOpenDialogState();
      persistState();
    });
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "hidden") {
        rememberActiveViewScroll();
        rememberOpenDialogState();
        persistState();
      }
    });
  }

  function bindProductivityActions() {
    byId("mobilePickTarget").addEventListener("click", () => byId("openTargetPicker").click());
    byId("mobileSolve").addEventListener("click", () => {
      if (appState.activeView === "reverse") runReverse();
      else if (appState.activeView === "dex") byId("dexSearch").focus();
      else solvePlanner();
    });
    byId("undoAction").addEventListener("click", () => {
      const action = undoState;
      undoState = null;
      if (undoTimer) root.clearTimeout(undoTimer);
      if (action) action();
      byId("toast").hidden = true;
    });
    document.addEventListener("keydown", (event) => {
      const typing = ["INPUT", "TEXTAREA", "SELECT"].includes(event.target.tagName) || event.target.isContentEditable;
      if (event.key === "/" && !typing) {
        event.preventDefault();
        const field = appState.activeView === "dex" ? byId("dexSearch") : appState.activeView === "reverse" ? byId("reverseWork") : byId("targetInput");
        field.focus();
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z" && undoState && !typing) {
        event.preventDefault();
        byId("undoAction").click();
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        const field = appState.activeView === "dex" ? byId("dexSearch") : byId("targetInput");
        field.focus();
        field.select();
      }
      if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
        event.preventDefault();
        if (appState.activeView === "reverse") runReverse();
        else if (appState.activeView === "planner") solvePlanner();
      }
      if (event.altKey && /^[1-5]$/.test(event.key)) {
        event.preventDefault();
        activateView(["planner", "reverse", "dex", "tools", "settings"][Number(event.key) - 1], { focus: true });
      }
    });
    updateMobileActionBar();
  }

  function updateMobileActionBar() {
    const bar = byId("mobileActionBar");
    const action = byId("mobileSolve");
    const pick = byId("mobilePickTarget");
    if (!bar || !action || !pick) return;
    bar.hidden = !["planner", "reverse", "dex"].includes(appState.activeView);
    if (appState.activeView === "reverse") {
      pick.hidden = true;
      action.textContent = reverseHasRun ? "重新反查" : "开始反查";
    } else if (appState.activeView === "dex") {
      pick.hidden = true;
      action.textContent = "搜索图鉴";
    } else {
      pick.hidden = false;
      const key = resolveKey(byId("targetInput")?.value || appState.target);
      action.textContent = key ? `生成${palName(key)}路线` : "请先选择目标";
      action.disabled = !key;
      return;
    }
    action.disabled = appState.activeView === "reverse" && !effectiveOwned.size;
  }

  function showOnboardingIfNeeded() {
    const dialog = byId("onboardingDialog");
    byId("finishOnboarding").addEventListener("click", () => {
      appState.onboardingSeen = true;
      persistState();
      dialog.close();
      byId("openTargetPicker").focus();
    });
    byId("dismissOnboarding").addEventListener("click", () => dialog.close());
    if (!appState.onboardingSeen && !dialog.open) dialog.showModal();
  }

  function offerUndo(message, action) {
    undoState = typeof action === "function" ? action : null;
    if (undoTimer) root.clearTimeout(undoTimer);
    showToast(message, Boolean(undoState));
    undoTimer = root.setTimeout(() => {
      undoState = null;
      byId("undoAction").hidden = true;
    }, 7000);
  }

  function handleResultClick(event) {
    const pal = event.target.closest("[data-pal]");
    if (pal) {
      showPalDetail(pal.dataset.pal);
      return;
    }
    const recipes = event.target.closest("[data-open-recipes]");
    if (recipes) {
      byId("recipeTargetInput").value = palName(recipes.dataset.openRecipes);
      appState.recipeTarget = byId("recipeTargetInput").value;
      activateView("tools", { focus: false });
      lookupRecipes();
    }
  }

  function handleInventoryFile(event) {
    const file = event.target.files && event.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const data = JSON.parse(reader.result);
        importStatePayload(data);
      } catch (error) {
        showToast(`导入失败：${error.message || "不是有效 JSON"}`);
      }
    };
    reader.onerror = () => showToast("文件读取失败");
    reader.readAsText(file, "utf-8");
    event.target.value = "";
  }

  function importStatePayload(data) {
    const rows = [];
    if (Array.isArray(data.owned)) {
      for (const item of data.owned) {
        if (typeof item === "string") rows.push({ key: item, count: null });
        else if (item && item.key !== undefined) rows.push(item);
      }
    } else if (Array.isArray(data.ownedKeys)) {
      for (const key of data.ownedKeys) rows.push({ key, count: null, source: "import" });
    } else if (data.state && Array.isArray(data.state.owned)) {
      for (const item of data.state.owned) rows.push(typeof item === "string" ? { key: item } : item);
    }
    if (!rows.length) throw new Error("文件中没有 owned 或 ownedKeys 库存数据");
    let added = 0;
    let updated = 0;
    let unknown = 0;
    for (const item of rows) {
      const key = String(item.key || "");
      if (!PD.pals[key]) {
        unknown += 1;
        continue;
      }
      if (appState.owned.has(key)) updated += 1;
      else added += 1;
      appState.owned.set(key, normalizeInventoryRecord(item, "import"));
    }
    if (Array.isArray(data.favorites)) appState.favorites = new Set(data.favorites.map(String).filter((key) => PD.pals[key]));
    if (Array.isArray(data.recent)) appState.recent = data.recent.map(String).filter((key) => PD.pals[key]).slice(0, 6);
    if (Array.isArray(data.routeHistory)) appState.routeHistory = data.routeHistory.filter((item) => item && PD.pals[item.target]).slice(0, 8);
    if (Array.isArray(data.favoriteRoutes)) appState.favoriteRoutes = data.favoriteRoutes.filter((item) => item && PD.pals[item.target]).slice(0, 20);
    if (data.routeChecks && typeof data.routeChecks === "object") appState.routeChecks = data.routeChecks;
    const preferences = data.preferences || {};
    if (Object.values(PalSolver.STRATEGIES).includes(preferences.strategy)) appState.strategy = preferences.strategy;
    if (typeof preferences.requireOwned === "boolean") appState.requireOwned = preferences.requireOwned;
    if (typeof preferences.passives === "string") appState.passives = preferences.passives;
    if (["planner", "reverse", "dex", "tools", "settings"].includes(preferences.activeView)) appState.activeView = preferences.activeView;
    if (typeof preferences.dexSearch === "string") appState.dexSearch = preferences.dexSearch;
    if (WORKS.some(([value]) => value === preferences.dexWork)) appState.dexWork = preferences.dexWork;
    if (["0", "3", "4", "5"].includes(String(preferences.dexWorkLevel))) appState.dexWorkLevel = String(preferences.dexWorkLevel);
    if (["", "attack", "tank", "speed", "balanced"].includes(preferences.dexCombatRole)) appState.dexCombatRole = preferences.dexCombatRole;
    if (["", "breedable", "external", "wild"].includes(preferences.dexAcquisition)) appState.dexAcquisition = preferences.dexAcquisition;
    if (["number", "combat", "work", "speed"].includes(preferences.dexSort)) appState.dexSort = preferences.dexSort;
    if (typeof preferences.dexOwnOnly === "boolean") appState.dexOwnOnly = preferences.dexOwnOnly;
    if (typeof preferences.dexFavoriteOnly === "boolean") appState.dexFavoriteOnly = preferences.dexFavoriteOnly;
    if (Array.isArray(preferences.dexElements)) appState.dexElements = normalizeElementSelection(preferences.dexElements);
    if (typeof preferences.reverseOnly5 === "boolean") appState.reverseOnly5 = preferences.reverseOnly5;
    if (WORKS.some(([value]) => value === preferences.reverseWork)) appState.reverseWork = preferences.reverseWork;
    if (["0", "1", "2", "3", "4"].includes(String(preferences.reverseMaxExtra))) appState.reverseMaxExtra = String(preferences.reverseMaxExtra);
    if (Array.isArray(preferences.reverseElements)) appState.reverseElements = normalizeElementSelection(preferences.reverseElements);
    if (["cost", "operations", "work", "combat", "number"].includes(preferences.reverseSort)) appState.reverseSort = preferences.reverseSort;
    if (["", "attack", "tank", "speed", "balanced"].includes(preferences.homeCombatFilter)) appState.homeCombatFilter = preferences.homeCombatFilter;
    if (WORKS.some(([value]) => value === preferences.homeWorkFilter)) appState.homeWorkFilter = preferences.homeWorkFilter;
    if (["comfortable", "compact"].includes(preferences.routeDensity)) appState.routeDensity = preferences.routeDensity;
    if (["battle", "work"].includes(preferences.targetRecommendationMode)) appState.targetRecommendationMode = preferences.targetRecommendationMode;
    if (["battle", "work", "all"].includes(preferences.targetPickerMode)) appState.targetPickerMode = preferences.targetPickerMode;
    if (typeof preferences.targetPickerSearch === "string") appState.targetPickerSearch = preferences.targetPickerSearch;
    if (Array.isArray(preferences.targetPickerElements)) appState.targetPickerElements = normalizeElementSelection(preferences.targetPickerElements);
    syncControlsFromState();
    renderTargetRecommendations();
    renderTargetPickerFilters();
    renderReverseFilters();
    renderDexFilters();
    renderRecentTargets();
    renderSavedRouteShelf();
    applyRouteDensity();
    inventoryChanged();
    activateView(appState.activeView, { focus: false });
    showToast(`导入完成：新增 ${added} 种，更新 ${updated} 种${unknown ? `，跳过 ${unknown} 种未识别` : ""}`);
  }

  async function copyText(value, successMessage) {
    if (!value) return;
    let success = false;
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(value);
        success = true;
      }
    } catch (_) {
      success = false;
    }
    if (!success) {
      const area = document.createElement("textarea");
      area.value = value;
      area.setAttribute("readonly", "");
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      try {
        success = document.execCommand("copy");
      } catch (_) {
        success = false;
      }
      area.remove();
    }
    if (success) {
      showToast(successMessage);
      return;
    }
    const dialog = byId("copyFallbackDialog");
    const fallback = byId("copyFallbackText");
    fallback.value = value;
    dialog.showModal();
    root.setTimeout(() => {
      fallback.focus();
      fallback.select();
    }, 0);
    showToast("文本已打开并全选");
  }

  function showToast(message, allowUndo = false) {
    const toast = byId("toast");
    byId("toastMessage").textContent = message;
    byId("undoAction").hidden = !allowUndo;
    toast.hidden = false;
    if (toastTimer) root.clearTimeout(toastTimer);
    toastTimer = root.setTimeout(() => {
      toast.hidden = true;
    }, allowUndo ? 7000 : 2600);
  }
})(typeof window !== "undefined" ? window : globalThis);
