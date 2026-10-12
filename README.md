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
arrowshdl health
~~~

### Из wheel

~~~powershell
python -m pip install .\dist\arrowshdl-0.1.0-py3-none-win_amd64.whl
arrowshdl health
~~~

Имя файла приведено для Windows x64. Сборка wheel из исходников:

~~~powershell
python -m pip wheel . --no-deps -w dist
~~~

## Быстрый старт

Команды выполняются из корня репозитория после установки пакета.
`python -m arrowshdl` эквивалентен `arrowshdl`.

~~~powershell
arrowshdl build examples/alu_workbench/project.toml -o build/alu.json
arrowshdl test build/alu.json examples/alu_workbench/build/vectors.json --vectors -o build/alu/report.json
arrowshdl preview build/alu.json -o build/alu/map.png
~~~

`*.save.txt` — игровой код сохранения для импорта в Logic Arrows;
`*.map.json` — карта клеток; `*.build.json` — геометрия, порты, задержка и хеш;
`*.logic.json` — логический граф автоматического размещения.
Тестовые источники и пробники добавляются в копию карты.

## Использование CLI

Общая справка: `arrowshdl --help`; справка команды: `arrowshdl compile --help`.
**`-o` / `--out`** задаёт каталог результатов сборки либо имя объекта,
отчёта, преобразованного файла или PNG.

### Проверка работоспособности

~~~powershell
arrowshdl health
~~~

Команда проверяет запуск Node.js, наличие исполняемого файла симулятора,
компиляцию встроенной схемы, экспорт и чтение сохранения, результаты
физической симуляции и создание PNG. Проверки выполняются во временном
каталоге. Вывод на английском содержит статус каждого компонента;
код завершения **0** означает успех, **1** — сбой проверки.

### Компиляция HDL и проект TOML

`-o FILE` задаёт путь к **одному выходному файлу**. Расширение `.json` сохраняет
скомпилированную схему вместе с портами, временными характеристиками и метаданными.
Расширение `.txt` сохраняет код импорта в игру. Каталог в `-o` не допускается.
Предпросмотр и отчёт создаются отдельными командами.

Процессы выводят этапы и процент выполнения в stderr. Процент относится
к этапам операции; трассировщик дополнительно сообщает число обработанных
цепей, оставшиеся цепи и перестроения. Повторные попытки размещения могут
увеличивать длительность этапа. 100% выводится после успешного завершения. Все встроенные сообщения CLI,
справка и диагностика ошибок выводятся на английском языке.


~~~powershell
arrowshdl compile examples/alu_workbench/arithmetic.v --top arithmetic --std 1364-2005 -G WIDTH=4 -o build/compiled.json
arrowshdl build examples/packet_router/project.toml -o build/router.json
arrowshdl build examples/minesweeper/project.toml -o build/mines.json
~~~

TOML v2 задаёт исходники, экземпляры HDL-модулей, параметры, связи портов,
кнопки и готовые схемы дисплеев. Имена `library:seven_segment` и
`library:history64` в `components.file` подключают I/O из установленного пакета;
их сборка не зависит от ранее созданных файлов в `build/`. Каждая уникальная специализация HDL-модуля компилируется один раз;
готовые карты экземпляров размещаются и соединяются по графу TOML.
Параметры `compile`: `-I каталог` для include, `-D NAME=VALUE` для макроса,
`-G NAME=VALUE` для параметра верхнего модуля, `-L файл.v` для библиотеки.
Стандартная нативная библиотека подключается автоматически.
`--timeout` ограничивает время **всей операции** в секундах (по умолчанию 600),
`--max-cells` — число клеток (по умолчанию 1 000 000).

По умолчанию используется **`--layout auto`**: размещение по связям графа,
сокращение эквивалентной комбинационной логики и разводка. Шины сохраняют
порядок битов; входы размещаются ближе к потребителям, выходы — к источникам.
Размер скомпилированного модуля оценивается целиком, включая его порты. Геометрические шаблоны
арифметических блоков в этом режиме не используются.

**`--compact`** включает дополнительные формы размещения и эвристический
поиск. Он требует больше времени; скомпилированный модуль содержит не больше
стрелок и занимает не большую площадь, чем обычная компиляция того же модуля.
Поиск не гарантирует глобальный минимум.

~~~powershell
arrowshdl build examples/packet_router/project.toml --compact -o build/router-small.json
arrowshdl compile examples/alu_workbench/arithmetic.v --top arithmetic --compact -o build/math-small.json
~~~

