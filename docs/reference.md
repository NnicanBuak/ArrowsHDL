# Справочник ArrowsHDL

ArrowsHDL компилирует синтезируемый поднабор Verilog/SystemVerilog в физическую схему Logic Arrows. Встроенные сообщения CLI выводятся на английском. В этом документе описаны формат проекта, команды, границы HDL и Python API.

## CLI

~~~powershell
arrowshdl init PATH NAME [--design none|empty|ports|grid]
arrowshdl compile logic.v --top logic_unit -o build/logic.save.txt
arrowshdl build logic.v --top logic_unit -o build/logic.save.txt
arrowshdl build -o build/logic.save.txt
arrowshdl build project.toml -o build/logic.save.txt --preview build/logic.png
arrowshdl link module.aho.json --top logic_unit -o build/linked.save.txt
arrowshdl test project.toml vectors.json --vectors -o build/report.json
arrowshdl test logic.v vectors.json --top logic_unit --vectors -o build/report.json
arrowshdl simulate build/logic.save.txt scenario.json -o build/trace.json
arrowshdl preview build/logic.save.txt -o build/preview.png
arrowshdl test --suite tests -o build/regression.json
arrowshdl health
~~~

Команды compile, build и link создают одно игровое сохранение .txt. Параметр --preview PATH при compile/build/link записывает ещё и PNG из той же физической карты. Отдельная команда preview может прочитать сохранение. Команды test и simulate создают JSON-отчёты; тестовые векторы и сценарии также задаются отдельными JSON-файлами.

Команды decode, encode и graph служат для явного преобразования или диагностики сохранения. Их JSON-выходы не являются результатом обычной сборки. Исключение для компиляции — compile -c: он сохраняет промежуточный RTLIL-объект .aho.json для последующего link.

`init` создаёт новый каталог проекта, базовый `project.toml` и стартовый
`NAME.v`. По умолчанию создаётся только минимальный проект; `--design` выбирает
заготовку `design.toml`: `empty`, `ports` или `grid` (значение `none` оставляет
sidecar-файл отключённым). Настройки project TOML задаются через `--standard`,
`-I`, `-D` и `-G`; порты design TOML добавляются через повторяемый
`--port NAME=WIDGET`. Команда не перезаписывает существующие файлы без `--force`.

`build` также принимает один `.v` или `.sv` без зависимостей. В этом режиме
используются `--top`, `--std`, `-I`, `-D` и `-G`; если `--top` не указан, берётся
stem имени исходного файла.

Если `PROJECT_OR_SOURCE` не указан, `build` ищет вход в текущей папке. Единственный
проектный TOML (`version`, `top`, `sources`) имеет приоритет над HDL-файлами;
если проектного TOML нет, используется единственный `.v` или `.sv`. При нуле или
нескольких подходящих файлах путь нужно указать явно.

Справка команд доступна через arrowshdl --help и arrowshdl NAME --help. Для compile доступны --std, -I, -D, -G, -L, --timeout, --max-cells, --input-bus и --input-bus-gap. Параметры -I, -D, -G и -L также доступны test при компиляции отдельных .v/.sv-исходников. Для project.toml верхний модуль и параметры задаются внутри файла проекта.

Единственный публичный переключатель компактного размещения — --layout compact. Он запускает современный автоматический алгоритм с дополнительным поиском. По умолчанию действует auto. В зависимости от типа схемы доступны sparse, fixed и macro-grid. Таймаут по умолчанию равен 600 секундам для компиляции и проверки. --max-cells задаёт максимальный размер физической карты.

Код завершения CLI: 0 — успех, 1 — тестовые ожидания не выполнены или проверка health не пройдена, 2 — ошибка аргументов, исходников либо выполнения. Во время сборки этапы и процент выводятся в stderr.

## Минимальный проект: от HDL до проверки

Создайте каталог проекта с тремя файлами. project.toml выбирает верхний HDL-модуль и его исходники. Пути sources отсчитываются от каталога файла TOML.

