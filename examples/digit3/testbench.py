"""Check real segment states after every input transition and on static presets."""
import json
from build import HERE,PROJECT,build
from mapdata import read_map,write_json,map_hash
from simulation import simulate

# Independent conventional segment masks: bit 0 = top, then clockwise, middle last.
MASKS=(0x3f,0x06,0x5b,0x4f,0x66,0x6d,0x7d,0x07)


def run():
    _,meta=build();folder=HERE/'build';cells=read_map(folder/'digit3.test.save.txt')
    values=[value for old in range(8) for new in range(8) for value in (old,new,old)]
    # Test a full steady window rather than one coincidentally correct sample.
    hold=160;steady=24
    phases=[phase for value in values for phase in [hold]+[1]*steady]
    data=[value for value in values for _ in range(steady+1)]
    case={'ticks':sum(phases),'frame_ticks':phases,'inputs':[
          {'at':p['fixture'],'values':[(v>>p['index'])&1 for v in data]} for p in meta['inputs']['n']],
          'expect':[],'observe':meta['segments']}
    checks=0
    for optimized in (False,True):
        result=simulate(cells,case,optimize_cycles=optimized)
        for i,value in enumerate(data):
            actual=sum(row['values'][i]<<bit for bit,row in enumerate(result['observations']))
            if actual!=MASKS[value]:raise RuntimeError(f'{optimized=}, {i=}, {value=}, actual={actual:02x}')
        checks+=len(data)*7
    # Observe all existing cells for previews; no measurement wires alter the display.
    for value in range(8):
        preset=read_map(folder/'presets'/f'digit{value}.save.txt')
        case={'ticks':hold,'hold_ticks':hold,'inputs':[],'expect':[],'observe':[list(p) for p in sorted(preset)]}
        result=simulate(preset,case,optimize_cycles=False)
        states={tuple(row['at']):row['values'][0] for row in result['observations']}
        actual=sum(states[tuple(p)]<<bit for bit,p in enumerate(meta['segments']))
        if actual!=MASKS[value]:raise RuntimeError(f'Wrong static preset {value}')
        write_json(folder/'presets'/f'digit{value}.states.json',{
                   'map_hash':map_hash(preset),'ticks':hold,'states':result['observations']})
    report={'passed':True,'map_hash':meta['map_hash'],'all_input_values':list(range(8)),
            'all_64_transitions':True,'vectors':len(values),'steady_window_ticks':steady,
            'hold_ticks':hold,'segment_checks':checks,'cycle_modes':[False,True],
            'static_presets':8,'profile':meta['profile'],'verified_against_current_game':False}
    write_json(folder/'digit3.report.json',report)
    print(json.dumps(report),flush=True)


if __name__=='__main__':run()
