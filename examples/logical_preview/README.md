# Logical Preview

Небольшой пример для `--style logical`: каждый блок `transform` выделен рамкой,
цветные линии проходят внутри модулей и по соединительным проводам, оставляя
свободными клетки логических операторов. Все четыре входа и оба выхода подписаны.

```powershell
arrowshdl build examples/logical_preview/project.toml -o build/logical_preview.json
arrowshdl preview build/logical_preview.json --style logical -o build/logical_preview.png
```

Исходная схема находится в `logical_preview.v`. В ней два экземпляра `transform`
и четыре входа: `a`, `b`, `c`, `d`.