Файл logic.v:

~~~verilog
module logic_unit(input a, b, output y);
    assign y = a ^ b;
endmodule
~~~

Файл project.toml:

~~~toml
version = 3
top = "logic_unit"
sources = ["logic.v"]
parameters = {}

[language]
standard = "1364-2005"
~~~

Файл vectors.json содержит тестовые комбинации и ожидаемый выход:

~~~json
[
  {"inputs":{"a":0,"b":0},"expect":{"y":0}},
  {"inputs":{"a":0,"b":1},"expect":{"y":1}},
  {"inputs":{"a":1,"b":0},"expect":{"y":1}},
  {"inputs":{"a":1,"b":1},"expect":{"y":0}}
]
~~~

Из каталога проекта выполните:

~~~powershell
arrowshdl build project.toml -o build/logic.save.txt --preview build/logic.png
arrowshdl test project.toml vectors.json --vectors -o build/report.json
~~~

Сборка компилирует физическую карту и записывает сохранение, а --preview создаёт изображение из тех же клеток. Проверка отдельно компилирует project.toml в памяти, добавляет временные тестовые контакты и симулирует физическую схему. Она использует метаданные этой компиляции для сопоставления имён HDL-портов с физическими контактами.

Без TOML можно передать исходник напрямую:

~~~powershell
arrowshdl compile logic.v --top logic_unit -o build/logic.save.txt
arrowshdl test logic.v vectors.json --top logic_unit --vectors -o build/report.json
~~~

## TOML v3: HDL-проект и описание схемы

Формат `project.toml` использует версию 3.

### project.toml

Формат v3 требует top и sources. Поле language.standard выбирает режим чтения Verilog: 1364-2005 либо 1800-2023. Неизвестные поля и неподдерживаемые версии вызывают ошибку. Параметры верхнего HDL-модуля передаются таблицей parameters, например parameters = { WIDTH = 4 }. Также доступны include_dirs, defines, libraries и timing; пути к исходникам и design.toml задаются относительно project.toml.

Без design.toml компилятор строит схему только по HDL и автоматически назначает кнопки HDL-входам и индикаторы выходам.

### design.toml

design.toml необязателен и начинается с version = 1. Он может задавать порты, панели повторяемых модулей, дополнительные компоненты и надписи, а также физическое размещение.

~~~toml
version = 1

[[ports]]
path = "enable"
widget = "button"

[placement]
input_bus_gap = "auto"

[[placement.grids]]
instances = "rows[*].cols[*].tile"
origin = [120, 148]
step = [56, 70]
max_cell_size = [56, 64]
~~~

Путь instances выбирает иерархические экземпляры HDL. origin задаёт координаты первого элемента, step — разнос экземпляров по X и Y. Если реальный размер экземпляра больше max_cell_size или шаблон не выбрал ни одного экземпляра, сборка сообщает ошибку. Ограничение влияет на положения элементов и их проверку; оно не служит подсказкой, которую компилятор может проигнорировать. Для отдельного экземпляра используйте [[placement.placements]] с полями instance и at.

В design.toml можно также описать:

- ports: виджеты HDL-портов, размер и скрытие; входы по умолчанию получают button, выходы — indicator.
- views: панель из кнопки и одного или двух выходов повторяемого HDL-модуля.
- components: встроенные компоненты library:seven_segment и library:history64, подготовленные компоненты или текстовые надписи.
- labels: подписи по шрифту.
- placement: сетки, явные координаты экземпляров и размещение входных шин.

## Поддерживаемый HDL

Фронтенд использует Yosys. Поддерживаются комбинационные выражения, арифметика и сравнение, условные выражения, статические циклы и generate, иерархия, параметры, шины, always @* и always_comb. Значение --std задаёт режим чтения и не означает полной поддержки стандарта.

