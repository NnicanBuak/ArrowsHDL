![Скомпилированное поле Minesweeper V2 5×5](../visuals/board.png)

# Сапёр V2

Версия компактной ячейки **56×64, 2164 стрелки**.
Логика описана в `cell.v`, `cell_top.v`, исходниках полей и контроллера;
геометрия — в JSON и физическом TOML старого формата. Готовые карты сохранены
как исторические регрессионные фикстуры.

Из корня ArrowsHDL с установленным ArrowsHDL:

```powershell
python -m unittest tests.projects.minesweeper.test_saved_maps.MinesweeperRegressionTests.test_v2_compact_maps_and_preparation_arbitration -v
```

Проверка включает поля 3×3, 5×5 и 10×10. Компиляция HDL v3 показана в
[текущем примере](../../../../../examples/minesweeper/README.md).
Полный проверяемый запуск и ограничения: [описание проекта](../README.md).
Проверки создают сценарии и отчёты в памяти; папка сборки содержит только
итоговые сохранения схем.
