# CanMV-Compatible Generic SoC Reference Product Plan

## 1. Decision

The proposed direction is valid with one correction: the reusable asset is a
portable **source-level reference product**, not one binary image for every
SoC. MicroPython and the CanMV-compatible API remain stable. Board and SoC
differences are implemented behind provider contracts.

For another board using the same SoC, pinmux, clocks, peripheral instances and
board drivers may be the only changes. For another SoC, Agents may also need to
adapt the boot chain, linker and memory map, RT-Thread CPU port, interrupt and
DMA/cache providers, media pipeline and accelerator backend.

The development model may generate an implementation only from confirmed
contracts. It must not guess DDR training, BootROM image formats, NPU command
ABIs, undocumented ISP/VPU protocols or signing keys. Missing facts become
stable blockers.

## 2. Current Gap

The existing production path already provides material-only intake, Hardware
IR, locked source selection, isolated Agent worktrees, promotion, generic
RT-Thread/RT-AI/TVM components and reproducible image packaging.

The K230 source-stack path currently builds `k230-sdk` with
`k230_canmv_v3_defconfig`. The resulting image boots the vendor SDK stack but
does not contain the MicroPython and CanMV product layer. The generic
ProductAgent compiles a `soc_image` binding and host smoke test, but it is not
linked into the source-stack image. Its capability matrix is also hard-coded
to UART, DMA, RVV and AI.

Therefore the current `sdk.img` is an unsigned test candidate, not a CanMV
replacement. The implementation must join the two currently separate paths:

```text
Hardware IR -> locked sources -> platform/providers -> MicroPython + CanMV API
            -> board-native build -> sdk.img -> official comparison -> HIL
```

## 3. Product Architecture

### 3.1 Stable Product Layer

Every generated reference product contains:

- the MicroPython VM and REPL;
- a `machine` compatibility surface;
- CanMV-compatible camera, display, media and AI modules selected by the
  compatibility contract;
- diagnostic and capability-query modules;
- reference applications and per-capability smoke tests;
- the RT-AI runtime and TVM-generated CPU/RVV/NPU artifacts when supported.

Applications call stable Python/C APIs. They never call a board driver,
vendor SDK or accelerator command ABI directly.

### 3.2 Provider Boundary

Use one provider ABI, with one versioned contract per domain:

| Provider | Stable API domains | Typical target implementation |
|---|---|---|
| `core` | ticks, reset, unique ID, memory information | RT-Thread and BSP |
| `machine` | Pin, UART, I2C, SPI, PWM, ADC, RTC, WDT | RT-Thread device drivers |
| `storage` | SD, block device, filesystem | SDHCI/SPI and RT-Thread DFS |
| `network` | Ethernet, Wi-Fi, sockets | lwIP and board network drivers |
| `camera` | sensor probe, frames, format, buffers | sensor + CSI/VICAP/ISP |
| `display` | framebuffer, LCD/DSI/HDMI output | display controller + connector |
| `audio` | input/output, codec, I2S | I2S/DMA + board codec |
| `ai` | model load, tensor, KPU/NPU, AI2D | RT-AI + TVM or vendor backend |

Each API entry has exactly one runtime state:

- `native`: implemented and verified on target hardware;
- `fallback`: behavior is correct through a slower portable implementation;
- `unsupported`: unavailable and raises `NotImplementedError` with a reason.

No provider may report success for an unsupported operation. `fallback` is
allowed only when its behavior and numerical contract match the API contract.

### 3.3 Compatibility Contract

Add `schemas/product_api.schema.json` and a checked-in
`products/canmv_compat/api_contract.json`. Each API record contains:

```json
{
  "module": "camera",
  "symbol": "Camera.snapshot",
  "signature": "snapshot(timeout_ms=None)",
  "required_capabilities": ["camera", "dma"],
  "semantics_test": "tests/camera/test_snapshot.py",
  "reference_required": true,
  "fallback_allowed": false
}
```

The contract is the compatibility target. Public documentation and black-box
tests define behavior. The official image is test input only and never a
component input.

## 4. Source Reuse Policy

SourceDiscoveryAgent must distinguish three source decisions:

| Decision | Permitted use |
|---|---|
| `build` | May enter a produced image after revision, tree and license closure |
| `internal_evaluation` | May build an internal comparison candidate; cannot be released |
| `reference_only` | Metadata and comparison only; cannot compile or contribute files |

