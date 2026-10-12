# Сторонние материалы

Собственный код ArrowsHDL распространяется по PolyForm Noncommercial 1.0.0;
`Required Notice: Copyright 2026 Nnican`. Эта лицензия не заменяет лицензии
и авторство следующих материалов.

- **GraphDLC**, MerinPrime, MIT. Исходники в `vendor/graphdlc`, commit
  `01232bdef7d0d399432ddd1a5a5f57e9fcbd4d1b`; оригинальный текст лицензии
  в [vendor/graphdlc/LICENSE](vendor/graphdlc/LICENSE), копия входит в пакет.
  Локальные CLI-адаптеры и сборка отделены от исходного движка.

- Устанавливаемые зависимости **Yosys/yowasp-yosys, Pillow, Node.js**
  сохраняют лицензии своих дистрибутивов. Cargo-зависимости перечислены
  в `native/Cargo.lock`, npm-зависимости сборки — в `tools/package-lock.json`.
  Тексты MIT/Apache/Unicode для точных версий Rust-зависимостей и MIT для
  esbuild включены в `arrowshdl/data/licenses` вместе с лицензией GraphDLC.

- **Logic Arrows**, Аркадий Чубрик: игровые правила и изображения стрелок
  в `src/arrowshdl/data/sprites`. Авторство сохраняется; разрешение на
  распространение этих ресурсов необходимо подтвердить перед публикацией.

- Учебные модули Nandland в `tests/fixtures/circuits/hdl/half_adder` и
  `full_adder` сохраняют ссылки на оригиналы и не входят в wheel.
  Условия использования этих фрагментов требуют отдельной проверки.
  Изображение исходной схемы в `tests/fixtures/circuits/reference_adder8`
  используется только регрессией распознавания и тоже не входит в wheel.


## Arrow 4 bitmap font

`src/arrowshdl/data/fonts/arrow4.json` preserves the bitmap glyphs extracted
from the saved arrow alphabet at https://logic-arrows.io/map--132oac3.
The source map hash and derivation notes are retained in the font document.
Original authorship of the source map and game materials is retained.
The generated display wiring is part of ArrowsHDL.
