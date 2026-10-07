"""Compare the old and new multiplier independently of Yosys's cell IDs."""
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parents[2]/'examples/hdl/candidates/mul4'


def structure(graph):
    signatures={'const0':'zero','const1':'one'}
    signatures.update({entry['net']:f"{name}[{entry['index']}]" for name,entries in graph['inputs'].items() for entry in entries})
    operations=[]
    for node in graph['nodes']:
        arguments=[signatures[net] for net in node['inputs']]
        if node['op'] in ('AND','OR','XOR','MAJ'):arguments.sort()
        token=hashlib.sha256(repr((node['op'],arguments)).encode()).hexdigest()
        signatures[node['output']]=token;operations.append(token)
    outputs={name:[signatures[entry['net']] for entry in entries] for name,entries in graph['outputs'].items()}
    return sorted(operations),outputs


graphs=[json.loads((HERE/folder/'mul4.logic.json').read_text(encoding='utf-8')) for folder in ('before-packed','build')]
manifests=[json.loads((HERE/folder/'mul4.build.json').read_text(encoding='utf-8')) for folder in ('before-packed','build')]
before,after=map(structure,graphs)
report={'same_source_sha256':manifests[0]['source_sha256']==manifests[1]['source_sha256'],
        'same_operator_structure':before[0]==after[0],'same_output_structure':before[1]==after[1],
        'source_sha256':manifests[1]['source_sha256'],
        'before':{key:manifests[0][key] for key in ('cells','logic_core','settle_ticks')},
        'after':{key:manifests[1][key] for key in ('cells','logic_core','settle_ticks')}}
report['passed']=all(report[key] for key in ('same_source_sha256','same_operator_structure','same_output_structure'))
(HERE/'build/mul4.comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
raise SystemExit(0 if report['passed'] else 1)
