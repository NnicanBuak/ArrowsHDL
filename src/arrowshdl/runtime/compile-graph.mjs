// Bundled GraphDLC MIT cycle optimizer; see ../vendor/graphdlc/LICENSE.

// compile-graph.ts
import fs from "node:fs";

// headless-scheduler.ts
var queuedTasks = [];
var AsyncScheduler = class {
  constructor(_budget) {
  }
  schedule(task, _done, _owner) {
    queuedTasks.push(task);
  }
  clear() {
    queuedTasks.length = 0;
  }
};
function drainTasks() {
  let budget = 1e7;
  while (queuedTasks.length) {
    const task = queuedTasks.shift();
    while (!task.step(1e4)) {
      budget -= 1e4;
      if (budget <= 0) throw new Error("\u041F\u0440\u0435\u0432\u044B\u0448\u0435\u043D \u0431\u044E\u0434\u0436\u0435\u0442 \u043F\u043E\u0438\u0441\u043A\u0430 \u043A\u043E\u043B\u0435\u0446; \u0438\u0441\u043F\u043E\u043B\u044C\u0437\u0443\u0439\u0442\u0435 --no-cycles");
    }
  }
}

// ../vendor/graphdlc/ts/src/core/graph/engines/core/NodeType.ts
var NodeTypes;
((NodeTypes2) => {
  NodeTypes2.PATH_TYPES = [
    1 /* ARROW */,
    6 /* SPLITTER_UP_DOWN */,
    7 /* SPLITTER_UP_RIGHT */,
    8 /* SPLITTER_UP_RIGHT_LEFT */,
    10 /* BLUE_ARROW */,
    11 /* DIAGONAL_ARROW */,
    12 /* SPLITTER_UP_UP */,
    13 /* SPLITTER_RIGHT_UP */,
    14 /* SPLITTER_UP_DIAGONAL */,
    22 /* LEVEL_SOURCE */,
    23 /* LEVEL_TARGET */
  ];
  function fromArrowType(type) {
    switch (type) {
      case 0 /* EMPTY */:
        return 0 /* EMPTY */;
      case 1 /* ARROW */:
      case 6 /* SPLITTER_UP_DOWN */:
      case 7 /* SPLITTER_UP_RIGHT */:
      case 8 /* SPLITTER_UP_RIGHT_LEFT */:
      case 10 /* BLUE_ARROW */:
      case 11 /* DIAGONAL_ARROW */:
      case 12 /* SPLITTER_UP_UP */:
      case 13 /* SPLITTER_RIGHT_UP */:
      case 14 /* SPLITTER_UP_DIAGONAL */:
      case 22 /* LEVEL_SOURCE */:
      case 23 /* LEVEL_TARGET */:
        return 1 /* PATH */;
      case 2 /* SOURCE */:
        return 2 /* SOURCE */;
      case 3 /* BLOCKER */:
        return 3 /* BLOCKER */;
      case 4 /* DELAY */:
        return 4 /* DELAY */;
      case 5 /* DETECTOR */:
        return 5 /* DETECTOR */;
      case 9 /* IMPULSE */:
        return 6 /* IMPULSE */;
      case 15 /* LOGIC_NOT */:
        return 7 /* LOGIC_NOT */;
      case 16 /* LOGIC_AND */:
        return 8 /* LOGIC_AND */;
      case 17 /* LOGIC_XOR */:
        return 9 /* LOGIC_XOR */;
      case 18 /* LATCH */:
        return 10 /* LATCH */;
      case 19 /* FLIP_FLOP */:
        return 11 /* FLIP_FLOP */;
      case 20 /* RANDOM */:
        return 12 /* RANDOM */;
      case 21 /* BUTTON */:
        return 13 /* BUTTON */;
      case 24 /* DIRECTIONAL_BUTTON */:
        return 14 /* DIRECTIONAL_BUTTON */;
      default:
        return 0 /* EMPTY */;
    }
  }
  NodeTypes2.fromArrowType = fromArrowType;
  function isEntryPoint(type) {
    return type === 2 /* SOURCE */ || type === 6 /* IMPULSE */ || type === 7 /* LOGIC_NOT */ || type === 13 /* BUTTON */ || type === 14 /* DIRECTIONAL_BUTTON */;
  }
  NodeTypes2.isEntryPoint = isEntryPoint;
  function isAdditionalUpdate(type) {
    return type === 4 /* DELAY */ || type === 6 /* IMPULSE */ || type === 11 /* FLIP_FLOP */ || type === 12 /* RANDOM */;
  }
  NodeTypes2.isAdditionalUpdate = isAdditionalUpdate;
})(NodeTypes || (NodeTypes = {}));

