# GraphDLC core and cycle optimizer

Vendored from https://github.com/MerinPrime/GraphDLC at commit
`01232bdef7d0d399432ddd1a5a5f57e9fcbd4d1b` (read 2026-10-06).

`core/src` contains the unmodified Rust native engine. The local Cargo manifest
builds it as an rlib for a single-threaded CLI instead of a browser cdylib.
`ts` contains the unmodified cycle search/validation code, node type mapping,
arrow relationships and coordinate transforms. Original MIT license is included.

Browser UI, settings, rendering, extension installation and snapshots are not
part of the CLI. The headless adapter supplies a synchronous bounded scheduler.
The engine uses global mutable state: never run two simulations concurrently
inside the same process. Separate CLI processes are independent.
