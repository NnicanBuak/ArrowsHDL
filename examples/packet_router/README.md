# Packet Router

**Маршрутизатор двух входов на два выхода:** проверка чётности, арбитраж
конкурирующих кадров и подтверждение передачи с учётом готовности приёмника.
Проект показывает композицию повторяемых HDL-модулей и проверку протокола.

![Устройство маршрутизатора](visuals/architecture.png)

Кадр `frame[5:0]`: бит 5 — номер выхода, бит 4 — чётность,
биты 3…0 — данные. XOR пяти младших битов должен быть равен 0.
`valid[i]` сообщает наличие кадра; `error[i]` отмечает неверную чётность
только у присутствующего кадра.

Для каждого выхода `output_lane` выбирает подходящий корректный кадр.
**Вход 0 имеет приоритет** при совпадении назначения.
`output_valid[lane]` и данные видны даже при `ready[lane]=0`;
`accepted[i]` появляется лишь у победителя, когда выход готов.
Очереди и памяти в этом проекте нет: отправитель удерживает кадр до принятия.

## Сборка и проверка

Из корня ArrowsHDL:

~~~powershell
arrowshdl build examples/packet_router/project.toml --layout macro-grid -o examples/packet_router/build
arrowshdl test examples/packet_router/build/packet_router.save.txt examples/packet_router/vectors.json --vectors --manifest examples/packet_router/build/packet_router.build.json -o build/router-demo.report.json
python -m unittest tests.projects.examples.test_showcases.ShowcaseTests.test_router_all_65536_frames_controls_and_backpressure -v
~~~

[Сохранение](build/packet_router.save.txt): **11 221 стрелка, 204×505**.
Кнопки задают биты входов; индикаторы показывают данные, valid, accepted и error.
Порядок битов, контакты и `settle_ticks`: [manifest](build/packet_router.build.json).
[Полный отчёт](build/packet_router.report.json) проверяет **65 536** наборов:
все кадры, valid и ready. Модель ожиданий независимо описана в tests.

![Чётность, конкуренция и backpressure](visuals/behavior.png)

Строки демонстрируют параллельную передачу, конфликт назначения, блокировку
одного выхода, повреждённый кадр, отсутствие valid и приоритет входа 0.
Битовые маски приведены десятичными числами: например, 3 означает два активных бита.

[Физическая карта](visuals/map.png) ·
[Измерения с хешем сохранения](visuals/behavior.report.json).
Воспроизведение изображений: `python tools/render_examples.py`.