The source lock must contain both selected build repositories and all exact
reference repositories. A multi-repository stack records URL, 40-character
revision, tree hash, license decision and parent manifest hash for every
repository.

The existing 20-repository CanMV tree is registered as
`internal_evaluation` or `reference_only` until component-level licensing and
vendor binary provenance are closed. Agents must create clean detached
worktrees from the locked revisions; the existing dirty checkout is never a
build input.

The production compatibility implementation uses build-approved MicroPython,
RT-Thread and provider sources. Unknown-license CanMV code is not copied into
the production implementation.

## 5. Agent Workflow

The controller selects the smallest successful route per capability:

1. Reuse an exact board/SoC implementation with acceptable license and
   passing contract tests.
2. Adapt a same-IP or same-SoC implementation by generating glue, board data
   and provider bindings.
3. Generate a new provider from authoritative Hardware IR and upstream IP
   documentation.
4. If required facts are absent, emit a probe task or blocker.

The model is used at steps 2 and 3. Deterministic tools retain authority over
source locking, path ownership, compilation, ABI checks, hardware write
safety, promotion and release status.

Every generated target file must record:

- Agent task and attempt IDs;
- Hardware IR and source-lock hashes;
- API/provider contract version;
- input source revisions;
- independent verifier result.

ProductAgent does not implement drivers. It selects compatible provider
artifacts, generates bindings and builds the reference product. Verification
Agent receives only contracts and artifacts, not the producer conversation.

## 6. Ordered Implementation

The following stages are sequential. A failed gate blocks the next stage.

### Stage A: Lock the Reference Stack

Change:

- extend `source_policy.schema.json` with `decision` and optional child
  manifest metadata;
- extend `source_discovery_tools.py` so `source.lock.json` records build and
  reference repositories separately;
- import the exact 20-repository CanMV manifest into a generated lock;
- add a clean checkout/export helper using `git worktree` at locked commits;
- add an evaluation-only CanMV build adapter.

Outputs:

- `generated/sources/source.lock.json`;
- `generated/sources/reference.lock.json`;
- `generated/reference_build/manifest.json`;
- evaluation `sdk.img` as an external artifact.

Gate:

- every repository has an exact resolvable revision and tree hash;
- a dirty checkout cannot influence output;
- evaluation sources cannot be selected by a production build;
- the evaluation image contains MicroPython/CanMV markers and is classified
  `unlicensed_evaluation_candidate`.

### Stage B: Define API and Provider Contracts

Change:

- add the product API schema and the CanMV compatibility contract;
- split API coverage into `machine`, storage/network, camera/media, display,
  audio and AI groups;
- add provider ABI headers and capability descriptors;
- derive required API groups from confirmed hardware capabilities and the
  default all-confirmed-capabilities product profile.

Outputs:

- `generated/product/api_contract.json`;
- `generated/product/provider_requirements.json`;
- `generated/product/capability_matrix.json` with per-symbol state and proof.

Gate:

- every required API symbol maps to one provider operation and one test;
- no hard-coded K230 capability list remains in ProductAgent;
- `unsupported` produces `NotImplementedError` and cannot satisfy release
  coverage;
- `fallback` records the implementation and semantic test evidence.

### Stage C: Generate and Verify Providers

Change:

- make DriverAgent publish versioned provider descriptors in addition to
  register-level drivers;
- add board configuration for clocks, resets, pinmux, sensor/codec/display
  topology and connector routing;
- implement generic RT-Thread providers for standard device classes;
- implement K230 camera/media, display, audio and KPU/AI2D providers only from
  locked and permitted sources or confirmed contracts;
- add host fakes for API tests and target probes for hardware tests.

Outputs:

- `generated/providers/<domain>/provider.json`;
- provider libraries or sources;
- compile, ABI and semantic-test reports;
- blockers for unresolved proprietary interfaces.

Gate:

- provider ABI version and Hardware IR hash match ProductAgent inputs;
- register writes trace to authoritative fields;
- host tests cover error paths and lifecycle;
- target-dependent claims remain `unverified` until HIL.

### Stage D: Build the MicroPython/CanMV Product

Change:

- replace the current single `soc_image` module generator with contract-driven
  MicroPython module generation;
- consume the locked RT-Thread MicroPython revision through `selected_source`
  instead of reading the ambient checkout HEAD;
- compile the VM, REPL, bindings, provider libraries, RT-AI and model runtime
  into a target product component;
