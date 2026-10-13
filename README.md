# ArrowsHDL

ArrowsHDL компилирует Verilog/SystemVerilog в физические схемы Logic Arrows. Он предоставляет CLI и Python API для сборки, симуляции и проверки схем.

## Требования и установка

Для установки готового пакета нужны Python 3.11 или новее и pip. Yosys, Node.js и Pillow устанавливаются как зависимости; wheel содержит скомпилированный симулятор, поэтому Rust/Cargo для установки готового пакета не нужен.

1. Откройте [страницу релизов ArrowsHDL](https://github.com/NnicanBuak/ArrowsHDL/releases).
2. В разделе Assets нужного релиза скачайте wheel для своей ОС и архитектуры. Архивы Source code для установки не подходят.
3. Установите скачанный файл и проверьте пакет:

~~~powershell
python -m pip install "ПОЛНЫЙ_ПУТЬ_К_WHEEL.whl"
arrowshdl health
~~~

Релиз [v0.1.0](https://github.com/NnicanBuak/ArrowsHDL/releases/tag/v0.1.0) содержит wheel для Windows x64, Linux x64 и macOS 14+ (Intel и Apple Silicon), а также файл контрольных сумм SHA256SUMS.txt. Успешная команда health завершается кодом 0.

## Быстрый старт

Проект содержит HDL-исходники и обязательный файл проекта; описание интерфейса и размещения подключается при необходимости.

- HDL-файлы .v и .sv задают модули, экземпляры и электрические соединения.
- project.toml выбирает верхний модуль, исходники и параметры сборки.
- design.toml необязателен; в нём можно задать виджеты, дисплеи и координаты экземпляров.

~~~powershell
arrowshdl build examples/alu_workbench/project.toml -o build/alu.save.txt --preview build/alu.png
arrowshdl test examples/alu_workbench/project.toml tests/fixtures/examples/alu_workbench/vectors.json --vectors -o build/alu.report.json
~~~

Команда build создаёт игровое сохранение .save.txt; параметр --preview дополнительно создаёт PNG из той же сборки. Команда test компилирует исходный проект в памяти и проверяет физическую схему по векторам. Проверка не зависит от заранее собранного сохранения.

Справочник: [структура TOML-проекта](docs/reference.md#toml-v3-hdl-проект-и-описание-схемы), [CLI](docs/reference.md#cli), [поддерживаемый HDL](docs/reference.md#поддерживаемый-hdl), [нативные модули](docs/reference.md#нативная-библиотека), [полный минимальный проект](docs/reference.md#минимальный-проект-от-hdl-до-проверки).

## HDL и Verilog

**HDL (Hardware Description Language)** — язык описания аппаратуры. Он описывает цифровые схемы через модули, сигналы, логические операции, связи и поведение, которое затем можно симулировать или синтезировать в физическую схему.

**Verilog** — язык описания аппаратуры для проектирования, моделирования и синтеза цифровых схем. **SystemVerilog** — расширение Verilog с дополнительными средствами RTL-проектирования и проверки.

### Материалы для изучения

- [Hardware description language (HDL)](https://en.wikipedia.org/wiki/Hardware_description_language) — общее описание HDL и области применения.
- [HDLBits](https://hdlbits.01xz.net/wiki/Main_Page) — практические задачи по цифровой логике и Verilog.
- [Verilog Design Guide](https://verilogguide.readthedocs.io/en/latest/) — учебное руководство по синтаксису и основным конструкциям Verilog.
- [IEEE Verilog/SystemVerilog standards](https://standards.ieee.org/ieee/1364/2052/) — официальная справочная информация по стандартам языка.

## Документация ArrowsHDL

| Материал | Что содержит |
| --- | --- |
| [Справочник](docs/reference.md) | CLI, `project.toml`, `design.toml`, поддерживаемый HDL, API, тесты и симуляция |
| [Правила нативных модулей](docs/native-rules.md) | Контакты и ограничения встроенных компонентов ArrowsHDL |
| [Оптимизация нативной симуляции](docs/native-simulation-optimization.md) | Детали производительности и прохождения игровых тактов |
| [Архитектура](ARCHITECTURE.md) | Внутренние стадии компиляции и основные компоненты проекта |
| [Симулятор](SIMULATOR.md) | Формат и правила физической симуляции |
| [Примеры](examples/) | Готовые проекты с HDL, конфигурацией, схемами и проверками |

Для быстрого старта достаточно открыть [минимальный проект от HDL до проверки](docs/reference.md#минимальный-проект-от-hdl-до-проверки), а затем посмотреть [ограничения поддерживаемого HDL](docs/reference.md#поддерживаемый-hdl). ArrowsHDL поддерживает **синтезируемый поднабор Verilog/SystemVerilog**, а не весь стандарт: произвольная последовательностная логика и VHDL не поддерживаются.

## Сборка из командной строки

Полная компиляция файла без project.toml и сборка проекта выглядят так:

~~~powershell
arrowshdl compile examples/alu_workbench/arithmetic.v --top arithmetic -G WIDTH=4 -o build/arithmetic.save.txt --preview build/arithmetic.png
arrowshdl build examples/packet_router/project.toml --layout compact -o build/router.save.txt
~~~

Для build, compile и link выходной файл -o должен быть игровым сохранением .txt. Флаг --preview PATH при полной компиляции создаёт ещё один файл PNG. Предпросмотр уже готовой карты можно получить отдельной командой:

~~~powershell
arrowshdl preview build/router.save.txt -o build/router.png
~~~

По умолчанию используется --layout auto. Единственный публичный выбор компактного размещения — --layout compact. Он использует современный автоматический алгоритм с дополнительным поиском. Также доступны sparse, fixed и macro-grid там, где их поддерживает команда. Автоматический поиск ограничен таймаутом и не гарантирует глобальный минимум.

Для раздельной компиляции компилятор может сохранить внутренний объект RTLIL, который затем принимает link:

~~~powershell
arrowshdl compile -c examples/alu_workbench/arithmetic.v --top arithmetic -o build/arithmetic.aho.json
arrowshdl link build/arithmetic.aho.json --top arithmetic -o build/linked.save.txt
~~~

Файл .aho.json предназначен только для промежуточного объекта компиляции. Обычные compile/build/link выдают игровое сохранение.

Повторные сборки проекта используют системный кеш скомпилированных HDL-модулей. Ключ зависит от исходников, include-файлов, параметров, стандарта и настроек компилятора; переменная ARROWSHDL_CACHE_DIR позволяет выбрать другой каталог кеша.

## Проверка и симуляция

Векторы задаются JSON-массивом объектов inputs/expect. Пример и команды находятся в [минимальном проекте](docs/reference.md#минимальный-проект-от-hdl-до-проверки). Тест запускается от проекта или исходника:

~~~powershell
arrowshdl test project.toml vectors.json --vectors -o build/report.json
arrowshdl test logic.v vectors.json --top logic_unit --vectors -o build/report.json
~~~

Для сценария с кнопками, наблюдениями и игровыми тактами используйте test с исходным проектом либо simulate с готовым сохранением:

~~~powershell
arrowshdl test project.toml scenario.json -o build/game.report.json
arrowshdl simulate build/game.save.txt scenario.json -o build/trace.json
~~~

Отчёт теста содержит результат проверок и хеш исходной физической карты. Выходы тестов и симуляций — JSON-отчёты; они не являются файлами сборки. Код завершения test: 0 — проверки пройдены, 1 — ожидания не выполнены, 2 — ошибка команды.

Запустить регрессионные тесты из исходного репозитория можно отдельно:

~~~powershell
arrowshdl test --suite tests -o build/regression.json
~~~

## Примеры

| Проект | Что показывает |
| --- | --- |
| [Minesweeper V2](examples/minesweeper/README.md) | Игра 10×10, физическая сетка экземпляров и проверка поведения |
| [ALU Workbench](examples/alu_workbench/README.md) | Иерархия модулей, параметры, арифметика и векторы |
| [Packet Router](examples/packet_router/README.md) | Соединение HDL-блоков и проверка протокола |
| [Pulse Sequencer](examples/pulse_sequencer/README.md) | Нативная память, генераторы, история сигнала и временная симуляция |

В каждом каталоге примера находятся HDL, project.toml, иногда design.toml, README и PNG-изображения собранной схемы. Проверки запускаются отдельно от сборки и компилируют проект непосредственно из исходников.

## Python API и разработка

~~~python
import arrowshdl

result = arrowshdl.build("project.toml", layout="compact")
print(len(result.cells), result.metadata["settle_ticks"])
report = arrowshdl.test("project.toml", "vectors.json", vectors=True)
~~~

Без параметра out API возвращает клетки, порты и метаданные в памяти. Если передать out, API сохранит только игровой файл .txt. Параметр preview позволяет дополнительно записать PNG.

Для установки из исходного дерева разработки необходим Rust/Cargo:

~~~powershell
python -m pip install -e ".[test]"
arrowshdl test --suite tests -o build/regression.json
~~~

## Ограничения

Поддерживается синтезируемый поднабор Verilog/SystemVerilog. Произвольная поведенческая последовательная логика не поддерживается; память и таймеры задаются нативными модулями ArrowsHDL. Сложная автоматическая разводка ограничена таймаутом и бюджетом клеток.

Подробности: [справочник](docs/reference.md). Лицензия: [PolyForm Noncommercial 1.0.0](LICENSE). Сведения о сторонних материалах: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
