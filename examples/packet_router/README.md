![Скомпилированная схема Packet Router](visuals/map.png)

# Packet Router

Маршрутизатор двух входов на два выхода с проверкой чётности, арбитражем конкурирующих кадров и подтверждением передачи при готовом приёмнике. Пример показывает повторяемые HDL-модули и проверку протокола.

![Устройство маршрутизатора](visuals/architecture.png)

Кадр frame[5:0]: бит 5 — номер выхода, бит 4 — чётность, биты 3…0 — данные. XOR пяти младших битов должен быть равен 0. Вход 0 имеет приоритет при совпадении назначения. Данные и output_valid доступны даже при ready=0; accepted появляется только у выигравшего кадра, когда соответствующий выход готов. Очередей нет: отправитель удерживает кадр до принятия.

## Сборка и проверка

Из корня репозитория:

~~~powershell
arrowshdl build examples/packet_router/project.toml --layout compact -o examples/packet_router/build/packet_router.save.txt --preview examples/packet_router/visuals/map.png
python -m unittest tests.projects.examples.test_showcases.ShowcaseTests.test_router_all_65536_frames_controls_and_backpressure -v
~~~

Независимая регрессия компилирует проект из исходников и проверяет **65 536 сочетаний** кадров, valid и ready. Сохранение и PNG при сборке получаются из одной физической карты.

![Чётность, конкуренция и backpressure](visuals/behavior.png)

[Физическая карта](visuals/map.png). Иллюстрации пересобираются командой python tools/render_examples.py.
