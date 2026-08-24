#!/usr/bin/env python3
"""Generate AIRTOS statistical figures from the frozen experimental log."""

from __future__ import annotations

import json
import struct
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "figures"
TARGETS = (
    "fig_admission_atomicity_analysis",
    "fig_memory_dma_analysis",
    "fig_recovery_governance_analysis",
    "fig_timing_contract_analysis",
)

BLUE = "#3B6F9B"
GREEN = "#4F8064"
ORANGE = "#B86B32"
RED = "#A9443A"
PURPLE = "#725C8E"
GRAY = "#6A7075"
DARK = "#263238"

plt.rcParams.update(
    {
        "font.family": "sans-serif",
        "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans"],
        "font.size": 7.2,
        "axes.titlesize": 7.2,
        "axes.titleweight": "bold",
        "axes.labelsize": 7.4,
        "axes.linewidth": 0.65,
        "legend.fontsize": 6.4,
        "xtick.labelsize": 6.4,
        "ytick.labelsize": 6.4,
        "figure.dpi": 300,
        "savefig.dpi": 300,
        "axes.axisbelow": True,
    }
)


def finish(fig: plt.Figure, name: str) -> None:
    fig.savefig(OUT / f"{name}.png", dpi=300, facecolor="white")
    plt.close(fig)


def clean_axes(ax: plt.Axes, axis: str = "y") -> None:
    ax.grid(axis=axis, color="#D7DADD", linewidth=0.55, linestyle="--", alpha=0.75)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)


def admission_atomicity_analysis() -> None:
    methods = ["None", "Candidate", "FIFO", "Fixed pri.", "All-job"]
    false_accept = np.array([5822, 3932, 27, 29, 0])
    false_reject = np.array([0, 0, 355, 380, 0])
    accepted = 112_091
    rejected = 287_909

    fig, (ax0, ax1) = plt.subplots(1, 2, figsize=(4.0, 3.0), dpi=300)
    x = np.arange(len(methods))
    width = 0.36
    b0 = ax0.bar(x - width / 2, false_accept, width, color=ORANGE, hatch="////", label="False accept")
    b1 = ax0.bar(x + width / 2, false_reject, width, color=BLUE, hatch="....", label="False reject")
    ax0.set_title("(a) Admission errors", loc="left")
    ax0.set_ylabel("Scenarios")
    ax0.set_xticks(x, methods)
    ax0.tick_params(axis="x", labelrotation=28, labelsize=5.6)
    ax0.set_ylim(0, 6500)
    ax0.legend(loc="upper right", frameon=False)
    clean_axes(ax0)
    for bars in (b0, b1):
        for bar in bars:
            value = int(bar.get_height())
            if value:
                ax0.text(bar.get_x() + bar.get_width() / 2, value + 95, f"{value:,}", ha="center", va="bottom", fontsize=5.3, rotation=90 if value < 500 else 0)
    ax0.text(x[-1], 180, "0 / 0", ha="center", va="bottom", fontsize=5.7, color=GREEN, weight="bold")

    ax1.barh([0], [accepted], color=GREEN, height=0.42, label="Accepted")
    ax1.barh([0], [rejected], left=[accepted], color=GRAY, height=0.42, label="Safely rejected")
    ax1.set_title("(b) Concurrent commit", loc="left")
    ax1.set_xlabel("Transactions")
    ax1.set_yticks([])
    ax1.set_xlim(0, 420_000)
    ax1.legend(loc="upper center", ncol=1, frameon=False, fontsize=5.6)
    clean_axes(ax1, "x")
    ax1.text(accepted / 2, 0, f"{accepted:,}\n28.0%", ha="center", va="center", fontsize=6.0, color="white", weight="bold")
    ax1.text(accepted + rejected / 2, 0, f"{rejected:,}\n72.0%", ha="center", va="center", fontsize=6.0, color="white", weight="bold")
    ax1.set_ylim(-0.65, 0.65)
    ax1.text(200_000, -0.48, "0 active overlaps  |  0 partial commits", ha="center", fontsize=5.5, color=DARK, weight="bold")

    fig.subplots_adjust(left=0.12, right=0.98, bottom=0.22, top=0.92, wspace=0.34)
    finish(fig, "fig_admission_atomicity_analysis")