// ../vendor/graphdlc/ts/src/core/graph/ast/cycle/utils.ts
var ALLOWED_IN_CYCLE = /* @__PURE__ */ new Set([1 /* PATH */, 9 /* LOGIC_XOR */]);
function canBeInCycle(node) {
  return ALLOWED_IN_CYCLE.has(node.type);
}

// ../vendor/graphdlc/ts/src/core/graph/ast/cycle/CycleSearchTask.ts
var CycleSearchTask = class {
  constructor(onCycleFound, onIdle) {
    this.onCycleFound = onCycleFound;
    this.onIdle = onIdle;
  }
  onCycleFound;
  onIdle;
  isCanceled = false;
  candidateQueue = [];
  candidateHead = 0;
  queueSet = /* @__PURE__ */ new Set();
  pathStack = [];
  edgeIndexStack = [];
  inPathSet = /* @__PURE__ */ new Set();
  pushCandidate(node) {
    if (!this.queueSet.has(node)) {
      this.queueSet.add(node);
      this.candidateQueue.push(node);
    }
  }
  clear() {
    this.candidateQueue.length = 0;
    this.candidateHead = 0;
    this.queueSet.clear();
    this.resetDFS();
  }
  compactQueue() {
    if (this.candidateHead > 500) {
      this.candidateQueue.splice(0, this.candidateHead);
      this.candidateHead = 0;
    }
  }
  step(maxStepsCount) {
    if (this.isCanceled) return true;
    let stepsRun = 0;
    while (stepsRun < maxStepsCount) {
      if (this.pathStack.length === 0) {
        if (this.candidateHead >= this.candidateQueue.length) {
          this.clear();
          this.onIdle();
          return true;
        }
        this.compactQueue();
        const root = this.candidateQueue[this.candidateHead++];
        this.queueSet.delete(root);
        if (canBeInCycle(root)) {
          this.resetDFS();
          this.pushToPath(root);
        } else {
          continue;
        }
      }
      while (this.pathStack.length > 0 && stepsRun < maxStepsCount) {
        stepsRun++;
        const depth = this.pathStack.length - 1;
        const current = this.pathStack[depth];
        const edgeIdx = this.edgeIndexStack[depth];
        if (!canBeInCycle(current)) {
          this.popFromPath();
          continue;
        }
        const links = current.links;
        if (edgeIdx >= links.length) {
          this.popFromPath();
          continue;
        }
        const next = links[edgeIdx];
        this.edgeIndexStack[depth]++;
        if (this.inPathSet.has(next)) {
          const cycleStartIdx = this.pathStack.indexOf(next);
          if (cycleStartIdx !== -1) {
            const cycleLen = this.pathStack.length - cycleStartIdx;
            if (cycleLen >= 2) {
              this.onCycleFound(
                this.pathStack.slice(cycleStartIdx)
              );
            }
          }
          continue;
        }
        if (canBeInCycle(next)) {
          this.pushToPath(next);
        }
      }
    }
    return false;
  }
  getResult() {
    return;
  }
  resetDFS() {
    this.pathStack.length = 0;
    this.edgeIndexStack.length = 0;
    this.inPathSet.clear();
  }
  pushToPath(node) {
    this.pathStack.push(node);
    this.edgeIndexStack.push(0);
    this.inPathSet.add(node);
  }
  popFromPath() {
    const node = this.pathStack.pop();
    this.edgeIndexStack.pop();
    if (node) {
      this.inPathSet.delete(node);
    }
  }
};

