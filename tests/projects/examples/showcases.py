"""Independent protocol and arithmetic models for complete demonstration projects."""
from itertools import product

PROJECTS={'alu_workbench':'alu_workbench','packet_router':'packet_router','pulse_sequencer':'pulse_sequencer'}

def alu(a,b,op):
    value=(a+b,a-b,a&b,a|b,a^b,~a,a<<1,b)[op]&15
    carry=int(a+b>15) if op==0 else int(a>=b) if op==1 else (a>>3) if op==6 else 0
    return dict(result=value,carry=carry,zero=int(value==0),equal=int(a==b))

def route(frame0,frame1,valid,ready):
    frames=(frame0,frame1)
    good=[bool(valid&(1<<i)) and ((f&31).bit_count()%2==0) for i,f in enumerate(frames)]
    error=sum(int(bool(valid&(1<<i)) and not good[i])<<i for i in range(2))
    accepted=0;output_valid=0;data=[0,0]
    for lane in range(2):
        contenders=[i for i,f in enumerate(frames) if good[i] and f>>5==lane]
        if contenders:
            winner=contenders[0]
            output_valid|=1<<lane;data[lane]=frames[winner]&15
            if ready&(1<<lane):accepted|=1<<winner
    return dict(data0=data[0],data1=data[1],output_valid=output_valid,accepted=accepted,error=error)

def vectors(top):
    if top=='alu_workbench':
        for a,b,op in product(range(16),range(16),range(8)):
            yield dict(inputs=dict(a=a,b=b,operation=op),expect=alu(a,b,op))
    elif top=='packet_router':
        for f0,f1,valid,ready in product(range(64),range(64),range(4),range(4)):
            yield dict(inputs=dict(frame0=f0,frame1=f1,valid=valid,ready=ready),expect=route(f0,f1,valid,ready))
    else:raise ValueError(top)
