# Generic SoC Image Factory

This project builds a software image from SoC and board hardware materials. The
production entry point does not accept a vendor SDK, firmware image, defconfig,
toolchain path, operating-system choice, or prewritten target contract.

## Start a run

```sh
python3 soc_image.py run \
  --material /path/to/soc-manual.pdf \
  --material /path/to/board-schematic.pdf \
  --out runs/board-a
```

The intake stage copies each material into the run by content hash and writes
`materials.lock.json`. It then writes `hardware_ir.json`, `unknowns.json`,
`conflicts.json`, `reference_profile.json`, `software_requirements.json`, `plan.json`, and `state.db`. PDF and image observations stay
as non-executable candidates; only provenance-bound SVD/DTS facts can enable a
capability. Agent attempts run in isolated Git worktrees under `candidates/`;
verified patches are promoted into the run-local `integration/` tree and
snapshotted by hash under `artifacts/`. Repeating the command is allowed only
when every input hash matches the existing lock.

```sh
python3 soc_image.py status --run runs/board-a
python3 soc_image.py resume --run runs/board-a
```

`run` is the only production entry point. It creates `runs/board-a/adaptation-repository/chip`, then every planned
capability is executed by its engineering Agent in an isolated Git worktree. The deterministic generators provide only
an initial scaffold; each Agent must inspect sources, adapt code and run engineering checks. A failed check gets one
bounded repair round. Verified Agent outputs are synchronized into the five SYSUOS provider contracts.

`sdk init-soc` remains an SDK authoring utility for an exported kit. It is not a second production workflow.

Later stages derive the hardware contract, software capabilities, target
sources, image, simulation and board-validation plan from this locked input.

## Reference artifacts

The existing K230 `sdk.img` is a black-box regression reference. Its manifest
sets `build_input_allowed=false`; it must never provide a boot region, partition
payload, overlay base, firmware component or other input to a generated image.

The former K230/CanMV pipeline remains temporarily available for baseline
regression while the staged migration proceeds. It is not the production entry
point and cannot be reached from `soc_image.py`.

## Checks

```sh
python3 tools/run_strict_tests.py
python3 tools/clean_checkout_test.py
```

Implementation phases are ordered by `tools/phase_gate.py`. A phase cannot
begin unless the preceding phase report passed and is bound to the current Git
commit.