// ../vendor/graphdlc/ts/src/core/graph/ast/cycle/CycleManager.ts
var CycleManager = class {
  scheduler = new AsyncScheduler(() => 16);
  activeTask = null;
  internalCycles = /* @__PURE__ */ new Map();
  validationSet = /* @__PURE__ */ new Set();
  getOrCreateTask(graph) {
    if (this.activeTask === null) {
      this.activeTask = new CycleSearchTask(
        (path) => this.handleCycleCandidate(graph, path),
        () => {
          this.activeTask = null;
        }
      );
      this.scheduler.schedule(this.activeTask, () => {
      }, this);
    }
    return this.activeTask;
  }
  getCycleKey(path) {
    const len = path.length;
    let minIdx = 0;
    let minVal = path[0].nodeIdx;
    for (let i = 1; i < len; i++) {
      if (path[i].nodeIdx < minVal) {
        minVal = path[i].nodeIdx;
        minIdx = i;
      }
    }
    let key = "";
    for (let i = 0; i < len; i++) {
      const node = path[(minIdx + i) % len];
      key += `${node.nodeIdx}>`;
    }
    return key;
  }
  resetNodeCycleInfo(node) {
    node.cycle = null;
  }
  assignCycleHead(headNode, cycle, headType, offset, extraPath = []) {
    headNode.cycle = {
      ref: cycle,
      headType,
      offset,
      isBody: false
    };
    cycle.heads.push(headNode);
    const cycleLen = cycle.nodes.length;
    const pathLen = extraPath.length;
    for (let i = 0; i < pathLen; i++) {
      const extraNode = extraPath[i];
      const rawOffset = offset + pathLen - i - 1;
      const normalizedOffset = (rawOffset % cycleLen + cycleLen) % cycleLen;
      extraNode.cycle = {
        ref: cycle,
        headType: 0 /* NONE */,
        offset: normalizedOffset,
        isBody: false
      };
      cycle.extraNodes.push(extraNode);
    }
  }
  findReadHead(node, cycleSet) {
    let current = node;
    let distance = 0;
    const extraPath = [];
    const visitedPath = /* @__PURE__ */ new Set();
    while (current.type === 1 /* PATH */ || current.type === 5 /* DETECTOR */) {
      if (current.links.length !== 1) return null;
      if (current.backLinks.length !== 1 && current.type === 1 /* PATH */)
        return null;
      const next = current.links[0];
      if (cycleSet.has(next)) return null;
      if (visitedPath.has(current)) {
        return null;
      }
      visitedPath.add(current);
      extraPath.push(current);
      current = next;
      distance++;
    }
    if (current.type !== 8 /* LOGIC_AND */) {
      return null;
    }
    return {
      node: current,
      extraPath,
      distance
    };
  }
  refreshCycleIO(cycle, graph) {
    const { heads, extraNodes, nodes: cycleNodes } = cycle;
    const affectedNodesToUpdate = [];
    if (graph) {
      for (let i = 0; i < heads.length; i++) {
        affectedNodesToUpdate.push(heads[i]);
      }
      for (let i = 0; i < extraNodes.length; i++) {
        affectedNodesToUpdate.push(extraNodes[i]);
      }
    }
    for (let i = 0; i < heads.length; i++) {
      this.resetNodeCycleInfo(heads[i]);
    }
    heads.length = 0;
    for (let i = 0; i < extraNodes.length; i++) {
      this.resetNodeCycleInfo(extraNodes[i]);
    }
    extraNodes.length = 0;
    const cycleSet = this.validationSet;
    cycleSet.clear();
    const cycleLen = cycleNodes.length;
    for (let i = 0; i < cycleLen; i++) {
      cycleSet.add(cycleNodes[i]);
    }
    try {
      for (let i = 0; i < cycleLen; i++) {
        const node = cycleNodes[cycleLen - i - 1];
        if (node.cycle !== null) {
          node.cycle.offset = i;
        }
        for (let j = 0; j < node.links.length; j++) {
          const linkedNode = node.links[j];
          if (cycleSet.has(linkedNode)) continue;
          const readHead = this.findReadHead(linkedNode, cycleSet);
          if (readHead !== null) {
            const offset = (i - readHead.distance + cycleLen) % cycleLen;
            this.assignCycleHead(
              readHead.node,
              cycle,
              1 /* READ */,
              offset,
              readHead.extraPath
            );
          }
        }
        for (let j = 0; j < node.backLinks.length; j++) {
          const backLinkedNode = node.backLinks[j];
          if (!cycleSet.has(backLinkedNode)) {
            const offset = (i + 1) % cycleLen;
            let headType = 2 /* WRITE */;
            if (backLinkedNode.type === 3 /* BLOCKER */) {
              headType = 3 /* CLEAR */;
            } else if (node.type === 9 /* LOGIC_XOR */) {
              headType = 4 /* XOR_WRITE */;
            }
            this.assignCycleHead(
              backLinkedNode,
              cycle,
              headType,
              offset
            );
          }
        }
      }
    } finally {
      cycleSet.clear();
    }
    if (graph) {
      for (let i = 0; i < heads.length; i++) {
        affectedNodesToUpdate.push(heads[i]);
      }
      for (let i = 0; i < extraNodes.length; i++) {
        affectedNodesToUpdate.push(extraNodes[i]);
      }
      for (let i = 0; i < affectedNodesToUpdate.length; i++) {
        graph.updater.update(affectedNodesToUpdate[i]);
      }
    }
  }
  isValidCycle(cyclePath) {
    const cycleSet = this.validationSet;
    cycleSet.clear();
    const pathLen = cyclePath.length;
    for (let i = 0; i < pathLen; i++) {
      cycleSet.add(cyclePath[i]);
    }
    try {
      for (let i = 0; i < pathLen; i++) {
        if (!this.validateNodeIO(cyclePath, i, cycleSet)) {
          return false;
        }
      }
      return true;
    } finally {
      cycleSet.clear();
    }
  }
  validateNodeIO(cyclePath, nodeIndex, cycleSet) {
    const cycleNode = cyclePath[nodeIndex];
    const pathLen = cyclePath.length;
    const { links, backLinks: nodeBackLinks } = cycleNode;
    let hasCycleLink = false;
    for (let j = 0; j < links.length; j++) {
      const neighbor = links[j];
      if (!cycleSet.has(neighbor)) {
        if (neighbor.type === 0 /* EMPTY */) continue;
        const readHead = this.findReadHead(neighbor, cycleSet);
        if (readHead === null) return false;
        const stepsToCheck = 1 + readHead.distance;
        for (let step = 1; step <= stepsToCheck; step++) {
          const checkNode = cyclePath[(nodeIndex + step) % pathLen];
          const { backLinks } = checkNode;
          for (let k = 0; k < backLinks.length; k++) {
            if (!cycleSet.has(backLinks[k])) {
              return false;
            }
          }
        }
      } else {
        if (hasCycleLink) return false;
        hasCycleLink = true;
      }
    }
    let hasWriteLink = false;
    for (let j = 0; j < nodeBackLinks.length; j++) {
      const neighbor = nodeBackLinks[j];
      if (!cycleSet.has(neighbor)) {
        if (neighbor.links.length !== 1) return false;
        const { type } = neighbor;
        const isInvalidEntryPoint = NodeTypes.isEntryPoint(type) || type === 12 /* RANDOM */ || type === 4 /* DELAY */ || type === 10 /* LATCH */ || type === 11 /* FLIP_FLOP */;
        if (isInvalidEntryPoint || hasWriteLink) return false;
        hasWriteLink = true;
      }
    }
    return true;
  }
  reevaluateAllCycles(graph) {
    const nodeUsageCount = /* @__PURE__ */ new Map();
    for (const internal of this.internalCycles.values()) {
      for (let i = 0; i < internal.nodes.length; i++) {
        const node = internal.nodes[i];
        nodeUsageCount.set(node, (nodeUsageCount.get(node) ?? 0) + 1);
      }
    }
    const toDeactivate = [];
    const toActivate = [];
    for (const internal of this.internalCycles.values()) {
      let overlaps = false;
      for (let i = 0; i < internal.nodes.length; i++) {
        if ((nodeUsageCount.get(internal.nodes[i]) ?? 0) > 1) {
          overlaps = true;
          break;
        }
      }
      const shouldBeValid = !overlaps && this.isValidCycle(internal.nodes);
      if (internal.valid !== shouldBeValid) {
        internal.valid = shouldBeValid;
        if (shouldBeValid) {
          toActivate.push(internal);
        } else {
          toDeactivate.push(internal);
        }
      } else if (shouldBeValid && internal.graphCycleRef !== null) {
        toActivate.push(internal);
      }
    }
    for (let i = 0; i < toDeactivate.length; i++) {
      const internal = toDeactivate[i];
      if (internal.graphCycleRef !== null) {
        const cycleRef = internal.graphCycleRef;
        internal.graphCycleRef = null;
        graph.removeCycle(cycleRef);
      }
      for (let j = 0; j < internal.nodes.length; j++) {
        this.resetNodeCycleInfo(internal.nodes[j]);
      }
    }
    for (let i = 0; i < toActivate.length; i++) {
      const internal = toActivate[i];
      if (internal.graphCycleRef === null) {
        graph.addCycle(internal.nodes);
      } else {
        this.refreshCycleIO(internal.graphCycleRef, graph);
      }
    }
  }
  handleCycleCandidate(graph, path) {
    const len = path.length;
    if (len < 2) return;
    for (let i = 0; i < len; i++) {
      const current = path[i];
      const next = path[(i + 1) % len];
      if (!canBeInCycle(current) || !current.links.includes(next)) {
        return;
      }
    }
    const key = this.getCycleKey(path);
    if (this.internalCycles.has(key)) {
      return;
    }
    this.internalCycles.set(key, {
      key,
      nodes: path,
      graphCycleRef: null,
      valid: false
    });
    this.reevaluateAllCycles(graph);
  }
  invalidateCluster(graph, root) {
    if (!canBeInCycle(root)) return;
    const task = this.getOrCreateTask(graph);
    task.pushCandidate(root);
    for (let i = 0; i < root.links.length; i++) {
      const next = root.links[i];
      if (canBeInCycle(next)) task.pushCandidate(next);
    }
    for (let i = 0; i < root.backLinks.length; i++) {
      const prev = root.backLinks[i];
      if (canBeInCycle(prev)) task.pushCandidate(prev);
    }
  }
  onLinkAdded(graph, node, target) {
    this.invalidateCluster(graph, node);
    this.invalidateCluster(graph, target);
    this.reevaluateAllCycles(graph);
  }
  onLinkRemoved(graph, fromNode, toNode) {
    const keysToRemove = [];
    for (const [key, internal] of this.internalCycles.entries()) {
      const nodes = internal.nodes;
      const len = nodes.length;
      for (let i = 0; i < len; i++) {
        if (nodes[i] === fromNode && nodes[(i + 1) % len] === toNode) {
          keysToRemove.push(key);
          if (internal.graphCycleRef !== null) {
            const ref = internal.graphCycleRef;
            internal.graphCycleRef = null;
            graph.removeCycle(ref);
          }
          for (let j = 0; j < nodes.length; j++) {
            this.resetNodeCycleInfo(nodes[j]);
          }
          break;
        }
      }
    }
    for (let i = 0; i < keysToRemove.length; i++) {
      this.internalCycles.delete(keysToRemove[i]);
    }
    this.reevaluateAllCycles(graph);
    this.invalidateCluster(graph, fromNode);
    this.invalidateCluster(graph, toNode);
  }
  onNodeTypeChanged(graph, node) {
    if (!canBeInCycle(node)) {
      const keysToRemove = [];
      for (const [key, internal] of this.internalCycles.entries()) {
        if (internal.nodes.includes(node)) {
          keysToRemove.push(key);
          if (internal.graphCycleRef !== null) {
            graph.removeCycle(internal.graphCycleRef);
          }
        }
      }
      for (let i = 0; i < keysToRemove.length; i++) {
        this.internalCycles.delete(keysToRemove[i]);
      }
    }
    this.reevaluateAllCycles(graph);
    this.invalidateCluster(graph, node);
  }
  onCycleAdded(_graph, cycle) {
    const key = this.getCycleKey(cycle.nodes);
    const internal = this.internalCycles.get(key);
    if (internal) {
      internal.graphCycleRef = cycle;
    }
  }
  onCycleRemoved(_graph, cycle) {
    const key = this.getCycleKey(cycle.nodes);
    const internal = this.internalCycles.get(key);
    if (internal) {
      internal.graphCycleRef = null;
    }
  }
  attachNodesToCycle(cycle, nodes) {
    for (let i = 0; i < nodes.length; i++) {
      nodes[i].cycle = {
        ref: cycle,
        headType: 0 /* NONE */,
        offset: 0,
        isBody: true
      };
    }
    this.refreshCycleIO(cycle);
  }
  detachNodesFromCycle(cycle) {
    const { nodes, heads, extraNodes } = cycle;
    for (let i = 0; i < nodes.length; i++) {
      this.resetNodeCycleInfo(nodes[i]);
    }
    for (let i = 0; i < heads.length; i++) {
      this.resetNodeCycleInfo(heads[i]);
    }
    for (let i = 0; i < extraNodes.length; i++) {
      this.resetNodeCycleInfo(extraNodes[i]);
    }
  }
  onGraphClear(_graph) {
    this.scheduler.clear();
    this.internalCycles.clear();
    if (this.activeTask !== null) {
      this.activeTask.clear();
      this.activeTask = null;
    }
  }
  onChunkAdded(_graph, _chunk, _chunkIdx) {
  }
  onNodeAdded(_graph, _node) {
  }
};

