# -*- coding: utf-8 -*-
"""아키텍처 레이어 식별을 위한 구조 분석 스크립트.

입력 JSON(fileNodes / importEdges / allEdges)을 받아 디렉터리 그룹, 노드 타입 분포,
그룹 간 import 빈도와 방향, 그룹 내부 응집도, 디렉터리·파일명 패턴 매칭 등을 계산해
레이어를 판단할 때 쓸 구조적 근거만 뽑아낸다. 의미 해석은 하지 않는다."""
import json
import sys
import os
import re
from collections import defaultdict


def main(inp, outp):
    d = json.load(open(inp, encoding='utf-8'))
    nodes, imports, alledges = d['fileNodes'], d['importEdges'], d['allEdges']
    byid = {n['id']: n for n in nodes}
    paths = [n['filePath'] for n in nodes]

    # A. 모든 파일이 공유하는 접두 경로를 걷어낸 뒤, 그 다음 첫 디렉터리 세그먼트로 묶는다.
    #    세그먼트가 하나뿐인(= 루트에 놓인) 파일은 'root' 그룹으로 보낸다.
    segs = [p.split('/') for p in paths]
    prefix = []
    for i in range(min(len(s) for s in segs)):
        cand = {s[i] for s in segs}
        if len(cand) == 1 and all(len(s) > i + 1 for s in segs):
            prefix.append(segs[0][i])
        else:
            break
    pl = len(prefix)
    groups = defaultdict(list)
    node2group = {}
    for n in nodes:
        s = n['filePath'].split('/')[pl:]
        g = s[0] if len(s) > 1 else 'root'
        groups[g].append(n['id'])
        node2group[n['id']] = g

    # B. 노드 타입별 그룹화 — 코드/설정/문서/테이블 분포를 본다.
    types = defaultdict(list)
    for n in nodes:
        types[n['type']].append(n['id'])

    # C. import 인접 관계에서 파일별 fan-in(피참조) / fan-out(참조) 집계.
    fanout, fanin = defaultdict(int), defaultdict(int)
    for e in imports:
        if e['source'] in byid and e['target'] in byid:
            fanout[e['source']] += 1
            fanin[e['target']] += 1

    # D. 서로 다른 노드 타입 사이를 잇는 교차 카테고리 엣지 집계.
    cross = defaultdict(int)
    for e in alledges:
        s, t = byid.get(e['source']), byid.get(e['target'])
        if s and t and s['type'] != t['type']:
            cross[(s['type'], t['type'], e['type'])] += 1

    # E/F. 그룹 간 import 빈도와 그룹 내부 응집도(내부 엣지 / 관여 엣지 총합).
    inter = defaultdict(int)
    internal, total = defaultdict(int), defaultdict(int)
    for e in imports:
        a, b = node2group.get(e['source']), node2group.get(e['target'])
        if a is None or b is None:
            continue
        if a == b:
            internal[a] += 1
            total[a] += 1
        else:
            inter[(a, b)] += 1
            total[a] += 1
            total[b] += 1

    # G. 디렉터리 이름을 알려진 아키텍처 패턴 라벨에 대응시킨다.
    PAT = {
        'routes': 'api', 'api': 'api', 'controllers': 'api', 'endpoints': 'api',
        'handlers': 'api', 'serializers': 'api', 'routers': 'api', 'blueprints': 'api',
        'services': 'service', 'core': 'service', 'lib': 'service', 'domain': 'service',
        'logic': 'service', 'strategies': 'service', 'signals': 'service',
        'internal': 'service', 'composables': 'service', 'mailers': 'service',
        'jobs': 'service', 'channels': 'service',
        'models': 'data', 'db': 'data', 'data': 'data', 'persistence': 'data',
        'repository': 'data', 'entities': 'data', 'entity': 'data',
        'migrations': 'data', 'sql': 'data', 'database': 'data', 'schema': 'data',
        'components': 'ui', 'views': 'ui', 'pages': 'ui', 'ui': 'ui',
        'layouts': 'ui', 'screens': 'ui',
        'middleware': 'middleware', 'plugins': 'middleware',
        'interceptors': 'middleware', 'guards': 'middleware',
        'utils': 'utility', 'helpers': 'utility', 'common': 'utility',
        'shared': 'utility', 'tools': 'utility', 'pkg': 'utility',
        'templatetags': 'utility',
        'config': 'config', 'constants': 'config', 'env': 'config',
        'settings': 'config', 'management': 'config', 'commands': 'config',
        '__tests__': 'test', 'test': 'test', 'tests': 'test',
        'spec': 'test', 'specs': 'test',
        'types': 'types', 'interfaces': 'types', 'schemas': 'types',
        'contracts': 'types', 'dtos': 'types', 'dto': 'types',
        'request': 'types', 'response': 'types',
        'hooks': 'hooks',
        'store': 'state', 'state': 'state', 'reducers': 'state',
        'actions': 'state', 'slices': 'state',
        'assets': 'assets', 'static': 'assets', 'public': 'assets',
        'cmd': 'entry', 'bin': 'entry',
        'docs': 'documentation', 'documentation': 'documentation', 'wiki': 'documentation',
        'deploy': 'infrastructure', 'deployment': 'infrastructure',
        'infra': 'infrastructure', 'infrastructure': 'infrastructure',
        'docker': 'infrastructure', 'k8s': 'infrastructure',
        'kubernetes': 'infrastructure', 'helm': 'infrastructure',
        'charts': 'infrastructure', 'terraform': 'infrastructure', 'tf': 'infrastructure',
        '.github': 'ci-cd', '.gitlab': 'ci-cd', '.circleci': 'ci-cd',
    }
    patterns = {g: PAT.get(g.lower(), 'unknown') for g in groups}

    # 파일 단위 패턴 — 디렉터리로 안 잡히는 진입점·테스트·설정·문서를 따로 표시.
    filepat = {}
    for n in nodes:
        p = n['filePath']
        base = os.path.basename(p)
        lab = None
        if re.search(r'(\.test\.|\.spec\.|_test\.go$|Test\.java$|_spec\.rb$)', p) or base.startswith('test_'):
            lab = 'test'
        elif base in ('__init__.py', 'index.ts', 'index.js', 'manage.py',
                      'main.rs', 'lib.rs', 'config.ru'):
            lab = 'entry'
        elif base in ('wsgi.py', 'asgi.py', 'Cargo.toml', 'go.mod', 'Gemfile',
                      'pom.xml', 'build.gradle', 'composer.json'):
            lab = 'config'
        elif base.endswith(('.json', '.toml', '.yaml', '.yml', '.cfg', '.ini')):
            lab = 'config'
        elif base.endswith(('.md', '.rst')):
            lab = 'documentation'
        elif base.endswith('.sql'):
            lab = 'data'
        elif base.endswith(('.graphql', '.gql', '.proto')):
            lab = 'types'
        elif base in ('Dockerfile', 'Makefile') or base.startswith('docker-compose') \
                or p.endswith(('.tf', '.tfvars')):
            lab = 'infrastructure'
        if lab:
            filepat[n['id']] = lab

    # H. 배포 토폴로지 — 컨테이너/IaC/CI 파일이 실제로 있는지.
    low = [p.lower() for p in paths]
    infra = [p for p in paths
             if os.path.basename(p) in ('Dockerfile', 'Makefile')
             or 'docker-compose' in p
             or p.endswith(('.tf', '.tfvars'))
             or '.github/workflows' in p
             or os.path.basename(p) in ('.gitlab-ci.yml', 'Jenkinsfile')]
    topo = {
        'hasDockerfile': any('dockerfile' in p for p in low),
        'hasCompose': any('docker-compose' in p for p in low),
        'hasK8s': any(re.search(r'(^|/)(k8s|kubernetes|helm|charts)/', p) for p in low),
        'hasTerraform': any(p.endswith('.tf') for p in low),
        'hasCI': any('.github/workflows' in p or 'gitlab-ci' in p.lower()
                     or 'jenkinsfile' in p.lower() for p in paths),
        'infraFiles': infra,
    }

    # I. 데이터 파이프라인 흔적 — 스키마/마이그레이션/모델/수집 지점.
    pipe = {
        'schemaFiles': [n['filePath'] for n in nodes
                        if n['type'] in ('schema', 'table')
                        or n['filePath'].endswith(('.graphql', '.proto', '.prisma'))],
        'migrationFiles': [p for p in paths if 'migration' in p.lower()],
        'dataModelFiles': [n['id'] for n in nodes
                           if {'data-model', 'database', 'ingestion', 'schema-definition'}
                           & set(n.get('tags', []))],
        'apiHandlerFiles': [n['id'] for n in nodes
                            if {'api-handler', 'api-client', 'endpoint'}
                            & set(n.get('tags', []))],
    }

    # J. 문서 커버리지 — 문서 노드가 직접 속하거나 엣지로 가리키는 그룹을 센다.
    docids = set(types.get('document', []))
    documented = set()
    for e in alledges:
        if e['source'] in docids and e['target'] in node2group:
            documented.add(node2group[e['target']])
        if e['target'] in docids and e['source'] in node2group:
            documented.add(node2group[e['source']])
    for g, ids in groups.items():
        if any(i in docids for i in ids):
            documented.add(g)
    cov = {
        'groupsWithDocs': len(documented),
        'totalGroups': len(groups),
        'coverageRatio': round(len(documented) / max(1, len(groups)), 2),
        'undocumentedGroups': sorted(set(groups) - documented),
    }

    # K. 그룹 쌍마다 우세한 의존 방향을 정한다(양방향이면 순증분 쪽만 남긴다).
    direction, seen = [], set()
    for (a, b), c in inter.items():
        if (a, b) in seen or (b, a) in seen:
            continue
        seen.add((a, b))
        rev = inter.get((b, a), 0)
        if c > rev:
            direction.append({'dependent': a, 'dependsOn': b, 'net': c - rev})
        elif rev > c:
            direction.append({'dependent': b, 'dependsOn': a, 'net': rev - c})

    out = {
        'scriptCompleted': True,
        'commonPrefix': '/'.join(prefix),
        'directoryGroups': dict(groups),
        'nodeTypeGroups': dict(types),
        'crossCategoryEdges': [{'fromType': k[0], 'toType': k[1], 'edgeType': k[2], 'count': v}
                               for k, v in sorted(cross.items(), key=lambda x: -x[1])],
        'interGroupImports': [{'from': k[0], 'to': k[1], 'count': v}
                              for k, v in sorted(inter.items(), key=lambda x: -x[1])],
        'intraGroupDensity': {g: {'internalEdges': internal[g], 'totalEdges': total[g],
                                  'density': round(internal[g] / total[g], 2) if total[g] else 0.0}
                              for g in groups},
        'patternMatches': patterns,
        'filePatternMatches': filepat,
        'deploymentTopology': topo,
        'dataPipeline': pipe,
        'docCoverage': cov,
        'dependencyDirection': sorted(direction, key=lambda x: -x['net']),
        'fileStats': {
            'totalFileNodes': len(nodes),
            'filesPerGroup': {g: len(v) for g, v in groups.items()},
            'nodeTypeCounts': {t: len(v) for t, v in types.items()},
        },
        'fileFanIn': dict(sorted(fanin.items(), key=lambda x: -x[1])),
        'fileFanOut': dict(sorted(fanout.items(), key=lambda x: -x[1])),
    }
    json.dump(out, open(outp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('ok:', len(nodes), 'nodes,', len(groups), 'groups')


if __name__ == '__main__':
    try:
        main(sys.argv[1], sys.argv[2])
    except Exception as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
