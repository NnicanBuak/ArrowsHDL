# Сапёр V1

Версия исходной ячейки **112×112**.
Логика описана в `cell.v`, `cell_top.v`, исходниках полей и контроллера;
геометрия — в JSON и физическом TOML. Карты собирает общий ArrowsHDL.

Из корня ArrowsHDL с установленным ArrowsHDL:

```powershell
arrowshdl build examples/minesweeper/v1/cell.toml -o examples/minesweeper/v1/build
arrowshdl build examples/minesweeper/v1/minesweeper_3x3.toml -o examples/minesweeper/v1/build
arrowshdl build examples/minesweeper/v1/minesweeper_10x10.toml -o examples/minesweeper/v1/build
```

Сохранения V1 побайтно воспроизводят исходный комплект previous-112:
[проверка сохранности](preservation.json). Их точные SHA-256 также закреплены
в регрессионной фикстуре ArrowsHDL.
Полный проверяемый запуск и ограничения: [описание проекта](../README.md).
[Итоговый отчёт](build/regression.json). По одному финальному комплекту на карту.
