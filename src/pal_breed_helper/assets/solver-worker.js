self.window = self;
importScripts("data/breeding.js", "app.js");

function solvePlanOptions(payload) {
  return self.PalSolver.solveRoutes({
    pd: self.PD,
    owned: payload.owned || [],
    target: payload.target,
    strategy: payload.strategy,
    requireOwned: Boolean(payload.requireOwned),
    limit: 2,
  }) || [];
}

self.addEventListener("message", (event) => {
  const request = event.data || {};
  try {
    let result;
    if (request.kind === "plan-options") result = solvePlanOptions(request.payload || {});
    else if (request.kind === "discover") {
      result = self.PalSolver.discoverRoutes({
        pd: self.PD,
        owned: request.payload && request.payload.owned || [],
        strategy: self.PalSolver.STRATEGIES.FEW_EXTRA,
        frontierLimit: 1,
        maxIterations: 9,
      });
    } else throw new Error("未知求解任务");
    self.postMessage({ id: request.id, result });
  } catch (error) {
    self.postMessage({ id: request.id, error: error && error.message || "后台计算失败" });
  }
});
