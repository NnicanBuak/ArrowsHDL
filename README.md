# ArrowsHDL

ArrowsHDL компилирует Verilog/SystemVerilog в физические схемы Logic Arrows.
CLI и Python API позволяют собрать проект, проверить его поведение и экспортировать игровое сохранение.

**Версия 0.1.1 экспериментальная.**

## Установка

Нужны **Python 3.11+ и pip**. Скачайте wheel своей платформы со
[страницы релизов](https://github.com/NnicanBuak/ArrowsHDL/releases):

| Платформа | Окончание имени wheel |
| --- | --- |
| Windows x64 | `win_amd64.whl` |
| Linux x64 | `manylinux_2_17_x86_64.whl` |
| macOS 14+ Intel | `macosx_14_0_x86_64.whl` |
| macOS 14+ Apple Silicon | `macosx_14_0_arm64.whl` |

~~~powershell
python -m pip install "ПОЛНЫЙ_ПУТЬ_К_СКАЧАННОМУ_WHEEL.whl"
arrowshdl health
~~~

Wheel содержит готовый нативный симулятор. Yosys, Node.js и Pillow устанавливаются
через pip; **Rust/Cargo для установки и запуска wheel не требуется**.
Команды установки и `health` выполняются из любого каталога.

## Быстрый старт

Из корня репозитория после установки пакета:

~~~powershell
arrowshdl build examples/alu_workbench/project.toml --layout compact -o build/alu.save.txt --preview build/alu.png
arrowshdl preview build/alu.save.txt -o build/alu-preview.png
~~~

Для одного HDL-файла без `project.toml` можно использовать ту же команду:

~~~powershell
arrowshdl build logic.v -o build/logic.save.txt
~~~

В этом режиме верхний модуль по умолчанию совпадает с именем файла; другой
модуль задаётся через `--top`.

Если команда запускается внутри папки, где находится ровно один проектный
TOML-файл или ровно один `.v`/`.sv`, путь можно не указывать:

~~~powershell
arrowshdl build -o build/logic.save.txt
~~~

Чтобы сразу скопировать игровое сохранение в буфер обмена, файл указывать не
обязательно:

~~~powershell
arrowshdl build --clipboard
~~~

Флаги `--clipboard` и `-o` можно использовать одновременно. Для `--preview`
по-прежнему требуется `-o`, потому что preview строится из сохранения на диске.

Сборка записывает одно игровое сохранение `.txt`; `--preview PNG` создаёт изображение
той же карты. По умолчанию действует `--layout auto`; `--layout compact` добавляет
поиск компактного размещения, включая нативную память и интерфейсы.

Новый проект можно создать командой `init`:

~~~powershell
arrowshdl init C:/Users/you/projects xor_demo --design ports --standard 1364-2005
~~~

Команда создаёт каталог `xor_demo` с `project.toml`, `xor_demo.v` и выбранным
`design.toml`. Доступны preset-варианты `--design none|empty|ports|grid`.
Параметры проекта можно задать флагами `--standard`, `-I`, `-D` и `-G`, а
настройки портов — повторяемым `--port NAME=WIDGET`, где `WIDGET` это
`button`, `indicator` или `binary`. Существующие сгенерированные файлы защищены
от перезаписи; для явной замены используется `--force`.

`project.toml` **версии 3** задаёт верхний HDL-модуль и исходники.
Необязательный `design.toml` описывает кнопки, дисплеи и размещение.
Повторяемые модули компилируются один раз и сохраняются в системном кеше.
Клетки, порты и метаданные доступны через `BuildResult` в Python API.

## Проверка своего проекта

Создайте `logic.v`, `project.toml` и `vectors.json` по
[минимальному примеру](docs/reference.md#минимальный-проект-от-hdl-до-проверки).
Из каталога проекта можно проверить TOML или отдельный исходник:

~~~powershell
arrowshdl test project.toml vectors.json --vectors -o build/report.json
arrowshdl test logic.v vectors.json --top logic_unit --vectors -o build/source-report.json
~~~

Каждый вызов `test` компилирует исходники в памяти и проверяет физическую схему.
Векторы задают именованные `inputs` и ожидаемые `expect`.
Для симуляции готового сохранения используйте `simulate` с физическим сценарием.

## Примеры

| Проект | Что показывает |
| --- | --- |
| [Mini Calculator](examples/mini_calculator/README.md) | Арифметика, логика, сдвиг, сохранение результата и семисегментный дисплей |
| [8-bit Comparator](examples/comporator_8bit/README.md) | Сравнение двух байтовых операндов и физические кнопки |
| [ALU Workbench](examples/alu_workbench/README.md) | 4-битная ALU, восемь операций, иерархия и флаги |
| [Packet Router](examples/packet_router/README.md) | Чётность, арбитраж и backpressure |
| [Pulse Sequencer](examples/pulse_sequencer/README.md) | Генераторы, память выбора и история на 64 такта |
| [Minesweeper](examples/minesweeper/README.md) | Поле 10×10, повторяемые HDL-ячейки и заданная сетка |

README каждого примера содержит команду сборки, точный регрессионный тест и изображения.
Исторические схемы сохранены в [tests/fixtures/historical](tests/fixtures/historical).

## Разработка и регрессии

Установка из исходников для разработки дополнительно требует Rust/Cargo.
Для тестового окружения с NumPy 2.5.4 нужен **Python 3.12+**:

~~~powershell
python -m pip install -e ".[test]"
arrowshdl test --suite tests -o build/regression.json
~~~

Набор `unittest` проверяет компилятор, симулятор, публичный API и четыре примера.
Тестовые данные находятся в `tests/fixtures`. Иллюстрации пересобираются командой
`python tools/render_examples.py`.

Полный набор регрессий запускается вручную при разработке. Релизный CI выполняет
аудит wheel, проверку чистой установки и короткие проверки CLI, API и нативного движка.

## Документация и лицензия

Поддерживается синтезируемый поднабор Verilog/SystemVerilog; состояние задаётся
нативными модулями библиотеки. Форматы, команды, Python API и границы HDL описаны
в [справочнике](docs/reference.md). Устройство компилятора описано в
[ARCHITECTURE.md](ARCHITECTURE.md), история выпусков — в [CHANGELOG.md](CHANGELOG.md).

Собственный код: [PolyForm Noncommercial 1.0.0](LICENSE), [NOTICE](NOTICE).
Сторонние материалы: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
