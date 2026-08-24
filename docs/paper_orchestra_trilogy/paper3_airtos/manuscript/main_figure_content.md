# AIRTOS main figure: flat technical OS-to-chip dissection

Create one continuous 16:9 IEEE double-column figure with exactly three
numbered anchors and no full-height panel borders. Use a flat engineering
drawing style with solid fills, section hatching, and uniform black/colored
strokes. Absolutely no gradients, shadows, glow, transparency lighting,
photorealistic rendering, or pseudo-3D perspective.

- Left, 17%: qualified plan + evidence.
- Center, 60%: dominant RT-Smart and K230 technical dissection.
- Right, 23%: completion and bounded closure.

The center must be a real technical cutaway with a top view plus an aligned
orthographic section A--A, not a dark package containing a row of function
boxes. Use space evenly and keep visible labels short.

## 1. Qualified plan + evidence

Use one compact blue cluster centered vertically. A compiler produces a small
CPU/RVV/KPU/DMA DAG with deadline and WCET tags. A signed evidence bundle has
five grouped labels: identities + target, input domain, timing + memory,
coherency, fallback + recovery. Both join into one qualified-plan token entering
the center. Do not expand this into a tall checklist.

## 2. AIRTOS / RT-Smart mechanism and physical K230 dissection

Fill the center using three aligned horizontal layers.

### Layer A: RT-Smart control strip

At the top, use one continuous kernel strip with three mechanisms:

1. A complete joint gate with nine directly labeled checkpoints: Parse, Bind,
   Domain, Evidence, Provider, Memory, Coherence, Schedulability,
   Recoverability.
2. One atomic coupling symbol joining an arena lease bitmap and an all-job
   SimEDF+ timeline under lease-generation and schedule-generation locks. Show
   one green `publish job + lease` latch and one vermilion `publish neither`
   outlet.
3. One session strip (DAG, deadline, lease, state, token) feeding four short
   EDF tracks for CPU, RVV, KPU, and DMA. Each track shows three deadline dots
   and one WCET badge. A single dispatch tag reads
   `device | epoch | cookie | job | segment`.

The four tracks descend as command lines into the K230 top view below. Do not
draw separate device cards.

### Layer B: opened K230 package, top view

Draw a large orthographic top view of a square black K230_LP4 BGA package. One
rectangular portion of the solid black package cover is removed and placed just
above it, exposing a single silicon die. Use no bevel, highlight, shadow, or
gradient.

The exposed die should resemble a technical chip layout: fine rectilinear
interconnect traces, repeated compute-cell textures, SRAM/cache arrays, and a
central interconnect mesh. Place concise leader labels on spatial regions for
dual RISC-V CPU + D-cache, RVV, KPU/NPU, DMA, interrupt logic, and reset logic.
Do not enclose these regions as a row of rounded workflow boxes. Mark a cut line
`A--A` across the package that corresponds to the sectional view below.

Map OS mechanisms directly onto the physical view:

- CPU/RVV/KPU/DMA EDF command lines terminate on the corresponding die regions;
- the dispatch token follows the selected command through the package edge;
- the completion IRQ originates at interrupt logic and returns upward;
- the amber physical-reset line terminates at reset logic;
- buffer-ownership arrows leave the DMA/KPU region toward LPDDR4.

### Layer C: aligned section A--A and LPDDR4

Below the top view, draw a large flat side section aligned to `A--A`. Clearly
separate and directly label these physical layers using solid fills and hatch
patterns:

1. black package cover / mold compound;
2. silicon die;
3. die-attach layer;
4. redistribution/interconnect layer;
5. organic package substrate with multiple copper routing layers;
6. plated through-vias / microvias;
7. bottom solder mask;
8. BGA solder balls.

Next to this section, draw a smaller matching section of the physical
K4F8E304HB-MGCJ LPDDR4 package. Show mold compound, memory die, die attach,
substrate copper layers, vias, solder mask, and BGA balls. Connect K230 and
LPDDR4 using a compact, parallel DDR bundle labeled
`DQ0/1 | CA | differential clock | reset`. Inside the LPDDR4 memory die, show
three non-overlapping solid lease bands: input, output, scratch.

This physical section should occupy the full lower center width. It must look
like a semiconductor-package cross-section from a hardware manual, not like a
software process diagram.

### Runtime mechanism through the dissection

Overlay one green ownership/data route through the top view and section view.
Use four large phase labels instead of many sentences:

- `1–3 CPU handoff`: write lease -> D-cache clean -> barrier;
- `4–5 device access`: DMA/KPU read -> KPU writes output;
- `6 completion IRQ`: interrupt carries active token;
- `7–8 CPU reclaim`: invalidate output -> read fresh output.

Numbers 1 through 8 appear exactly once along the route. The path must visibly
cross K230 die, package routing, DDR bundle, and LPDDR4 lease bands.

## 3. Completion and bounded closure

Fill the right side with two large vertically stacked mechanisms.

At top, one exact-match comparator reads
`device + epoch + cookie + active job + segment`. A green match leads to
`next segment` or `DAG complete -> release lease`. A gray no-match path ends at
`stale / duplicate -> discard; no state change`.

Below, one amber rail reads
`watchdog -> cancel -> physical reset -> epoch + 1 -> reinitialize -> health
check`. Use a professional timer icon, cancel icon, reset icon, epoch tag, tool
icon, and health icon. Put one `finite budget` bracket under the entire rail.
End at green `Healthy` or vermilion `Quarantined`. A blue fallback token curves
back to the complete joint gate.

At the bottom across center and right, show one thin trace ribbon with fields
only: `plan | job | segment | resource | epoch | cookie | event | time |
result`. A dashed gray arrow returns to the compiler and says
`proposal only; cannot certify or bypass admission`.

## Researched flat palette

Use these exact solid colors and no color interpolation:

- qualification `#0072B2`, pale fill `#EAF4FA`;
- admitted execution `#007A5E`, pale fill `#E8F3EE`;
- bounded recovery `#A66F00`, pale fill `#FFF3DC`;
- reject/quarantine `#D55E00`, pale fill `#FBECE7`;
- trace/physical auxiliary `#5F6B73`, pale fill `#F3F5F7`;
- text `#1F2933`; physical package layers use white, `#D9DEE2`, `#AEB7BF`,
  and black hatching only.

Every semantic path also has a unique line treatment and icon: solid blue
qualification, solid/double green execution, amber recovery with reset symbols,
vermilion cross/shield rejection, dashed gray feedback. Use at least 3:1
stroke/background contrast. Keep text horizontal, large, and directly adjacent
to what it labels. No section frames, vertical dividers, board, PCB, ports,
people, decorative server icons, or in-image prose caption.
