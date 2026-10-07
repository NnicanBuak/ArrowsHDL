"""Reconstruct this supplied screenshot on its calibrated cell grid.

Matching uses the game's actual sprites, not expected circuit behavior. An audit
records competing matches; reviewed corrections, if any, live in overrides.json.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image, ImageFilter, ImageOps

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))
from arrowasm import Cell, NAMES
from mapdata import write_json, write_map

GRID = {"origin_pixel": [254.6, 171.15], "pitch_pixel": [17.812, 17.825], "sample_size": 24}


def recognize():
    source = HERE / "source.jpg"
    im = Image.open(source).convert("RGB")
    size = GRID["sample_size"]
    templates, tokens, seen = [], [], set()
    for kind in range(1,26):
        original = Image.open(ROOT / f"assets/sprites/arrow{kind}.png").convert("RGBA")
        for mirror in (False,True):
            for rotation in range(4):
                sprite = ImageOps.mirror(original) if mirror else original
                sprite = sprite.rotate(-90*rotation).resize((size,size),Image.Resampling.LANCZOS)
                tile = Image.new("RGB",(size,size),"white")
                tile.paste(sprite,(0,0),sprite)
                tile = tile.filter(ImageFilter.GaussianBlur(0.35))
                signature = kind,tile.tobytes()
                if signature in seen:
                    continue
                seen.add(signature)
                tokens.append((kind,rotation,mirror))
                templates.append(np.asarray(tile,dtype=np.float32)[2:-2,2:-2])
    templates = np.stack(templates)
    cells,audit = {},[]
    cx,cy = GRID["origin_pixel"]
    px,py = GRID["pitch_pixel"]
    for y in range(20):
        for x in range(-2,52):
            # Exclude browser controls and empty canvas outside the two circuit regions.
            if x>33 and not (35<=x<=51 and 8<=y<=13):
                continue
            center_x,center_y = cx+x*px,cy+y*py
            patch = im.transform((size,size),Image.Transform.AFFINE,
                (px/size,0,center_x-px/2,0,py/size,center_y-py/2),Image.Resampling.BICUBIC)
            arr = np.asarray(patch,dtype=np.float32)[2:-2,2:-2]
            ink = np.max(arr,axis=2)-np.min(arr,axis=2)>20
            if np.count_nonzero(ink)<5:
                continue
            scores = np.mean((templates-arr)**2,axis=(1,2,3))
            order = np.argsort(scores)[:3]
            if float(scores[order[0]]) >= float(np.mean((arr-255)**2)):
                continue
            best = tokens[int(order[0])]
            cells[x,y] = Cell(*best)
            audit.append({"at":[x,y],"match":{"type":best[0],"name":NAMES[best[0]],"rotation":best[1],"mirrored":best[2]},
                "mse":round(float(scores[order[0]]),2),
                "alternatives":[{"type":tokens[int(i)][0],"rotation":tokens[int(i)][1],"mirrored":tokens[int(i)][2],"mse":round(float(scores[i]),2)} for i in order[1:]],
                "confidence_gap":round(float((scores[order[1]]-scores[order[0]])/max(1,scores[order[0]])),3)})
    overrides_path = HERE / "overrides.json"
    overrides = json.loads(overrides_path.read_text(encoding="utf-8")) if overrides_path.exists() else []
    for entry in overrides:
        position=tuple(entry["at"])
        if entry.get("empty"):
            cells.pop(position,None)
        else:
            cells[position]=Cell(entry["type"],entry["rotation"],entry.get("mirrored",False))
    out=HERE/"build"
    write_map(out,"reference",cells)
    write_json(out/"recognition.audit.json",{"source_sha256":hashlib.sha256(source.read_bytes()).hexdigest(),"grid":GRID,
        "cells":len(cells),"counts":dict(sorted(Counter(c.type for c in cells.values()).items())),"overrides":overrides,"matches":audit})
    print("cells",len(cells),"counts",dict(sorted(Counter(c.type for c in cells.values()).items())))
    print("lowest confidence",[(a["at"],a["match"]["name"],a["confidence_gap"]) for a in sorted(audit,key=lambda a:a["confidence_gap"])[:20]])
    return cells,audit


if __name__ == "__main__":
    recognize()
