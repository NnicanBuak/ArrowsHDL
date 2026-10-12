"""Test-only expectations. Application names never enter the compiler."""
from itertools import product
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PROJECTS = {
    'half_adder': 'hdl/half_adder', 'full_adder':'hdl/full_adder',
    'adder8':'hdl/adder8', 'composed_logic':'hdl/composed_logic',
    'mux2':'hdl/multiplexer/mux2', 'mux4':'hdl/multiplexer/mux4', 'mux8':'hdl/multiplexer/mux8',
    'mul2':'hdl/multiplier/mul2', 'mul3':'hdl/multiplier/mul3', 'mul4':'hdl/multiplier/mul4',
    'bcd4':'hdl/binary_to_bcd', 'digit3':'digit3', 'loop_mux8':'loop_mux8', 'reference':'reference_adder8',
}


def vectors(top, exhaustive=True):
    if top=='half_adder':
        for a,b in product(range(2),repeat=2):
            yield dict(inputs=dict(i_bit1=a,i_bit2=b),expect=dict(o_sum=a^b,o_carry=a&b))
    elif top=='full_adder':
        for a,b,cin in product(range(2),repeat=3):
            yield dict(inputs=dict(i_bit1=a,i_bit2=b,i_carry=cin),expect=dict(o_sum=(a+b+cin)&1,o_carry=(a+b+cin)>>1))
    elif top=='adder8':
        values = product(range(256),range(256),range(2)) if exhaustive else ((a,b,cin) for a,b in ((0,0),(255,0),(255,255),(85,170),(127,1)) for cin in (0,1))
        for a,b,cin in values:
            n=a+b+cin
            yield dict(inputs=dict(a=a,b=b,cin=cin),expect=dict(sum=n&255,cout=n>>8))
    elif top=='composed_logic':
        for a,b,c,d in product(range(2),repeat=4):
            p=((1-a)^b)&(a|c)
            y=((1-p)^c)&(p|d)
            yield dict(inputs=dict(a=a,b=b,c=c,d=d),expect=dict(p=p,y=y))
    elif top.startswith('mux'):
        count=int(top[3:])
        for data,sel in product(range(1<<count),range(count)):
            yield dict(inputs=dict(data=data,sel=sel),expect=dict(y=(data>>sel)&1))
    elif top.startswith('mul'):
        width=int(top[3:])
        for a,b in product(range(1<<width),repeat=2):
            yield dict(inputs=dict(a=a,b=b),expect=dict(product=a*b))
    elif top=='bcd4':
        for binary in range(16):
            yield dict(inputs=dict(binary=binary),expect=dict(bcd=(binary//10)*16+binary%10))
    else:
        raise ValueError(top)
