import fs from 'node:fs';
import { CycleManager } from '../vendor/graphdlc/ts/src/core/graph/ast/cycle/CycleManager';
import { NodeType, NodeTypes } from '../vendor/graphdlc/ts/src/core/graph/engines/core/NodeType';
import { getArrowRelations } from '../vendor/graphdlc/ts/src/core/utils/getArrowRelations';
import { getRelativePosition } from '../vendor/graphdlc/ts/src/core/utils/getRelativePosition';
import { drainTasks } from './headless-scheduler';

function compile(request: any) {
  const nodes: any[] = [];
  const byCoords = new Map<string, any>();
  for (const cell of request.cells) {
    if (!Number.isInteger(cell.type) || cell.type < 1 || cell.type > 25)
      throw new Error(`Неподдерживаемый элемент ${cell.type} в (${cell.x}, ${cell.y})`);
    const key = `${cell.x},${cell.y}`;
    if (byCoords.has(key)) throw new Error(`Повторная клетка ${key}`);
    const node = {
      nodeIdx: nodes.length, chunkIdx: 0, globalX: cell.x, globalY: cell.y,
      arrowType: cell.type, type: NodeTypes.fromArrowType(cell.type),
      rotation: cell.rotation, flipped: cell.mirrored,
      links: [], backLinks: [], detectedLink: null, blockedLink: null, cycle: null,
    };
    nodes.push(node); byCoords.set(key, node);
  }
  const link = (a: any, b: any) => {
    if (b && !a.links.includes(b)) { a.links.push(b); b.backLinks.push(a); }
  };
  const relative = (n: any, forward: number, sideways: number) => {
    const p = getRelativePosition(n.globalX, n.globalY, n.rotation, n.flipped, forward, sideways);
    return byCoords.get(`${p.x},${p.y}`) ?? null;
  };
  for (const node of nodes) {
    for (const [forward, sideways] of getArrowRelations(node.arrowType))
      link(node, relative(node, forward, sideways));
    if (node.type === NodeType.BLOCKER) node.blockedLink = relative(node, -1, 0);
    if (node.type === NodeType.DETECTOR) {
      node.detectedLink = relative(node, 1, 0);
      if (node.detectedLink) link(node.detectedLink, node);
    }
  }
  const cycles: any[] = [];
  if (request.optimize_cycles !== false) {
    const manager = new CycleManager();
    // Ports must remain addressable and external inputs must never be bypassed.
    const originalValidate = manager.isValidCycle.bind(manager);
    manager.isValidCycle = (path: any[]) =>
      !path.some(n => n.arrowType === 22 || n.arrowType === 23 ||
        n.backLinks.some((p: any) => p.arrowType === 22 || p.arrowType === 23)) && originalValidate(path);
    const graph: any = {
      updater: { update(_node: any) {} },
      addCycle(path: any[]) {
        const cycle = { index: cycles.length, nodes: path, heads: [], extraNodes: [] };
        cycles.push(cycle);
        manager.attachNodesToCycle(cycle as any, path);
        manager.onCycleAdded(graph, cycle as any);
      },
      removeCycle(cycle: any) {
        manager.detachNodesFromCycle(cycle); cycles[cycle.index] = null;
        manager.onCycleRemoved(graph, cycle);
      },
    };
    for (const node of nodes) manager.invalidateCluster(graph, node);
    drainTasks();
  }
  const resultNodes = nodes.map(n => ({
    x: n.globalX, y: n.globalY, arrow_type: n.arrowType, node_type: n.type,
    links: n.links.filter((v: any) => v.type !== NodeType.DETECTOR || n.type === NodeType.BLOCKER).map((v: any) => v.nodeIdx),
    detectors: n.links.filter((v: any) => v.type === NodeType.DETECTOR && v.detectedLink === n).map((v: any) => v.nodeIdx),
    detected: n.detectedLink?.nodeIdx ?? -1, blocked: n.blockedLink?.nodeIdx ?? -1,
    cycle_idx: n.cycle?.ref.index ?? -1,
    cycle_offset: n.cycle?.offset ?? 0, head_type: n.cycle?.headType ?? 0,
    entry: NodeTypes.isEntryPoint(n.type), additional: NodeTypes.isAdditionalUpdate(n.type),
  }));
  if (resultNodes.some(n => n.links.length > 4 || n.detectors.length > 4))
    throw new Error('Граф превышает ограничения числа связей ядра GraphDLC');
  return {
    nodes: resultNodes,
    cycles: cycles.filter(Boolean).map(c => ({ index: c.index, length: c.nodes.length,
      nodes: c.nodes.map((n: any) => n.nodeIdx), heads: c.heads.map((n: any) => n.nodeIdx) })),
    test: request.test,
  };
}

try {
  const request = JSON.parse(fs.readFileSync(0, 'utf8'));
  process.stdout.write(JSON.stringify(compile(request)));
} catch (error) {
  process.stderr.write(String(error) + '\n'); process.exitCode = 2;
}
