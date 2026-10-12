# ArrowsHDL

ArrowsHDL — компилятор Verilog/SystemVerilog в физические схемы Logic Arrows.
Пакет предоставляет CLI и Python API для компиляции, компоновки, симуляции,
проверки и экспорта игровых сохранений.

Версия: **0.1.0**, экспериментальная.

## Требования

- Python 3.11 или новее.
- Rust/Cargo для сборки и установки из исходников.

Yosys и Node.js устанавливаются как зависимости pip. Платформенный wheel
содержит скомпилированный симулятор и не требует Rust/Cargo при установке.

## Установка

### Из исходников

Команды выполняются из корня репозитория.

~~~powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install .
arrowshdl check
~~~

### Из wheel

~~~powershell
python -m pip install .\dist\arrowshdl-0.1.0-py3-none-win_amd64.whl
arrowshdl check
~~~

Имя файла приведено для Windows x64. Сборка wheel из исходников:

~~~powershell
python -m pip wheel . --no-deps -w dist
~~~

## Быстрый старт

Команды выполняются из корня репозитория после установки пакета.
`python -m arrowshdl` эквивалентен `arrowshdl`.

~~~powershell
arrowshdl build examples/alu_workbench/project.toml --layout macro-grid -o build/alu
arrowshdl test build/alu/alu_workbench.save.txt examples/alu_workbench/vectors.json --vectors --manifest build/alu/alu_workbench.build.json -o build/alu/report.json
arrowshdl preview build/alu/alu_workbench.save.txt build/alu/alu_workbench.build.json -o build/alu/map.png
~~~

`*.save.txt` — игровой код сохранения для импорта в Logic Arrows;
`*.map.json` — карта клеток; `*.build.json` — геометрия, порты, задержка и хеш;
`*.logic.json` — логический граф автоматического размещения.
Тестовые источники и пробники добавляются в копию карты.

## Использование CLI

Общая справка: `arrowshdl --help`; справка команды: `arrowshdl compile --help`.
**`-o` / `--out`** задаёт каталог результатов сборки либо имя объекта,
отчёта, преобразованного файла или PNG.

### Компиляция HDL и проект TOML

~~~powershell
arrowshdl compile examples/alu_workbench/alu_workbench.v examples/alu_workbench/arithmetic.v examples/alu_workbench/logic_unit.v --top alu_workbench --std 1364-2005 --layout macro-grid -o build/compiled
arrowshdl build examples/packet_router/project.toml --layout macro-grid -o build/router
arrowshdl build examples/minesweeper/v2/minesweeper_5x5.toml -o build/mines
~~~

TOML задаёт исходники, верхний модуль, стандарт, контакты и геометрию.
Параметры `compile`: `-I каталог` для include, `-D NAME=VALUE` для макроса,
`-G NAME=VALUE` для параметра верхнего модуля, `-L файл.v` для библиотеки.
Стандартная нативная библиотека подключается автоматически.
`--timeout` ограничивает время **всей операции** в секундах (по умолчанию 600),
`--max-cells` — число клеток (по умолчанию 1 000 000).

`--layout compact` — обычное автоматическое размещение; `macro-grid` —
сетка макросов для сложных комбинационных схем; `sparse` — разреженная разводка.
`macro-grid` не поддерживает группировку входных шин.
Нативные физические проекты используют заданную в TOML геометрию.

### Объектная компиляция и компоновка

~~~powershell
arrowshdl compile -c examples/alu_workbench/alu_workbench.v examples/alu_workbench/arithmetic.v examples/alu_workbench/logic_unit.v --top alu_workbench -o build/alu.aho.json
arrowshdl link build/alu.aho.json --top alu_workbench --layout macro-grid -o build/linked
~~~

`-c` сохраняет объект RTLIL без размещения. `link` принимает несколько
объектов, объединяет модули и строит карту. Для раздельной компиляции
`compile -c --extern имя` оставляет объявленный интерфейс до компоновки.

### Проверка логики и симуляция по тактам

~~~powershell
arrowshdl test build/alu/alu_workbench.save.txt examples/alu_workbench/vectors.json --vectors --manifest build/alu/alu_workbench.build.json -o build/alu/report.json
arrowshdl build examples/pulse_sequencer/project.toml -o build/sequencer
arrowshdl simulate build/sequencer/pulse_sequencer.save.txt examples/pulse_sequencer/scenario.json -o build/sequencer/trace.json
~~~

Векторы — массив объектов `{"inputs": {...}, "expect": {...}}`, шины заданы
целыми числами. `--vectors --manifest` добавляет тестовые контакты и определяет
время установления комбинационной схемы.

Физический сценарий задаёт `ticks`, `inputs` для тестовых источников,
`controls` для кнопок, `probes` для свободных приёмников, `observe` для
считывания существующих клеток и `assert` / `expect` для проверок.
Значения — `0`, `1`, а `null` в проверке пропускает отсчёт.
`simulate` и `test` используют один физический симулятор. Отчёт содержит
трассы и SHA-256 входного сохранения. Код завершения: **0** — успех или
трасса без проверок, **1** — провал проверки, **2** — ошибка команды.
`--no-optimize-cycles` отключает оптимизацию циклов.

### Сохранения, граф и изображения

~~~powershell
arrowshdl decode build/alu/alu_workbench.save.txt -o build/alu/decoded.json
arrowshdl encode build/alu/decoded.json -o build/alu/roundtrip.save.txt
arrowshdl graph build/alu/roundtrip.save.txt -o build/alu/graph.json
arrowshdl preview build/alu/roundtrip.save.txt -o build/alu/preview.png
arrowshdl check
~~~

`decode` читает сохранение, `encode` записывает его из JSON,
`graph` экспортирует клетки и физические зависимости,
`preview` рисует реальные стрелки; `check` проверяет установку.

## Примеры

| Проект | Описание |
|---|---|
| [Minesweeper](examples/minesweeper/README.md) | Игра с безопасным первым кликом, каскадным открытием, счётчиками и статусом |
| [ALU Workbench](examples/alu_workbench/README.md) | Иерархическая ALU с восемью операциями и флагами результата |
| [Packet Router](examples/packet_router/README.md) | Маршрутизатор с проверкой чётности, арбитражем и backpressure |
| [Pulse Sequencer](examples/pulse_sequencer/README.md) | Восемь генераторов, память выбора и история сигнала на 64 такта |

Каталоги примеров содержат HDL, описание проекта, сохранения,
диаграммы, изображения карт и визуализации поведения.

## Разработка и тестирование

~~~powershell
python -m pip install -e ".[test]"
arrowshdl test --suite tests -o build/regression.json
~~~

Регрессионные тесты расположены в `tests`, тестовые данные — в
`tests/fixtures`. Набор включает проверки компилятора, симулятора,
публичного API и проектов из `examples`.

Генерация визуализаций примеров:

~~~powershell
python tools/render_examples.py
~~~

## Ограничения

Поддерживается синтезируемый поднабор Verilog/SystemVerilog.
Произвольная поведенческая последовательная логика не поддерживается;
память реализуется нативными модулями библиотеки. Автоматическое размещение
ограничено заданным бюджетом времени и числом клеток.

## Документация и лицензия

Подробные форматы и Python API: [справочник](docs/reference.md).
Устройство компилятора: [ARCHITECTURE.md](ARCHITECTURE.md).
Собственный код: [PolyForm Noncommercial 1.0.0](LICENSE), [NOTICE](NOTICE).
Сторонние материалы: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
