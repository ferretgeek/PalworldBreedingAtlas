"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { performance } = require("node:perf_hooks");

const projectRoot = path.resolve(__dirname, "..");
const solver = require(path.join(projectRoot, "src", "pal_breed_helper", "assets", "app.js"));
const breedingPath = path.join(projectRoot, "src", "pal_breed_helper", "assets", "data", "breeding.js");

function loadBreedingData() {
  const context = { window: {} };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(breedingPath, "utf8"), context);
  return context.window.PD;
}

const knownInventory = [
  "77", "11", "1", "2", "12", "17", "29", "3", "14", "9", "28", "22", "20", "6", "13", "7",
  "37", "10", "19", "34", "27", "59", "21", "87", "63", "42", "47", "35", "58", "56", "15", "4",
  "5", "33", "60", "23B", "103", "61", "18", "32", "78", "51", "38", "89", "44", "44B", "49", "107",
  "102B", "75", "80", "94", "91B", "88", "73", "69", "67", "71", "82", "145", "109", "108", "26", "43B", "68",
];

function run() {
  assert.equal(solver.STRATEGIES.BALANCED, "balanced");
  assert.equal(typeof solver.combineInventoryRecords, "function", "库存合并应导出为可独立回归的纯函数");
  const worldInventory = [
    {
      key: "1",
      count: 2,
      world: 2,
      box: 0,
      individuals: [{ id: "world-1", source: "world", gender: "male" }],
    },
    { key: "3", count: 1, world: 1, box: 0, individuals: [] },
  ];
  const crossWorldGenes = [
    {
      key: "1",
      count: 3,
      world: 0,
      box: 3,
      individuals: [{ id: "cross-world-1", source: "crossWorldGenes", gender: "female" }],
    },
    {
      key: "2",
      count: 4,
      world: 0,
      box: 4,
      individuals: [{ id: "cross-world-2", source: "crossWorldGenes", gender: "male" }],
    },
  ];
  const worldSnapshot = JSON.parse(JSON.stringify(worldInventory));
  const geneSnapshot = JSON.parse(JSON.stringify(crossWorldGenes));

  const defaultInventory = solver.combineInventoryRecords(worldInventory, crossWorldGenes, false);
  const defaultByKey = new Map(defaultInventory.map((item) => [item.key, item]));
  assert.deepEqual([...defaultByKey.keys()], ["1", "3"], "默认库存不得混入跨界基因物种");
  assert.equal(defaultByKey.get("1").count, 2, "默认库存不得叠加同种跨界基因数量");
  assert.deepEqual(defaultByKey.get("1").individuals.map((item) => item.id), ["world-1"]);

  const visibleInventory = solver.combineInventoryRecords(worldInventory, crossWorldGenes, true);
  const visibleByKey = new Map(visibleInventory.map((item) => [item.key, item]));
  assert.equal(visibleByKey.size, 3);
  assert.equal(visibleByKey.get("1").count, 5, "显示跨界基因时应合并同种数量");
  assert.equal(visibleByKey.get("1").world, 2);
  assert.equal(visibleByKey.get("1").box, 3);
  assert.equal(visibleByKey.get("1").crossWorldCount, 3);
  assert.notEqual(visibleByKey.get("1").crossWorldOnly, true, "世界内也持有的同种记录不能标成仅跨界");
  assert.deepEqual(
    visibleByKey.get("1").individuals.map((item) => item.id),
    ["world-1", "cross-world-1"],
    "显示跨界基因时应保留两个来源的个体",
  );
  assert.equal(visibleByKey.get("2").count, 4);
  assert.equal(visibleByKey.get("2").crossWorldCount, 4);
  assert.equal(visibleByKey.get("2").crossWorldOnly, true, "只存在于跨界基因的物种必须显式标记");
  assert.deepEqual(worldInventory, worldSnapshot, "纯合并函数不得修改世界库存输入");
  assert.deepEqual(crossWorldGenes, geneSnapshot, "纯合并函数不得修改跨界基因输入");

  assert.deepEqual(solver.normalizePair(["1", "2"]), { a: "1", b: "2", ga: "", gb: "", legacy: true });
  assert.deepEqual(solver.normalizePair({ a: "1", b: "2", ga: "M", gb: "F" }), {
    a: "1", b: "2", ga: "male", gb: "female", legacy: false,
  });
  assert.deepEqual(solver.normalizePair(["79", "78", { parent1Gender: "FEMALE", parent2Gender: "MALE" }]), {
    a: "79", b: "78", ga: "female", gb: "male", legacy: false,
  });
  assert.deepEqual(solver.normalizePair(["79", "78", { parent1Gender: "WILDCARD", parent2Gender: "FEMALE" }]), {
    a: "79", b: "78", ga: "any", gb: "female", legacy: false,
  });

  const genderSchemaPd = {
    pals: { "78": {}, "79": {}, "78B": {}, "79B": {} },
    breed: {
      "79B": [["79", "78", { parent1Gender: "FEMALE", parent2Gender: "MALE" }]],
      "78B": [["79", "78", { parent1Gender: "MALE", parent2Gender: "FEMALE" }]],
    },
  };
  assert.deepEqual(solver.pairEntries(genderSchemaPd, "79B")[0], {
    a: "79", b: "78", ga: "female", gb: "male", legacy: false,
  });
  assert.deepEqual(solver.pairEntries(genderSchemaPd, "78B")[0], {
    a: "79", b: "78", ga: "male", gb: "female", legacy: false,
  });
  const balancedRoute = solver.solveRoute({
    pd: genderSchemaPd,
    owned: ["79", "78"],
    target: "79B",
    strategy: solver.STRATEGIES.BALANCED,
  });
  assert.ok(balancedRoute, "综合权衡策略应返回可行路线");
  assert.equal(balancedRoute.strategy, solver.STRATEGIES.BALANCED);

  const ownedO = solver.__test.baseState("O", "owned");
  const ownedP = solver.__test.baseState("P", "owned");
  const externalB = solver.__test.baseState("B", "extra");
  const producedB = solver.__test.combineStates("B", { a: "O", b: "P", ga: "", gb: "", legacy: true }, ownedO, ownedP);
  const xUsingExternalB = solver.__test.combineStates("X", { a: "B", b: "O", ga: "", gb: "", legacy: true }, externalB, ownedO);
  assert.ok(xUsingExternalB.extra.has("B"));
  const selfProducedB = solver.__test.combineStates("B", { a: "B", b: "B", ga: "any", gb: "any", legacy: false }, externalB, externalB);
  assert.ok(selfProducedB.extra.has("B"), "自己繁育自己不能消除首次获取该物种的需求");
  const mergedDag = solver.__test.combineStates("T", { a: "X", b: "B", ga: "", gb: "", legacy: true }, xUsingExternalB, producedB);
  assert.equal(mergedDag.extra.has("B"), false, "另一分支已经产出的 B 不应继续计入额外获取");
  assert.ok(mergedDag.produced.has("B"));
  const mergedOrder = solver.orderedOperations(mergedDag).map((item) => item.child);
  assert.ok(mergedOrder.indexOf("B") < mergedOrder.indexOf("X"), "被复用的产物必须排在依赖它的操作之前");
  const externalA = solver.__test.baseState("A", "extra");
  const aFromB = solver.__test.combineStates("A", { a: "B", b: "B", ga: "", gb: "", legacy: true }, externalB, externalB);
  const bFromA = solver.__test.combineStates("B", { a: "A", b: "A", ga: "", gb: "", legacy: true }, externalA, externalA);
  const cyclicBranches = solver.__test.combineStates("T", { a: "A", b: "B", ga: "", gb: "", legacy: true }, aFromB, bFromA);
  assert.ok(cyclicBranches.extra.size >= 1, "互相依赖的产物不能把全部首次获取需求错误抵消");

  const pd = loadBreedingData();
  const started = performance.now();
  solver.pairEntries(pd, "1");
  const fastestStarted = performance.now();
  const routeOptions = solver.solveRoutes({
    pd,
    owned: knownInventory,
    target: "175",
    strategy: solver.STRATEGIES.FASTEST,
    limit: 3,
  });
  const fastestElapsed = performance.now() - fastestStarted;
  assert.ok(Array.isArray(routeOptions) && routeOptions.length >= 1, "多路线接口应至少返回一条可行路线");
  assert.equal(routeOptions[0].operations.size, 1, "最快成型应直接选择一步亲本配方");
  assert.ok(fastestElapsed < 150, `最快成型直达计算耗时过长：${Math.round(fastestElapsed)}ms`);
  assert.equal(new Set(routeOptions.map((item) => item.hash)).size, routeOptions.length, "多路线结果必须去重");
  assert.ok(routeOptions.length <= 3, "多路线接口必须遵守数量上限");
  if (pd.breed["79B"] && pd.breed["78B"]) {
    const child79B = solver.pairEntries(pd, "79B").find((pair) => pair.a === "79" && pair.b === "78");
    const child78B = solver.pairEntries(pd, "78B").find((pair) => pair.a === "79" && pair.b === "78");
    assert.deepEqual([child79B.ga, child79B.gb], ["female", "male"], "79♀×78♂应产出79B");
    assert.deepEqual([child78B.ga, child78B.gb], ["male", "female"], "79♂×78♀应产出78B");
  }
  const regressionCases = [
    ["175", 11, "沁莲龙"],
    ["182", 10, "墨罗娜"],
  ];
  const routeTimes = [];
  for (const [target, maxOperations, name] of regressionCases) {
    if (!pd.pals[target]) continue;
    const routeStarted = performance.now();
    const result = solver.solveRoute({
      pd,
      owned: knownInventory,
      target,
      strategy: solver.STRATEGIES.ZERO_EXTRA,
    });
    routeTimes.push({ name, ms: performance.now() - routeStarted });
    assert.ok(result, `${name}应存在零补充路线`);
    assert.equal(result.extra.size, 0, `${name}不应要求额外获取`);
    assert.ok(result.operations.size <= maxOperations, `${name}应不超过${maxOperations}个去重操作，实际${result.operations.size}`);
    assert.equal(solver.orderedOperations(result).length, result.operations.size, `${name}展示步数必须等于求解计分步数`);
  }

  const objectSchemaPd = {
    pals: { T: { zh: "目标" }, B: { zh: "亲本" } },
    breed: { T: [{ a: "T", b: "B", ga: "F", gb: "M" }], B: [["B", "B"]] },
  };
  const ownedTargetResult = solver.solveRoute({
    pd: objectSchemaPd,
    owned: ["T", "B"],
    target: "T",
    strategy: solver.STRATEGIES.ZERO_EXTRA,
  });
  assert.ok(ownedTargetResult, "已经拥有目标时仍应允许继续繁育");
  assert.equal(ownedTargetResult.operations.size, 1);
  const [operation] = solver.orderedOperations(ownedTargetResult);
  assert.equal(operation.ga, "female");
  assert.equal(operation.gb, "male");

  const elapsed = performance.now() - started;
  const slowestRoute = Math.max(...routeTimes.map((item) => item.ms));
  assert.ok(slowestRoute < 1800, `零补充单次求解耗时过长：${Math.round(slowestRoute)}ms`);
  assert.ok(elapsed < 3000, `核心回归测试耗时过长：${Math.round(elapsed)}ms`);
  console.log(`solver tests passed in ${Math.round(elapsed)}ms; routes ${routeTimes.map((item) => `${item.name} ${Math.round(item.ms)}ms`).join(", ")}`);
}

run();
