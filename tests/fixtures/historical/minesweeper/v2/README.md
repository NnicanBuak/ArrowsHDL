![Скомпилированное поле Minesweeper V2 5×5](../visuals/board.png)

# Сапёр V2

Версия компактной ячейки **56×64, 2164 стрелки**.
Логика описана в `cell.v`, `cell_top.v`, исходниках полей и контроллера;
геометрия — в JSON и физическом TOML. Карты собирает общий ArrowsHDL.

Из корня ArrowsHDL с установленным ArrowsHDL:

```powershell
arrowshdl build examples/minesweeper/v2/cell.toml -o examples/minesweeper/v2/build
arrowshdl build examples/minesweeper/v2/minesweeper_3x3.toml -o examples/minesweeper/v2/build
arrowshdl build examples/minesweeper/v2/minesweeper_10x10.toml -o examples/minesweeper/v2/build
```

Поле 5×5: `arrowshdl build examples/minesweeper/v2/minesweeper_5x5.toml -o examples/minesweeper/v2/build`.
Полный проверяемый запуск и ограничения: [описание проекта](../README.md).
Проверки создают сценарии и отчёты в памяти; папка сборки содержит только
итоговые сохранения схем.
