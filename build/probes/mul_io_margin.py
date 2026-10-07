exec((__import__('pathlib').Path(__file__).parent/'connected_mul.py').read_text().split('for aspect in (')[0])
sys.stdout.reconfigure(encoding='utf-8')
outputs={e['net'] for es in graph['outputs'].values() for e in es}
for aspect in (2.5,2.8,3.5):
    for margin in (4,8,12):
        try:
            (vertices,positions,sources),blocks=arrange_packed(graph,{'core':1},0,aspect,(170,170),True)
            for i,v in enumerate(vertices):
                if v['kind']=='input' or v.get('node',{}).get('output') in outputs:continue
                x,y=positions[i];positions[i]=(x+margin,y+margin)
                if 'pins' in v:v['pins']=[(x+margin,y+margin) for x,y in v['pins']]
            router=Router(graph,1,100000,(vertices,positions,sources));cells=router.route()
            core=logic_core_metrics(cells,router.gates,router.output_nets)
            print(dict(aspect=aspect,margin=margin,cells=len(cells),core=core,fallback=router.io_conflict_fallback),flush=True)
        except MapError as e:print(dict(aspect=aspect,margin=margin,error=str(e)),flush=True)