def memory_dma_analysis() -> None:
    sizes = np.array([64, 256, 4096, 65536])
    latency = np.array([29.949, 34.490, 86.502, 713.355])
    successful = 948_950
    rejected = 1_000_000 - successful

    fig, (ax0, ax1) = plt.subplots(1, 2, figsize=(4.0, 3.0), dpi=300)
    ax0.barh([0], [successful], color=GREEN, height=0.42, label="Lease committed")
    ax0.barh([0], [rejected], left=[successful], color=GRAY, height=0.42, label="Safely rejected")
    ax0.set_title("(a) Lease outcomes", loc="left")
    ax0.set_xlabel("Allocation attempts")
    ax0.set_yticks([])
    ax0.set_xlim(0, 1_000_000)
    ax0.legend(loc="upper center", ncol=1, frameon=False, fontsize=5.3)
    clean_axes(ax0, "x")
    ax0.text(successful / 2, 0, f"{successful:,}\n94.9%", ha="center", va="center", fontsize=6.0, color="white", weight="bold")
    ax0.annotate(f"{rejected:,}\n5.1%", xy=(successful + rejected / 2, 0), xytext=(-4, 25), textcoords="offset points", ha="center", fontsize=5.6, arrowprops={"arrowstyle": "->", "color": GRAY, "linewidth": 0.6})
    ax0.set_ylim(-0.65, 0.65)
    ax0.text(500_000, -0.48, "0 overlap  |  0 corruption  |  0 rollback failure", ha="center", fontsize=5.0, color=DARK, weight="bold")

    ax1.plot(sizes, latency, color=BLUE, marker="o", markersize=4, linewidth=1.5)
    ax1.set_xscale("log", base=2)
    ax1.set_yscale("log")
    ax1.set_title("(b) K230 DMA latency", loc="left")
    ax1.set_xlabel("Transfer size (bytes)")
    ax1.set_ylabel("Mean time (us)")
    ax1.set_xticks(sizes, ["64", "256", "4K", "64K"])
    ax1.set_xlim(45, 100_000)
    ax1.set_ylim(20, 1100)
    clean_axes(ax1, "both")
    for size, value in zip(sizes, latency):
        ax1.annotate(f"{value:.3f}", (size, value), xytext=(0, 6), textcoords="offset points", ha="center", fontsize=5.2)
    ax1.text(
        0.03,
        0.96,
        "1,000,000 transfers: 0 mismatch\n"
        "Omit clean: 400/400 detected\n"
        "Omit invalidate: 400/400 detected",
        transform=ax1.transAxes,
        va="top",
        fontsize=4.8,
        color=DARK,
        bbox={"facecolor": "white", "edgecolor": "#C7CBCD", "pad": 2.5},
    )

    fig.subplots_adjust(left=0.13, right=0.98, bottom=0.20, top=0.92, wspace=0.36)
    finish(fig, "fig_memory_dma_analysis")


def recovery_governance_analysis() -> None:
    labels = [
        "Stale-event rejection",
        "Recovery state machine",
        "Budget / quarantine",
        "Fallback re-admission",
        "Base trace classification",
        "Robust trace classification",
        "GSDMA lifecycle",
        "Short continuous HIL",
    ]
    counts = [700_000, 1_500, 4_800, 1_200, 800, 2_400, 300, 6_685_424]
    colors = [BLUE, ORANGE, ORANGE, PURPLE, GREEN, GREEN, GRAY, BLUE]

    fig, ax = plt.subplots(figsize=(4.0, 3.0), dpi=300)
    y = np.arange(len(labels))
    ax.barh(y, counts, color=colors, edgecolor="white", linewidth=0.5, height=0.58)
    ax.set_yticks(y, labels)
    ax.invert_yaxis()
    ax.set_xscale("log")
    ax.set_xlim(180, 100_000_000)
    ax.set_xlabel("Events or episodes (log scale)")
    clean_axes(ax, "x")
    for i, count in enumerate(counts):
        if count >= 500_000:
            ax.text(count / 1.15, i, f"{count:,}  |  violations: 0", ha="right", va="center", fontsize=5.0, color="white", weight="bold")
        else:
            ax.text(count * 1.08, i, f"{count:,}  |  violations: 0", va="center", fontsize=5.2, color=DARK)
    ax.text(0.99, 0.015, "Trace: macro-F1 = 1.0  |  HIL: 1,440 s", transform=ax.transAxes, ha="right", fontsize=5.2, color=GRAY)
    fig.subplots_adjust(left=0.40, right=0.96, bottom=0.17, top=0.97)
    finish(fig, "fig_recovery_governance_analysis")