// ../vendor/graphdlc/ts/src/core/utils/getArrowRelations.ts
var ARROW_RELATIONS_MAP = {
  [1 /* ARROW */]: [[-1, 0]],
  [3 /* BLOCKER */]: [[-1, 0]],
  [4 /* DELAY */]: [[-1, 0]],
  [5 /* DETECTOR */]: [[-1, 0]],
  [15 /* LOGIC_NOT */]: [[-1, 0]],
  [16 /* LOGIC_AND */]: [[-1, 0]],
  [17 /* LOGIC_XOR */]: [[-1, 0]],
  [18 /* LATCH */]: [[-1, 0]],
  [19 /* FLIP_FLOP */]: [[-1, 0]],
  [20 /* RANDOM */]: [[-1, 0]],
  [22 /* LEVEL_SOURCE */]: [[-1, 0]],
  [24 /* DIRECTIONAL_BUTTON */]: [[-1, 0]],
  [2 /* SOURCE */]: [
    [-1, 0],
    [1, 0],
    [0, -1],
    [0, 1]
  ],
  [9 /* IMPULSE */]: [
    [-1, 0],
    [1, 0],
    [0, -1],
    [0, 1]
  ],
  [21 /* BUTTON */]: [
    [-1, 0],
    [1, 0],
    [0, -1],
    [0, 1]
  ],
  [6 /* SPLITTER_UP_DOWN */]: [
    [-1, 0],
    [1, 0]
  ],
  [7 /* SPLITTER_UP_RIGHT */]: [
    [-1, 0],
    [0, 1]
  ],
  [8 /* SPLITTER_UP_RIGHT_LEFT */]: [
    [0, -1],
    [-1, 0],
    [0, 1]
  ],
  [10 /* BLUE_ARROW */]: [[-2, 0]],
  [11 /* DIAGONAL_ARROW */]: [[-1, 1]],
  [12 /* SPLITTER_UP_UP */]: [
    [-1, 0],
    [-2, 0]
  ],
  [13 /* SPLITTER_RIGHT_UP */]: [
    [0, 1],
    [-2, 0]
  ],
  [14 /* SPLITTER_UP_DIAGONAL */]: [
    [-1, 0],
    [-1, 1]
  ],
  [0 /* EMPTY */]: [],
  [25 /* WALL */]: [],
  [23 /* LEVEL_TARGET */]: []
};
function getArrowRelations(type) {
  return ARROW_RELATIONS_MAP[type] ?? [];
}

