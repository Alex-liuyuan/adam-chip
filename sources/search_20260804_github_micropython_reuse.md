# GitHub reuse survey for MicroPython/CanMV contract work

Date: 2026-08-04

The Parallel Web API was unavailable because `PARALLEL_API_KEY` was not set.
Repository metadata, trees, README files, licenses, and selected source files
were checked through the GitHub API and raw GitHub content instead.

## Recommended production inputs

- https://github.com/micropython/micropython
  - MIT core and official `makemoduledefs.py`, `makeqstrdefs.py`,
    `makeqstrdata.py`, `mpremote`, `pyboard.py`, and `tests/run-tests.py`.
  - Use as the authority for build facts, device transport, and the standard
    MicroPython regression harness.
- https://github.com/Josverl/micropython-stubber
  - Top-level MIT; board-side `createstubs` variants enumerate configured
    modules with runtime `dir()` and `getattr()` and generate firmware stubs.
  - Reuse for runtime API inventory. Its own documentation states that
    parameter details are generally unavailable, so behavior probes remain
    necessary.
- https://github.com/RT-Thread-packages/micropython
  - MIT RT-Thread MicroPython port for RT-Thread 3.0 and newer.
  - Use as the initial production VM/RTOS integration base, from a locked
    immutable export rather than an ambient checkout.
- https://github.com/openmv/openmv
  - Useful source for MIT-licensed image and Python binding components.
  - The repository also contains GPL, proprietary, and non-commercial pieces;
    only file-level approved components may be selected, with GPL features
    disabled where required.

## Reference or auxiliary inputs

- https://github.com/kendryte/canmv_k230
  - Current official K230 CanMV build tree, but no repository-level license was
    detected. Keep it in internal-evaluation/reference-only classification
    unless file-level licensing or vendor authorization is established.
- https://github.com/kendryte/k230_canmv_docs
  - Official API documentation source; no repository-level license was
    detected. Use links and observations as requirement evidence, not copied
    production content.
- https://github.com/canmv-k230/micropython
  - CanMV MicroPython fork and useful version-matched build-tool reference.
    Lock the exact commit and audit changed files before production reuse.
- https://github.com/dhylands/rshell and https://github.com/thonny/thonny
  - Mature MIT MicroPython transports, but MicroPython's own `mpremote` and
    `pyboard.py` already cover the required non-interactive automation with a
    smaller dependency boundary.
- https://github.com/rizsotto/Bear
  - GPL host tool for generating `compile_commands.json`; optional only when
    the selected build system cannot emit a compilation database itself.
- https://github.com/doxygen/doxygen
  - Documentation metadata only, not a semantic API authority.
- https://github.com/tree-sitter/tree-sitter-c and
  https://github.com/eliben/pycparser
  - Useful syntax tools but unsuitable as authorities for expanded
    MicroPython macro/object-table semantics.

## Integration decision

Use MicroPython's exact locked build flow for module/qstr facts, feed its
module list into `micropython-stubber`, execute the board script through
`mpremote` or `pyboard.py`, and run contract-specific behavior scripts through
MicroPython's existing remote test harness. Do not resume the custom compiler
front-end/parser approach.