def timing_contract_analysis() -> None:
    paths = ["RVV primary", "CPU fallback"]
    p99 = [1.592, 1.592]
    maxima = [19.778, 19.926]
    wcet = [4.0, 10.0]
    x = np.arange(2)
    width = 0.23

    ratio_labels = ["0.50", "0.80", "1.00", "1.05", "1.20"]
    ratio_x = np.arange(len(ratio_labels))
    misses = np.array([0, 0, 0, 446, 1145])
    miss_rate = misses / 4178 * 100
    fig, (ax0, ax) = plt.subplots(1, 2, figsize=(4.0, 3.0), dpi=300)
    ax0.plot(ratio_x, miss_rate, color=RED, marker="o", markersize=4, linewidth=1.5)
    ax0.axvline(2, color=GRAY, linestyle="--", linewidth=0.9)
    ax0.fill_between(ratio_x, 0, miss_rate, color=RED, alpha=0.10)
    ax0.set_title("(a) WCET sensitivity", loc="left")
    ax0.set_xlabel("Actual / registered WCET")
    ax0.set_ylabel("Deadline misses (%)")
    ax0.set_xticks(ratio_x, ratio_labels)
    ax0.set_ylim(0, 31)
    clean_axes(ax0)
    for pos, rate, count in zip(ratio_x, miss_rate, misses):
        ax0.annotate(f"{count:,}", (pos, rate), xytext=(0, 6), textcoords="offset points", ha="center", fontsize=5.4)
    ax0.text(0.04, 0.94, "4,178 scenarios / ratio", transform=ax0.transAxes, fontsize=5.0, color=GRAY, va="top")

    bars_p99 = ax.bar(x - width, p99, width, color=BLUE, label="Batch p99")
    bars_max = ax.bar(x, maxima, width, color=ORANGE, hatch="////", label="Observed maximum")
    bars_wcet = ax.bar(x + width, wcet, width, color=GRAY, label="Registered WCET")
    ax.set_xticks(x, paths)
    ax.set_ylabel("Execution time (us)")
    ax.set_ylim(0, 24)
    ax.set_title("(b) Board timing audit", loc="left")
    ax.legend(loc="center", bbox_to_anchor=(0.5, 0.50), ncol=1, frameon=False, fontsize=4.7)
    clean_axes(ax)
    for bars, values in ((bars_p99, p99), (bars_max, maxima), (bars_wcet, wcet)):
        for bar, value in zip(bars, values):
            ax.text(bar.get_x() + bar.get_width() / 2, value + 0.35, f"{value:g}", ha="center", va="bottom", fontsize=5.5)
    for i, (maximum, limit) in enumerate(zip(maxima, wcet)):
        ax.annotate(
            f"FAIL\n+{maximum - limit:.3f} us",
            xy=(i, maximum),
            xytext=(i, 22.2),
            ha="center",
            fontsize=5.3,
            color=RED,
            weight="bold",
            arrowprops={"arrowstyle": "->", "color": RED, "linewidth": 0.7},
        )
    fig.subplots_adjust(left=0.12, right=0.98, bottom=0.20, top=0.93, wspace=0.34)
    finish(fig, "fig_timing_contract_analysis")


def png_info(path: Path) -> tuple[int, int, tuple[float, float] | None]:
    with path.open("rb") as handle:
        assert handle.read(8) == b"\x89PNG\r\n\x1a\n"
        width = height = None
        ppm = None
        while True:
            raw_len = handle.read(4)
            if not raw_len:
                break
            length = struct.unpack(">I", raw_len)[0]
            kind = handle.read(4)
            data = handle.read(length)
            handle.read(4)
            if kind == b"IHDR":
                width, height = struct.unpack(">II", data[:8])
            elif kind == b"pHYs" and data[8] == 1:
                ppm = struct.unpack(">II", data[:8])
            elif kind == b"IEND":
                break
    dpi = tuple(round(value * 0.0254, 2) for value in ppm) if ppm else None
    return width, height, dpi


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    admission_atomicity_analysis()
    memory_dma_analysis()
    recovery_governance_analysis()
    timing_contract_analysis()
    captions = {
        "fig_admission_atomicity_analysis": "Admission accuracy and transaction atomicity. The complete all-job SimEDF+ check eliminates oracle-relative false accepts and false rejects in the frozen ablation, while 400,000 concurrent transactions publish neither overlapping leases nor partial jobs.",
        "fig_memory_dma_analysis": "Memory and physical data-path analysis. The allocator safely commits 948,950 of one million lease attempts without a tracked isolation failure; K230 complete-path latency is shown for 250,000 transfers per size, with zero byte mismatch and full detection of omitted ownership operations.",
        "fig_recovery_governance_analysis": "Failure-governance evidence by endpoint. Log-scaled bars retain the distinct denominators for stale-event rejection, bounded recovery, quarantine, fallback, trace, device lifecycle, and short HIL rather than combining them into a common estimator.",
        "fig_timing_contract_analysis": "Timing-evidence analysis. Software-model misses emerge only after execution exceeds registered WCET, and the K230 audit rejects both plan bounds because measured maxima exceed them despite favorable batch p99 values.",
    }
    (OUT / "captions.json").write_text(json.dumps(captions, indent=2) + "\n", encoding="utf-8")
    assert set(captions) == set(TARGETS)
    for name in TARGETS:
        width, height, dpi = png_info(OUT / f"{name}.png")
        assert (width, height) == (1200, 900)
        assert dpi and all(abs(value - 300) < 0.1 for value in dpi)
        print(f"{name}: {width}x{height}, dpi={dpi}")


if __name__ == "__main__":
    main()