// ../vendor/graphdlc/ts/src/core/utils/getRelativePosition.ts
var ROTATION_MATRICES = [
  { fx: 0, fy: 1, sx: 1, sy: 0 },
  { fx: -1, fy: 0, sx: 0, sy: 1 },
  { fx: 0, fy: -1, sx: -1, sy: 0 },
  { fx: 1, fy: 0, sx: 0, sy: -1 }
];
function getRelativePosition(x, y, rotation, flipped, forward = -1, sideways = 0) {
  const matrix = ROTATION_MATRICES[rotation];
  const sidewaysDist = flipped ? -sideways : sideways;
  return {
    x: x + (forward * matrix.fx + sidewaysDist * matrix.sx),
    y: y + (forward * matrix.fy + sidewaysDist * matrix.sy)
  };
}

// compile-graph.ts
function compile(request) {
  const nodes = [];
  const byCoords = /* @__PURE__ */ new Map();
  for (const cell of request.cells) {
    if (!Number.isInteger(cell.type) || cell.type < 1 || cell.type > 25)
      throw new Error(`\u041D\u0435\u043F\u043E\u0434\u0434\u0435\u0440\u0436\u0438\u0432\u0430\u0435\u043C\u044B\u0439 \u044D\u043B\u0435\u043C\u0435\u043D\u0442 ${cell.type} \u0432 (${cell.x}, ${cell.y})`);
    const key = `${cell.x},${cell.y}`;
    if (byCoords.has(key)) throw new Error(`\u041F\u043E\u0432\u0442\u043E\u0440\u043D\u0430\u044F \u043A\u043B\u0435\u0442\u043A\u0430 ${key}`);
    const node = {
      nodeIdx: nodes.length,
      chunkIdx: 0,
      globalX: cell.x,
      globalY: cell.y,
      arrowType: cell.type,
      type: NodeTypes.fromArrowType(cell.type),
      rotation: cell.rotation,
      flipped: cell.mirrored,
      links: [],
      backLinks: [],
      detectedLink: null,
      blockedLink: null,
      cycle: null
    };
    nodes.push(node);
    byCoords.set(key, node);
  }
  const link = (a, b) => {
    if (b && !a.links.includes(b)) {
      a.links.push(b);
      b.backLinks.push(a);
    }
  };
  const relative = (n, forward, sideways) => {
    const p = getRelativePosition(n.globalX, n.globalY, n.rotation, n.flipped, forward, sideways);
    return byCoords.get(`${p.x},${p.y}`) ?? null;
  };
  for (const node of nodes) {
    for (const [forward, sideways] of getArrowRelations(node.arrowType))
      link(node, relative(node, forward, sideways));
    if (node.type === 3 /* BLOCKER */) node.blockedLink = relative(node, -1, 0);
    if (node.type === 5 /* DETECTOR */) {
      node.detectedLink = relative(node, 1, 0);
      if (node.detectedLink) link(node.detectedLink, node);
    }
  }
  const cycles = [];
  if (request.optimize_cycles !== false) {
    const manager = new CycleManager();
    const originalValidate = manager.isValidCycle.bind(manager);
    manager.isValidCycle = (path) => !path.some((n) => n.arrowType === 22 || n.arrowType === 23 || n.backLinks.some((p) => p.arrowType === 22 || p.arrowType === 23)) && originalValidate(path);
    const graph = {
      updater: { update(_node) {
      } },
      addCycle(path) {
        const cycle = { index: cycles.length, nodes: path, heads: [], extraNodes: [] };
        cycles.push(cycle);
        manager.attachNodesToCycle(cycle, path);
        manager.onCycleAdded(graph, cycle);
      },
      removeCycle(cycle) {
        manager.detachNodesFromCycle(cycle);
        cycles[cycle.index] = null;
        manager.onCycleRemoved(graph, cycle);
      }
    };
    for (const node of nodes) manager.invalidateCluster(graph, node);
    drainTasks();
  }
  const resultNodes = nodes.map((n) => ({
    x: n.globalX,
    y: n.globalY,
    arrow_type: n.arrowType,
    node_type: n.type,
    links: n.links.filter((v) => v.type !== 5 /* DETECTOR */ || n.type === 3 /* BLOCKER */).map((v) => v.nodeIdx),
    detectors: n.links.filter((v) => v.type === 5 /* DETECTOR */ && v.detectedLink === n).map((v) => v.nodeIdx),
    detected: n.detectedLink?.nodeIdx ?? -1,
    blocked: n.blockedLink?.nodeIdx ?? -1,
    cycle_idx: n.cycle?.ref.index ?? -1,
    cycle_offset: n.cycle?.offset ?? 0,
    head_type: n.cycle?.headType ?? 0,
    entry: NodeTypes.isEntryPoint(n.type),
    additional: NodeTypes.isAdditionalUpdate(n.type)
  }));
  if (resultNodes.some((n) => n.links.length > 4 || n.detectors.length > 4))
    throw new Error("\u0413\u0440\u0430\u0444 \u043F\u0440\u0435\u0432\u044B\u0448\u0430\u0435\u0442 \u043E\u0433\u0440\u0430\u043D\u0438\u0447\u0435\u043D\u0438\u044F \u0447\u0438\u0441\u043B\u0430 \u0441\u0432\u044F\u0437\u0435\u0439 \u044F\u0434\u0440\u0430 GraphDLC");
  return {
    nodes: resultNodes,
    cycles: cycles.filter(Boolean).map((c) => ({
      index: c.index,
      length: c.nodes.length,
      nodes: c.nodes.map((n) => n.nodeIdx),
      heads: c.heads.map((n) => n.nodeIdx)
    })),
    test: request.test
  };
}
try {
  const request = JSON.parse(fs.readFileSync(0, "utf8"));
  process.stdout.write(JSON.stringify(compile(request)));
} catch (error) {
  process.stderr.write(String(error) + "\n");
  process.exitCode = 2;
}
