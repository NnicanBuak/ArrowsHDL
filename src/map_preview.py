# Модель стрелок заимствована из https://github.com/kala-telo/arrows.py
# Автор: kala-telo; коммит: 5e235a03ff129f9171d2ae0c1c6dc88b7062b0d4.
# Классы Arrow, ArrowType и Direction подключены через preview_arrows.py.
# Отрисовка — местная реализация; спрайты — из Logic Arrows.

"""Render actual placed cells and measured test results, using game arrow sprites."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps
from preview_arrows import display_arrow

ROOT = Path(__file__).resolve().parents[1]


def font(size):
    for path in (Path("C:/Windows/Fonts/segoeui.ttf"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")):
        if path.is_file():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default(size=size)


def render(cells, manifest, path, report=None, table_rows=None):
    if manifest["layout"] == "compact-native-adder-v1":
        return render_native_adder(cells, manifest, path, report, table_rows)
    if manifest["layout"].startswith("compact-"):
        return render_compact(cells, manifest, path, report, table_rows)
    min_x, max_x = min(x for x, y in cells), max(x for x, y in cells)
    min_y, max_y = min(y for x, y in cells), max(y for x, y in cells)
    size = min(24, max(10, 2600 // (max_x - min_x + 1)))
    left, top = 155, 100
    gw, gh = (max_x - min_x + 3) * size, (max_y - min_y + 3) * size
    rows = (table_rows or report.get("truth_table", [])[:8]) if report else []
    width, height = max(1000, left + gw + 190), top + gh + 105 + (len(rows) + 2) * 28
    if width * height > 40_000_000:
        raise ValueError("Карта слишком велика для растрового предпросмотра")
    im = Image.new("RGB", (width, height), "#f6f8fb")
    draw = ImageDraw.Draw(im)
    draw.text((24, 18), manifest["top"], font=font(29), fill="#142237")
    subtitle = f"{'Тестовая карта' if report else 'Обычная карта'} · {len(cells)} клеток · предел установления: {manifest['settle_ticks']} тактов"
    draw.text((24, 57), subtitle, font=font(17), fill="#526278")
    draw.rectangle((left, top, left + gw, top + gh), fill="white", outline="#bdc9d8")
    for x in range(0, gw + 1, size):
        draw.line((left + x, top, left + x, top + gh), fill="#edf1f6")
    for y in range(0, gh + 1, size):
        draw.line((left, top + y, left + gw, top + y), fill="#edf1f6")

    def pixel(key):
        return left + (key[0] - min_x + 1) * size, top + (key[1] - min_y + 1) * size

    backgrounds = {2: "#fff0dd", 7: "#f6e8eb", 10: "#e3f1ff", 15: "#eee7ff", 16: "#eee7ff", 17: "#eee7ff", 22: "#d9f7e5", 23: "#fff0b7"}
    sprites = {}
    for key, cell in cells.items():
        arrow = display_arrow(cell)
        px, py = pixel(key)
        draw.rectangle((px + 1, py + 1, px + size - 1, py + size - 1), fill=backgrounds.get(arrow.type, "#fafbfc"))
        token = arrow.type, arrow.direction, arrow.flipped
        if token not in sprites:
            original = Image.open(ROOT / f"assets/sprites/arrow{arrow.type}.png").convert("RGBA")
            if arrow.flipped:
                original = ImageOps.mirror(original)
            sprites[token] = original.rotate(-90 * arrow.direction).resize((size - 2, size - 2), Image.Resampling.LANCZOS)
        im.paste(sprites[token], (px + 1, py + 1), sprites[token])
    for kind in ("inputs", "outputs"):
        for name, entries in manifest[kind].items():
            for entry in entries:
                key = entry["fixture"] if report else entry["contact"]
                px, py = pixel(key)
                text = name if len(entries) == 1 else f"{name}[{entry['index']}]"
                draw.text((left - 12, py + size / 2), text, anchor="rm", font=font(14), fill="#1d344f") if kind == "inputs" else draw.text((left + gw + 8, py + size / 2), text, anchor="lm", font=font(14), fill="#1d344f")
    for gate in manifest["gate_labels"]:
        px, py = pixel(gate["at"])
        draw.text((px + size / 2, py + size + 5), gate["op"], anchor="mt", font=font(12), fill="#6838a5")
    y = top + gh + 20
    draw.text((24, y), "Зелёный: Source    Жёлтый: Target    Фиолетовый: логика    Голубой: пересечение через прыжок", font=font(16), fill="#364962")
    y += 32
    if rows:
        draw.text((24, y), "Входы", font=font(16), fill="#253b57")
        draw.text((350, y), "Ожидалось", font=font(16), fill="#253b57")
        draw.text((650, y), "Измерено на Target", font=font(16), fill="#253b57")
        for row in rows:
            y += 28
            draw.text((24, y), ", ".join(f"{k}={v}" for k, v in row["inputs"].items()), font=font(14), fill="#253b57")
            draw.text((350, y), ", ".join(f"{k}={v}" for k, v in row["expected"].items()), font=font(14), fill="#253b57")
            draw.text((650, y), ", ".join(f"{k}={v}" for k, v in row["actual"].items()) + ("  OK" if row["passed"] else "  FAIL"), font=font(14), fill="#16804c" if row["passed"] else "#b32035")
    im.save(path)


def render_native_adder(cells, manifest, path, report=None, table_rows=None):
    """Dense bit-slice board with bus names above and below its actual cells."""
    min_x,max_x=min(x for x,y in cells),max(x for x,y in cells)
    min_y,max_y=min(y for x,y in cells),max(y for x,y in cells)
    size=min(38,max(16,2200//(max_x-min_x+3)))
    left,top=140,145
    gw,gh=(max_x-min_x+3)*size,(max_y-min_y+3)*size
    rows=(table_rows or report.get('truth_table',[])[:8]) if report else []
    width=max(1050,left+gw+140)
    height=top+gh+125+(len(rows)+2)*29
    if width*height>40_000_000:raise ValueError('Карта слишком велика для предпросмотра')
    im=Image.new('RGB',(width,height),'#f6f8fb');draw=ImageDraw.Draw(im)
    draw.text((24,16),manifest['top'],font=font(29),fill='#142237')
    draw.text((24,57),f"{'Тестовая карта' if report else 'Обычная карта'} · {len(cells)} клеток · {max_x-min_x+1}×{max_y-min_y+1} · установление ≤ {manifest['settle_ticks']} тактов",font=font(17),fill='#526278')
    core=manifest.get('logic_core')
    detail=f"Ядро без ввода/вывода · стрелок: {core['cells']} · поле: {core['bounds']['width']}×{core['bounds']['height']} · тактов: {core['ticks']}. " if core else ''
    draw.text((24,90),detail+'XOR — сумма; ≥2 — перенос.',font=font(16),fill='#526278')
    draw.rectangle((left,top,left+gw,top+gh),fill='white',outline='#bdc9d8')
    for x in range(0,gw+1,size):draw.line((left+x,top,left+x,top+gh),fill='#edf1f6')
    for y in range(0,gh+1,size):draw.line((left,top+y,left+gw,top+y),fill='#edf1f6')
    def pixel(key):return left+(key[0]-min_x+1)*size,top+(key[1]-min_y+1)*size
    gate_keys={tuple(g['at']) for g in manifest['gate_labels']}
    colors={10:'#e3f1ff',12:'#e3f1ff',14:'#e3f1ff',22:'#d9f7e5',23:'#fff0b7'}
    sprites={}
    for key,cell in cells.items():
        px,py=pixel(key)
        draw.rectangle((px+1,py+1,px+size-1,py+size-1),fill='#eee7ff' if key in gate_keys else colors.get(cell.type,'#fafbfc'))
        token=cell.type,cell.rotation,cell.mirrored
        if token not in sprites:
            original=Image.open(ROOT/f'assets/sprites/arrow{cell.type}.png').convert('RGBA')
            if cell.mirrored:original=ImageOps.mirror(original)
            sprites[token]=original.rotate(-90*cell.rotation).resize((size-4,size-4),Image.Resampling.LANCZOS)
        im.paste(sprites[token],(px+2,py+2),sprites[token])
    for gate in manifest['gate_labels']:
        if gate['op']=='BUF':continue
        px,py=pixel(gate['at'])
        text='≥2' if gate['op']=='MAJ' else gate['op']
        draw.text((px+size/2,py+size-2),text,anchor='ms',font=font(10),fill='#6838a5',stroke_width=1,stroke_fill='#eee7ff')
    for category in ('inputs','outputs'):
        for name,entries in manifest[category].items():
            for entry in entries:
                key=entry['fixture'] if report else entry['contact']
                px,py=pixel(key)
                text=name if len(entries)==1 else f"{name}[{entry['index']}]"
                color='#16804c' if category=='inputs' else '#956900'
                if len(entries)==1:
                    if category=='inputs':draw.text((px-8,py+size/2),text,anchor='rm',font=font(14),fill=color)
                    else:draw.text((px+size+8,py+size/2),text,anchor='lm',font=font(14),fill=color)
                elif entry['rotation']==2 and category=='inputs':
                    draw.text((px+size/2,top-15),text,anchor='mm',font=font(12),fill=color)
                else:
                    label_y=top+gh+(43 if category=='inputs' else 18)
                    draw.text((px+size/2,label_y),text,anchor='mm',font=font(12),fill=color)
    y=top+gh+72
    draw.text((24,y),'Зелёный — Source; жёлтый — Target. Весь рисунок прочитан из сохранения.',font=font(16),fill='#364962')
    y+=34
    if rows:
        columns=[24,max(350,width//3),max(650,width*2//3)]
        for x,text in zip(columns,('Входы','Ожидалось','Измерено на Target')):draw.text((x,y),text,font=font(16),fill='#253b57')
        for row in rows:
            y+=29
            for x,values in zip(columns,(row['inputs'],row['expected'],row['actual'])):
                text=', '.join(f'{k}={v}' for k,v in values.items())
                if x==columns[-1]:text+='  OK' if row['passed'] else '  FAIL'
                draw.text((x,y),text,font=font(14),fill='#16804c' if row['passed'] else '#b32035')
    im.save(path)


def render_compact(cells, manifest, path, report=None, table_rows=None):
    """Entire compact board, with port IDs tied to a readable side legend."""
    min_x, max_x = min(x for x, y in cells), max(x for x, y in cells)
    min_y, max_y = min(y for x, y in cells), max(y for x, y in cells)
    size, left, top = 32, 48, 134 if 'logic_core' in manifest else 112
    # Keep whole large circuits exportable without exceeding the raster budget.
    # Coordinates and cells are untouched; only the drawing scale changes.
    while size>12 and (left+(max_x-min_x+3)*size+325)*(top+(max_y-min_y+3)*size+500)>38_000_000:
        size-=2
    gw, gh = (max_x - min_x + 3) * size, (max_y - min_y + 3) * size
    rows = (table_rows or report.get("truth_table", [])[:8]) if report else []
    port_count = sum(len(entries) for category in ("inputs", "outputs") for entries in manifest[category].values())
    board_height = max(gh, 180 + port_count * 25)
    width, height = max(1050, left + gw + 325), top + board_height + 105 + (len(rows) + 2) * 28
    if width * height > 40_000_000:
        raise ValueError("Карта слишком велика для растрового предпросмотра")
    im = Image.new("RGB", (width, height), "#f6f8fb")
    draw = ImageDraw.Draw(im)
    draw.text((24, 15), manifest["top"], font=font(29), fill="#142237")
    timing = f"протокол слова: {manifest['operation_ticks']} тактов" if 'operation_ticks' in manifest else f"установление ≤ {manifest['settle_ticks']} тактов"
    subtitle = f"{'Тестовая карта' if report else 'Обычная карта'} · {len(cells)} клеток · поле {max_x-min_x+1}×{max_y-min_y+1} · {timing}"
    draw.text((24, 56), subtitle, font=font(18), fill="#526278")
    if core:=manifest.get('logic_core'):
        draw.text((24,87),f"Ядро без ввода/вывода · стрелок: {core['cells']} · поле: {core['bounds']['width']}×{core['bounds']['height']} · тактов: {core['ticks']}",font=font(16),fill="#526278")
    draw.rectangle((left, top, left + gw, top + gh), fill="white", outline="#bdc9d8")
    for x in range(0, gw + 1, size):
        draw.line((left + x, top, left + x, top + gh), fill="#edf1f6")
    for y in range(0, gh + 1, size):
        draw.line((left, top + y, left + gw, top + y), fill="#edf1f6")

    def pixel(key):
        return left + (key[0] - min_x + 1) * size, top + (key[1] - min_y + 1) * size

    for x in range(min_x, max_x + 1):
        if x % 5 == 0:
            px, _ = pixel((x, min_y))
            draw.text((px + size/2, top - 14), str(x), anchor="mm", font=font(11), fill="#7c8a9c")
    for y in range(min_y, max_y + 1):
        if y % 5 == 0:
            _, py = pixel((min_x, y))
            draw.text((left - 12, py + size/2), str(y), anchor="mm", font=font(11), fill="#7c8a9c")
    gate_keys = {tuple(gate["at"]) for gate in manifest["gate_labels"]}
    backgrounds = {2: "#fff0dd", 6: "#f6e8eb", 7: "#f6e8eb", 8: "#f6e8eb", 10: "#e3f1ff", 11: "#e3f1ff", 12: "#e3f1ff", 13: "#e3f1ff", 14: "#e3f1ff", 22: "#d9f7e5", 23: "#fff0b7"}
    sprites = {}
    for key, cell in cells.items():
        px, py = pixel(key)
        color = "#eee7ff" if key in gate_keys else backgrounds.get(cell.type, "#fafbfc")
        draw.rectangle((px + 1, py + 1, px + size - 1, py + size - 1), fill=color)
        token = cell.type, cell.rotation, cell.mirrored
        if token not in sprites:
            original = Image.open(ROOT / f"assets/sprites/arrow{cell.type}.png").convert("RGBA")
            if cell.mirrored:
                original = ImageOps.mirror(original)
            sprites[token] = original.rotate(-90 * cell.rotation).resize((size - 4, size - 4), Image.Resampling.LANCZOS)
        im.paste(sprites[token], (px + 2, py + 2), sprites[token])
    for gate in manifest["gate_labels"]:
        px, py = pixel(gate["at"])
        draw.text((px + size - 2, py + size - 1), gate["op"], anchor="rs", font=font(8), fill="#6838a5", stroke_width=1, stroke_fill="#eee7ff")
    legend_x, legend_y = left + gw + 22, top
    for category, prefix, color, title in (("inputs", "I", "#16804c", "Входы"), ("outputs", "O", "#956900", "Выходы")):
        draw.text((legend_x, legend_y), title + (" — Source" if category == "inputs" and report else " — Target" if report else " — контакты"), font=font(17), fill=color)
        legend_y += 34
        number = 0
        for name, entries in manifest[category].items():
            for entry in entries:
                key = entry["fixture"] if report else entry["contact"]
                px, py = pixel(key)
                tag = f"{prefix}{number}"
                label = name if len(entries) == 1 else f"{name}[{entry['index']}]"
                draw.rounded_rectangle((px + 1, py + size - 11, px + 24, py + size - 1), radius=2, fill=color)
                draw.text((px + 3, py + size - 12), tag, font=font(8), fill="white")
                draw.text((legend_x, legend_y), f"{tag:>3}  {label}   ({key[0]}, {key[1]})", font=font(14), fill="#253b57")
                legend_y += 25
                number += 1
        legend_y += 16
    draw.text((legend_x, legend_y + 6), "Фиолетовый — логические элементы\nРозовый — разветвление\nГолубой — прыжковая стрелка", font=font(14), fill="#526278", spacing=7)
    y = top + board_height + 20
    draw.text((24, y), "Каждая клетка на изображении прочитана из сохранения Base64.", font=font(16), fill="#364962")
    y += 32
    if rows:
        columns = [24, max(350, width // 3), max(650, width * 2 // 3)]
        for x, text in zip(columns, ("Входы", "Ожидалось", "Измерено на Target")):
            draw.text((x, y), text, font=font(16), fill="#253b57")
        for row in rows:
            y += 28
            for x, values in zip(columns, (row["inputs"], row["expected"], row["actual"])):
                text = ", ".join(f"{k}={v}" for k, v in values.items())
                if x == columns[-1]:
                    text += "  OK" if row["passed"] else "  FAIL"
                draw.text((x, y), text, font=font(14), fill="#16804c" if row["passed"] else "#b32035")
    im.save(path)
