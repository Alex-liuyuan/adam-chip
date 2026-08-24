# Generic SoC Image Factory

This project builds a software image from SoC and board hardware materials. The
production entry point does not accept a vendor SDK, firmware image, defconfig,
toolchain path, operating-system choice, or prewritten target contract.

## Supported environment

- Linux x86-64 (Ubuntu 22.04/24.04 recommended)
- Python 3.11 or newer, Git, curl and a C compiler
- About 20 GB free space when all third-party sources and K230 tools are fetched

The repository contains project source, schemas, experiment programs, papers and
paper-facing evidence. `third_party/`, `build/`, `output/` and local credentials
are intentionally not versioned; they are recreated from the checked-in manifests.

## Install

```sh
git clone https://github.com/Alex-liuyuan/adam-chip.git
cd adam-chip
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-agent.txt
python tools/run_strict_tests.py
```

The last command must print `ok`. Core self-tests do not require a development
board, vendor image or model service.

Fetch the default pinned source dependencies only when building firmware or
running the simulator integrations:

```sh
sh scripts/fetch_third_party.sh
```

For the K230 platform backend and toolchain, use:

```sh
INCLUDE_PLATFORM_BACKENDS=1 sh scripts/fetch_third_party.sh
```

Large dependencies are downloaded into `third_party/`. Their expected revisions
and artifact hashes are recorded in `third_party.lock.json`; available groups and
licensing boundaries are recorded in `third_party.manifest.json`.

## Model service configuration

The production Agent workflow needs an OpenAI-compatible model endpoint. Keep the
key in the environment, never in Git:

```sh
cp config/llm.example.json config/llm.local.json
export DMXAPI_API_KEY='your-key'
python chip_agents.py model-config
python chip_agents.py model-ping
```

Set `ADAM_LLM_BASE_URL` and `ADAM_LLM_MODEL` to use another compatible provider.
Commands with a `--no-model` option can exercise deterministic engineering paths
without network model calls.

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

The clean-checkout test creates a temporary Git worktree and verifies that the
committed files alone pass the strict gate. Run it after committing local changes.

## AIRTOS experiments and K230 hardware

The four AIRTOS experiment protocols, required packages, exact commands, metrics
and conclusion boundaries are documented in
`docs/paper_orchestra_trilogy/paper3_airtos/experiment_protocol.md`. Archived
results are indexed by
`docs/paper_orchestra_trilogy/paper3_airtos/EXPERIMENT_RESULTS_INDEX.md`.

Host/QEMU experiments require the corresponding Ubuntu cross compilers and QEMU
packages (`gcc-riscv64-linux-gnu`, `gcc-arm-none-eabi`, `qemu-user` and
`qemu-system-arm`). Physical K230 experiments additionally require the named board,
camera, flashed image and stable `/dev/serial/by-id/...` devices described by the
protocol. Hardware scripts do not fabricate a pass when a board or instrument is
absent.

The complete local Paper 3 evidence archive and exact v1 reproduction inputs are
published separately from Git source. Authorized repository users can download and
verify them as follows:

```sh
gh release download paper3-airtos-evidence-20260824 \
  --repo Alex-liuyuan/adam-chip \
  --pattern 'paper3-airtos-evidence-20260824.tar.zst'
echo '1e02f2c829b27851e74a9a23822549c2555a89bd1ae9100bf17f61d52597e0bc  paper3-airtos-evidence-20260824.tar.zst' | sha256sum -c -
tar --zstd -xf paper3-airtos-evidence-20260824.tar.zst
```

After installing the QEMU/cross-compiler packages, rerun the full software suite
with the extracted inputs:

```sh
bash experiments/airtos/run_software_experiments.sh \
  /tmp/airtos-reproduction \
  paper3-airtos-evidence/reproduction-inputs/compiler_corrected/model.aeg \
  paper3-airtos-evidence/reproduction-inputs/target \
  paper3-airtos-evidence/reproduction-inputs/compiler_corrected
```

## Repository map

- `soc_image.py`: production hardware-material intake and run lifecycle
- `agents/`, `engine/`, `socimage/`: orchestration and image-generation core
- `platforms/`, `bsp/`, `boot/`, `products/`: target and product implementations
- `compiler/`: edge-AI compilation and acceleration-plan support
- `experiments/airtos/`: executable AIRTOS experiment sources and runners
- `docs/`: project documentation, three-paper design and experiment evidence
- `tools/`: validation, build, simulation, release and supply-chain tools

See `docs/README.md` for the three-paper index and
`docs/PROJECT_FILE_ORGANIZATION.md` for file ownership and evidence-retention rules.

Implementation phases are ordered by `tools/phase_gate.py`. A phase cannot
begin unless the preceding phase report passed and is bound to the current Git
commit.