- preserve `soc_image.capabilities()` as the diagnostic API;
- generate one smoke application for every required API group.

Outputs:

- target MicroPython library/firmware component;
- module and qstr manifests;
- API inventory and import report;
- deterministic product component hash.

Gate:

- real MicroPython VM and all required modules link into the target component;
- module imports and signature tests pass under the target emulator where
  possible;
- no host-only object is linked;
- every exposed symbol is `native`, `fallback` or explicit `unsupported`.

### Stage E: Compose the Board-Native Image

Change:

- make `source_stack_image` depend on the promoted product and provider tasks;
- replace the hard-coded K230 config constant with an Agent-generated config
  derived from the locked source stack and Hardware IR;
- provide the product component to the clean source-stack build through a
  generated integration patch/config, not an overlay on an existing image;
- lock container, toolchain, packages, firmware blobs and download cache by
  digest;
- publish board-native partition and component manifests.

Outputs:

- `release/sdk.img`;
- build/source/container/package locks;
- component ancestry and partition readback reports.

Gate:

- two clean builds are byte-identical, or every unavoidable byte difference
  is identified and normalized before release;
- MicroPython and CanMV-compatible modules are found in readback components;
- no official image or existing built artifact is in ancestry;
- unlocked packages and unknown-license binaries force a non-release class.

### Stage F: Official Compatibility and K230 HIL

Change:

- create a black-box extractor for official partition layout, boot strings,
  Python module inventory and observable API behavior;
- generate API scripts that run unchanged on the official and candidate
  images;
- extend HIL with serial REPL execution, camera frame capture, display/audio
  loopback where fixtures exist, network/storage tests and KPU numerical tests;
- compare boot time, FPS, latency, memory, power, recovery and stability using
  fixed workloads.

Outputs:

- `official_profile.json`;
- `api_compatibility.json`;
- `physical_hil.json`;
- `performance_comparison.json`;
- final `capability_coverage.json`.

Gate:

- flash readback and run-ID boot attribution pass on the physical board;
- every official required capability is `native` or approved `fallback` and
  passes the same behavior test;
- camera, display, audio, storage/network and KPU tests pass on hardware;
- replacement status remains false if any required capability is unsupported,
  unverified or license-blocked;
- performance claims are made only per measured workload.

### Stage G: Second-SoC Generalization

Run the same material-only workflow on a physically different SoC. Adding its
source candidates, capability pack and providers is allowed; modifying
`engine/control.py`, the task schemas or the stable product API for target
special cases is not.

Gate:

- the image builds without K230/CanMV selectors;
- supported APIs run unchanged;
- unavailable hardware is explicit `unsupported`;
- the physical board passes boot, REPL and all enabled capability tests.

## 7. Required Registry Changes

The capability graph should become:

```text
hardware_contract_summary
  -> source_discovery
  -> reference_contract
  -> boot_bsp
  -> contract_drivers
  -> provider_adaptation
  -> rt_ai_os -> rt_ai_runtime -> tvm_ai_compiler
  -> canmv_compatible_product
  -> board_native_image
  -> official_compatibility
  -> hil_verification
  -> release
```

`source_stack_image` in its current independent form is retained only until
Stage E, then replaced by `board_native_image`. Otherwise it can publish an
SDK-only image before product/provider tasks have run, which is the current
root cause of the missing MicroPython/CanMV functionality.

## 8. Release Classes

Use only these release classes:

| Class | Meaning |
|---|---|
| `structural_candidate` | built and unpacked; no physical evidence |
| `unlicensed_evaluation_candidate` | internal source evaluation only |
| `unsigned_hil_candidate` | permitted source closure; ready for board tests |
| `signed_release_candidate` | signed and all release gates pass |

`replacement_gate_pass=true` requires source/license closure, reproducible
ancestry, official API compatibility and complete physical K230 HIL. A marker
scan, successful compilation or emulator run alone can never set it.

## 9. First Executable Increment

Implement Stages A and B before changing image assembly. The first increment
is complete when the engine can:

1. lock the complete CanMV reference stack without admitting it to production;
2. derive a versioned CanMV API contract and provider requirements;
3. produce a per-symbol `native/fallback/unsupported` matrix;
4. reject a production run that lacks required MicroPython/CanMV coverage.

This establishes the contracts needed by DriverAgent and ProductAgent while
preventing another board image that boots but cannot replace the official
developer image.