| Режим | Назначение |
| --- | --- |
| `--layout auto` | Автоматическое размещение по графу, включая нативную память и панели управления. Используется по умолчанию. |
| `--compact` | Дополнительный поиск расположений в режиме `auto`; выбирается проверенный вариант с меньшим числом стрелок и площадью. |
| `--layout compact` | Прежний поисковый алгоритм для комбинационной логики. |
| `--layout sparse` | Разреженная разводка комбинационной логики; увеличивает расстояния и размер карты. |
| `--layout macro-grid` | Диагностическая сетка нативных элементов без поиска компактного размещения. |
| `--layout fixed` | Структурная схема с заранее подготовленной физической геометрией. |

`--layout compact` и `sparse` не поддерживают нативные элементы памяти.
Панели управления требуют `auto`. `--compact` применяется с `--layout auto`.

### Повторное использование скомпилированных схем

`build` хранит готовые модули в системном каталоге кеша ArrowsHDL.
На Windows это `%LOCALAPPDATA%/ArrowsHDL/cache`; переменная
`ARROWSHDL_CACHE_DIR` задаёт другой каталог. Ключ учитывает
исходники, include-файлы, параметры, стандарт, определения и настройки
компилятора. Одинаковые экземпляры используют одну скомпилированную карту;
повторный `build` читает её из кеша. Изменение входных данных создаёт новую
сборку. Внутренние клетки готовой схемы при сборке карты сохраняются.

Для явной двухэтапной сборки:

~~~powershell
arrowshdl compile examples/minesweeper/mine_cell.v examples/minesweeper/seven_segment.v --top mine_cell --std 1364-2005 --compact -o build/tile.json
~~~

Команда создаёт один файл `build/tile.json`, содержащий готовую карту, порты и метаданные.
TOML проекта может подключить готовый результат без исходников:

~~~toml
[[components]]
name = "cell_0"
file = "build/tile.json"
~~~

Путь file задаётся относительно TOML. Добавление нескольких components с
разными name и одним file размещает копии одной готовой схемы. `--compact`
применяется при компиляции модуля; готовые components повторно не синтезируются.
Время и размер межмодульной разводки зависят от связей проекта.

### Объектная компиляция и компоновка

~~~powershell
arrowshdl compile -c examples/alu_workbench/arithmetic.v --top arithmetic -o build/math.aho.json
arrowshdl link build/math.aho.json --top arithmetic -o build/linked.json
~~~

`-c` сохраняет объект RTLIL без размещения. `link` принимает несколько
объектов, объединяет модули и строит карту. Для раздельной компиляции
`compile -c --extern имя` оставляет объявленный интерфейс до компоновки.

### Проверка логики и симуляция по тактам

~~~powershell
arrowshdl test build/alu.json examples/alu_workbench/build/vectors.json --vectors -o build/alu/report.json
arrowshdl build examples/pulse_sequencer/project.toml -o build/sequencer.json
arrowshdl simulate build/sequencer.json examples/pulse_sequencer/build/scenario.json -o build/sequencer/trace.json
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
arrowshdl decode build/alu.json -o build/alu/decoded.json
arrowshdl encode build/alu/decoded.json -o build/alu/roundtrip.save.txt
arrowshdl graph build/alu/roundtrip.save.txt -o build/alu/graph.json
arrowshdl preview build/alu/roundtrip.save.txt -o build/alu/preview.png
arrowshdl health
~~~

`decode` читает сохранение, `encode` записывает его из JSON,
`graph` экспортирует клетки и физические зависимости,
`preview` рисует реальные стрелки; `health` проверяет работоспособность установленного пакета.

## Примеры

| Проект | Описание |
|---|---|
| [Minesweeper](examples/minesweeper/README.md) | Игра с безопасным первым кликом, каскадным открытием, счётчиками и статусом |
| [ALU Workbench](examples/alu_workbench/README.md) | Иерархическая ALU с восемью операциями и флагами результата |
| [Packet Router](examples/packet_router/README.md) | Маршрутизатор с проверкой чётности, арбитражем и backpressure |
| [Pulse Sequencer](examples/pulse_sequencer/README.md) | Семь генераторов, восемь режимов, память выбора и история сигнала на 64 такта |

Корень каждого примера содержит README, один TOML и Verilog-модули.
`build/` содержит выходные карты,
сценарии, отчёты и JSON; `visuals/` — изображения. Исторические клеточные
реализации сохранены в `tests/fixtures/historical`.

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
