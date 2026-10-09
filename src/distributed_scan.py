"""Factor a two-dimensional OR prefix scan into parallel row reductions.

Contract: missing edge inputs are zero; the north carry is consumed only in
the first column. The forward prefix already ORs that carry into the row.
The reverse row reduction can then ignore the forward prefix and reduce
local values independently. Vertical accumulation runs concurrently with
other rows instead of making a serpentine traversal of every complete row.
"""
from copy import deepcopy
from arrowasm import MapError


def parallelize_or_scan(graph, *, value, row, north_carry, east_row, carry_port):
    result=deepcopy(graph)
    nodes={n['output']:n for n in result['nodes']}
    root=nodes.get(row)
    if not root or root['op']!='OR' or len(root['inputs'])!=2 or east_row not in root['inputs']:
        raise MapError('Не найден обратный OR-скан с указанным входом')
    end=nodes.get(next(net for net in root['inputs'] if net!=east_row))
    if not end or end['op']!='AND' or len(end['inputs'])!=2:
        raise MapError('Не найден граничный AND обратного скана')
    uses=[n['output'] for n in result['nodes'] if end['output'] in n['inputs']]
    if uses!=[row]:raise MapError('Граничный AND имеет посторонних потребителей')
    port=result['outputs'].get(carry_port)
    if not port or len(port)!=1:
        raise MapError('Не найден единственный порт вертикального переноса')
    driver=nodes.get(port[0]['net'])
    if not driver or driver['op']!='BUF' or driver['inputs']!=[row]:
        raise MapError('Вертикальный перенос не соответствует контракту скана')
    root['inputs']=[value,east_row]
    end.update(op='OR',inputs=[row,north_carry])
    driver['inputs']=[end['output']]
    result.setdefault('_distributed_rewrites',[]).append(dict(
        kind='parallel_or_scan',value=value,row=row,carry=end['output'],
        latency_order='width + height',previous_latency_order='width * height'))
    return result
