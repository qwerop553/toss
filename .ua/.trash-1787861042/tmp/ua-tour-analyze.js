// 튜어 설계에 쓸 그래프 구조 신호를 계산하는 스크립트.
// 입력 JSON({nodes, edges, layers})을 읽어 팬인/팬아웃 랭킹, 진입점 후보,
// BFS 의존성 사슬, 비코드 파일 인벤토리, 결합 클러스터를 결과 JSON으로 뽑는다.
const fs = require('fs');

function main() {
  const [, , inPath, outPath] = process.argv;
  if (!inPath || !outPath) throw new Error('usage: analyze.js <input.json> <output.json>');
  const { nodes, edges, layers } = JSON.parse(fs.readFileSync(inPath, 'utf8'));

  const byId = new Map(nodes.map(n => [n.id, n]));
  // function:/class: 같은 하위 노드는 id에 파일 경로가 박혀 있으므로 파일 노드로 접어 준다.
  // 그래야 함수 단위 calls 엣지도 파일 사이 결합도 신호로 살아난다.
  const pathToFileNode = new Map();
  nodes.forEach(n => { if (n.filePath && !pathToFileNode.has(n.filePath)) pathToFileNode.set(n.filePath, n.id); });
  const project = (id) => {
    if (byId.has(id)) return id;
    const parts = id.split(':');
    if (parts.length >= 3) {
      const fp = parts.slice(1, -1).join(':');
      if (pathToFileNode.has(fp)) return pathToFileNode.get(fp);
    }
    return null;
  };

  // 자기 자신으로 접힌 엣지(같은 파일 내부 contains/calls)는 구조 신호가 아니라 버린다.
  const pEdges = [];
  for (const e of edges) {
    const s = project(e.source), t = project(e.target);
    if (s && t && s !== t) pEdges.push({ source: s, target: t, type: e.type });
  }

  const fanIn = new Map(), fanOut = new Map();
  nodes.forEach(n => { fanIn.set(n.id, new Set()); fanOut.set(n.id, new Set()); });
  pEdges.forEach(e => { fanOut.get(e.source).add(e.target); fanIn.get(e.target).add(e.source); });

  const rank = (m, key) => nodes.map(n => ({ id: n.id, [key]: m.get(n.id).size, name: n.name }))
    .sort((a, b) => b[key] - a[key]).slice(0, 20);
  const fanInRanking = rank(fanIn, 'fanIn');
  const fanOutRanking = rank(fanOut, 'fanOut');

  // C. 진입점 후보 점수
  const ENTRY_NAMES = new Set(['index.ts','index.js','main.ts','main.js','app.ts','app.js','server.ts','server.js',
    'mod.rs','main.go','main.py','main.rs','manage.py','app.py','wsgi.py','asgi.py','run.py','__main__.py',
    'Application.java','Main.java','Program.cs','config.ru','index.php','App.swift','Application.kt','main.cpp','main.c']);
  const outVals = nodes.map(n => fanOut.get(n.id).size).sort((a, b) => b - a);
  const inVals = nodes.map(n => fanIn.get(n.id).size).sort((a, b) => a - b);
  const fanOutTop10 = outVals[Math.max(0, Math.floor(outVals.length * 0.1) - 1)] ?? 0;
  const fanInBot25 = inVals[Math.max(0, Math.ceil(inVals.length * 0.25) - 1)] ?? 0;

  const entryPointCandidates = nodes.map(n => {
    let score = 0;
    const fp = n.filePath || '';
    const depth = fp.split('/').length;
    if (n.type === 'document') {
      if (n.name === 'README.md' && depth === 1) score += 5;
      else if (n.name.endsWith('.md') && depth === 1) score += 2;
    } else {
      if (ENTRY_NAMES.has(n.name)) score += 3;
      if (depth <= 2) score += 1;
      if (fanOut.get(n.id).size >= fanOutTop10 && fanOutTop10 > 0) score += 1;
      if (fanIn.get(n.id).size <= fanInBot25) score += 1;
    }
    return { id: n.id, score, name: n.name, type: n.type, summary: n.summary };
  }).filter(c => c.score > 0).sort((a, b) => b.score - a.score).slice(0, 5);

  // D. 최상위 코드 진입점에서 imports/calls 순방향 BFS
  const codeEntry = entryPointCandidates.find(c => c.type !== 'document');
  const startNode = codeEntry ? codeEntry.id : (fanOutRanking[0] && fanOutRanking[0].id);
  const adj = new Map(nodes.map(n => [n.id, []]));
  pEdges.filter(e => e.type === 'imports' || e.type === 'calls').forEach(e => adj.get(e.source).push(e.target));
  const depthMap = {}, order = [];
  if (startNode) {
    depthMap[startNode] = 0; order.push(startNode);
    const q = [startNode];
    while (q.length) {
      const cur = q.shift();
      for (const nxt of adj.get(cur) || []) {
        if (depthMap[nxt] === undefined) { depthMap[nxt] = depthMap[cur] + 1; order.push(nxt); q.push(nxt); }
      }
    }
  }
  const byDepth = {};
  Object.entries(depthMap).forEach(([id, d]) => { (byDepth[d] = byDepth[d] || []).push(id); });

  // E. 비코드 파일 인벤토리
  const bucket = { document: 'documentation', service: 'infrastructure', pipeline: 'infrastructure',
    resource: 'infrastructure', table: 'data', schema: 'data', endpoint: 'data', config: 'config' };
  const nonCodeFiles = { documentation: [], infrastructure: [], data: [], config: [] };
  nodes.forEach(n => { const b = bucket[n.type];
    if (b) nonCodeFiles[b].push({ id: n.id, name: n.name, type: n.type, summary: n.summary }); });

  // F. 결합 클러스터: 양방향 관계 쌍을 씨앗으로 잡고, 씨앗 2개 이상과 붙은 노드를 흡수한다.
  const pairKey = (a, b) => [a, b].sort().join('||');
  const dir = new Set(pEdges.map(e => e.source + '>>' + e.target));
  const undirected = new Map();
  pEdges.forEach(e => { const k = pairKey(e.source, e.target); undirected.set(k, (undirected.get(k) || 0) + 1); });
  const seeds = [];
  for (const k of undirected.keys()) {
    const [a, b] = k.split('||');
    if (dir.has(a + '>>' + b) && dir.has(b + '>>' + a)) seeds.push(new Set([a, b]));
  }
  const clusters = [];
  for (const seed of seeds) {
    let changed = true;
    while (changed && seed.size < 5) {
      changed = false;
      for (const n of nodes) {
        if (seed.has(n.id) || seed.size >= 5) continue;
        let links = 0;
        for (const m of seed) if (undirected.has(pairKey(n.id, m))) links++;
        if (links >= 2) { seed.add(n.id); changed = true; }
      }
    }
    const ids = [...seed].sort();
    const key = ids.join('||');
    if (clusters.some(c => c.key === key)) continue;
    let edgeCount = 0;
    for (let i = 0; i < ids.length; i++) for (let j = i + 1; j < ids.length; j++) edgeCount += undirected.get(pairKey(ids[i], ids[j])) || 0;
    clusters.push({ key, nodes: ids, edgeCount });
  }
  clusters.sort((a, b) => b.edgeCount - a.edgeCount);
  const topClusters = clusters.slice(0, 10).map(({ nodes: n, edgeCount }) => ({ nodes: n, edgeCount }));

  const nodeSummaryIndex = {};
  nodes.forEach(n => { nodeSummaryIndex[n.id] = { name: n.name, type: n.type, summary: n.summary }; });

  fs.writeFileSync(outPath, JSON.stringify({
    scriptCompleted: true, entryPointCandidates, fanInRanking, fanOutRanking,
    bfsTraversal: { startNode, order, depthMap, byDepth },
    nonCodeFiles, clusters: topClusters,
    layers: { count: layers.length, list: layers },
    nodeSummaryIndex, totalNodes: nodes.length, totalEdges: edges.length,
    projectedEdges: pEdges.length
  }, null, 1), 'utf8');
}

try { main(); } catch (err) { console.error(err.stack || String(err)); process.exit(1); }
