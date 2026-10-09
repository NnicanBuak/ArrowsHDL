"""Render the saved physical circuit and the toggle/priority control close-up."""
import json
import sys

from build import HERE, PROJECT, STEM
sys.path.insert(0, str(PROJECT / "src"))
from mapdata import read_map
from map_preview import font
from PIL import Image, ImageDraw, ImageOps


def run():
    folder = HERE / "build"
    meta = json.loads((folder / f"{STEM}.build.json").read_text(encoding="utf-8"))
    report = json.loads((folder / f"{STEM}.report.json").read_text(encoding="utf-8"))
    if not report["passed"] or report["map_hash"] != meta["map_hash"]:
        raise ValueError("No passing report for the current map")
    cells = read_map(folder / f"{STEM}.save.txt")
    min_x, min_y = meta["bounds"]["min"]
    size, margin, top = 18, 30, 94
    width = meta["bounds"]["width"] * size + 2 * margin
    height = meta["bounds"]["height"] * size + top + margin
    image = Image.new("RGB", (width, height), "#0b1720")
    draw = ImageDraw.Draw(image)
    draw.text((margin, 16), "Logic oscilloscope: 8 rings / MUX8 / 64-bit history", font=font(29), fill="#e8f4fa")
    draw.text((margin, 54), f"{len(cells)} cells | rising-edge T toggles | priority 0..7 | 000 = output OFF", font=font(18), fill="#a3b9c8")
    colors = {"mux8": "#3a294c", "oscillators": "#163f38", "channels": "#112634",
              "display": "#19432d", "encoder": "#1a3249", "controls": "#5a4326"}
    groups = {tuple(p): name for name, points in meta["regions"].items() for p in points}
    sprites = {}
    for (x, y), cell in cells.items():
        px, py = margin + (x - min_x) * size, top + (y - min_y) * size
        draw.rectangle((px, py, px + size - 1, py + size - 1), fill=colors[groups[x, y]])
        key = cell.type, cell.rotation, cell.mirrored
        if key not in sprites:
            original = Image.open(PROJECT / f"assets/sprites/arrow{cell.type}.png").convert("RGBA")
            if cell.mirrored:
                original = ImageOps.mirror(original)
            sprites[key] = original.rotate(-90 * cell.rotation).resize((size-2,size-2), Image.Resampling.LANCZOS)
        image.paste(sprites[key], (px + 1, py + 1), sprites[key])
    image.save(folder / f"{STEM}.preview.png")
    # Keep the control circuit readable independently of the long signal wires.
    crop_left=margin+(-33-min_x)*size
    crop_top=top+(15-min_y)*size
    crop_right=margin+(15-min_x)*size
    crop_bottom=top+(54-min_y)*size
    close=image.crop((crop_left,crop_top,crop_right,crop_bottom))
    canvas=Image.new('RGB',(close.width+48,close.height+78),'#0b1720')
    canvas.paste(close,(48,78))
    d=ImageDraw.Draw(canvas)
    d.text((16,10),'Кнопки → фронт нажатия → Т-триггеры → приоритетный шифратор',font=font(22),fill='#e8f4fa')
    d.text((16,42),'Приоритет сверху вниз. 000 — вывод выключен.',font=font(19),fill='#9edbbd')
    for i in range(8):
        d.text((18,78+(24+4*i-15)*size-3),str(i),font=font(20),fill='#ffc981')
    canvas.save(folder/f'{STEM}.controls.preview.png')
    print('Rendered full circuit and control close-up')


if __name__ == "__main__":
    run()
