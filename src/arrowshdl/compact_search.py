"""Reusable area-first search; the caller supplies the ordinary compiler.

Recompile every footprint so placement and port geometry can change together.
Compilation success is not a substitute for simulation or equivalence tests.
"""
def search_footprints(compile_candidate, baseline, widths, heights, seeds=(67,31),
                      max_trials=32, on_trial=None):
    best=dict(baseline); trials=[]; seen=set()
    def attempt(width,height,seed):
        nonlocal best
        key=(width,height,seed)
        if key in seen or len(trials)>=max_trials:return
        seen.add(key)
        record=dict(width=width,height=height,seed=seed)
        try:
            candidate=compile_candidate(width,height,seed)
            record.update(status='compiled',arrows=candidate['arrows'],stem=candidate['stem'])
            score=lambda c:(c['width']*c['height'],c['arrows'],max(c['width'],c['height']))
            if score(candidate)<score(best):best=dict(candidate)
        except (ValueError,TimeoutError) as error:
            record.update(status='rejected',reason=str(error))
        trials.append(record)
        if on_trial:on_trial(record,best,trials)
    coarse=sorted({(w,h) for w in widths for h in heights},key=lambda p:(p[0]*p[1],max(p),p))
    for w,h in coarse:
        if w*h>best['width']*best['height']:continue
        attempt(w,h,seeds[0])
    # Refine the whole coarse grid at half its spacing, closest area first.
    fine=sorted({(w,h) for w in range(min(widths),max(widths)+1,2)
                        for h in range(min(heights),max(heights)+1,2)},
                key=lambda p:(-p[0]*p[1],max(p),p))
    for seed in seeds:
        for w,h in fine:
            if w*h>=best['width']*best['height']:continue
            attempt(w,h,seed)
    return dict(best=best,trials=trials,objective='area_then_arrows_then_longest_side',
                budget=max_trials,global_minimum_proved=False)
