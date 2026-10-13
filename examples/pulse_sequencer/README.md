![Скомпилированная схема Pulse Sequencer](visuals/map.png)

# Pulse Sequencer

Восемь кнопок переключают независимые биты памяти. selection_memory фиксирует нажатие и выбирает младший активный режим; oscillator_bank содержит семь автономных генераторов; waveform_selector выбирает сигнал. project.toml соединяет HDL-модули с дисплеем history64 из встроенной библиотеки.

Режим 0 отключает выход. Периоды режимов 1–7: 20, 24, 32, 40, 48, 64 и 80 игровых тактов. Удержание кнопки даёт одно переключение; повторное нажатие выключает соответствующий бит. Индикаторы active и selection показывают память и выбранный режим. История продвигается на одну клетку за такт.

## Сборка и проверка

Из корня репозитория:

~~~powershell
arrowshdl build examples/pulse_sequencer/project.toml -o examples/pulse_sequencer/build/pulse_sequencer.save.txt --preview examples/pulse_sequencer/visuals/map.png
python -m unittest tests.projects.examples.test_sequencer.SequencerTests.test_modes_held_buttons_priority_and_history -v
~~~

Тест компилирует исходный проект и проверяет **восемь режимов**, периоды, удержание кнопок, все 256 масок выбора и историю на 64 такта.

![Физическая временная диаграмма](visuals/behavior.png)

Иллюстрации пересобираются командой python tools/render_examples.py.