Не поддерживаются VHDL, классы, динамические структуры, произвольные последовательностные always-блоки, HDL-память и неподдерживаемые Yosys-ячейки. Для состояния используются нативные модули ArrowsHDL. Компилятор проверяет модули, направления и ширины портов, подключения, неопределённые сети, конфликт драйверов и соответствие электрических контактов.

## Нативная библиотека

Встроенная библиотека HDL подключается автоматически. Ключевые модули:

| Модуль | Назначение |
| --- | --- |
| arrows_register #(WIDTH) | Записывает D при активном load, сохраняет значение при снятом load |
| arrows_latch | Память установки и сброса с приоритетом set |
| arrows_clock #(PERIOD) | Автономный генератор с полным периодом |
| arrows_rise | Импульс при переходе сигнала из 0 в 1 |
| arrows_edge | Импульс при изменении сигнала в любом направлении |
| arrows_toggle | Переключает состояние на каждом активном игровом такте |
| arrows_random | Нативный независимый генератор случайности |
| arrows_button / arrows_indicator | Кнопка и индикатор физического интерфейса |
| arrows_logic #(OP) | Низкоуровневая нативная операция с контактами I, B и S |
| arrows_cell #(TYPE,X,Y,ROTATION,MIRRORED) | Низкоуровневый физический примитив |

Память задаётся библиотечными экземплярами, а не произвольной HDL-секвенциальной логикой. Параметры модуля указываются стандартным Verilog-синтаксисом. Физическое состояние считывается симулятором по игровым тактам; схема не является обычной симуляцией RTL на каждом фронте HDL-такта. Подробные контакты примитивов заданы в [native-rules.md](native-rules.md).

## Проверка и симуляция

При --vectors файл тестов содержит массив inputs/expect с именами HDL-портов и целыми значениями шин. Входы и выходы сопоставляются с контактами при компиляции физической схемы. Проект или исходник компилируется в памяти при каждом вызове test.

Физический сценарий задаёт ticks, необязательные frame_ticks и seed, входы inputs, нажатия controls, точки observe и проверки expect/assert. Пример:

~~~json
{"ticks":20,"frame_ticks":[10,10],"seed":123456789,
 "inputs":[{"at":[0,0],"values":[0,1]}],
 "expect":[{"at":[4,0],"values":[0,1]}],
 "observe":[[2,0]]}
~~~

Команда test может запустить этот сценарий непосредственно от HDL-проекта. Команда simulate принимает сохранение .txt и тот же сценарий. При отсутствии проверок simulate выдаёт трассу; это само по себе не доказывает функциональную корректность. API и независимые примеры тестирования приведены ниже и в каталогах examples.

## Python API

~~~python
import arrowshdl

compiled = arrowshdl.build("project.toml", layout="compact")
print(len(compiled.cells), compiled.metadata["settle_ticks"])
report = arrowshdl.test("project.toml", "vectors.json", vectors=True)
~~~

BuildResult содержит клетки, публичные порты, метаданные и пути созданных артефактов. compile, build и link без out возвращают результат в памяти; при заданном out записывают одно игровое сохранение. preview можно передать вместе с out, чтобы создать и PNG. compile_object и link работают с промежуточными RTLIL-объектами .aho.json. simulate выполняет сценарий для клеток в памяти или для игрового сохранения.

Кодек arrowasm позволяет явно читать/записывать сохранение. mapdata предоставляет хеш канонической карты и экспорт диагностического графа. Симулятор возвращает JSON-совместимый отчёт.

## Сохранения и вспомогательные файлы

Игровая карта записывается в .txt в формате импорта Logic Arrows. Для воспроизводимого сравнения используется SHA-256 точных байтов сохранения и отдельный хеш канонической модели клеток.

Отчёты test/simulate, сценарии и векторы используют JSON. Отдельная команда decode может экспортировать диагностическое представление карты, а graph — список физических зависимостей. Эти файлы предназначены для просмотра и преобразования. Сборка не использует их как замену HDL-исходников или результата project.toml.
