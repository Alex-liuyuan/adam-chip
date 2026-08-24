# Submission and Formatting Guidelines

## Target Format

- IEEE Transactions journal manuscript using the user-supplied `IEEEtran.cls`.
- LaTeX class: `\documentclass[lettersize,journal]{IEEEtran}`.
- Two-column journal layout, IEEE numeric citations, `IEEEkeywords`, and anonymous authors for review.
- The supplied paper, *Reliable Real-Time Operating System for IoT Devices*, is a structural and prose-density reference only. Its text and figures must not be copied.
- Preferred structure: Abstract; Introduction; Background and Related Work; System Model and Problem Formulation; AIRTOS Design; Implementation; Experimental Methodology; Evaluation; Discussion; Conclusion.
- Produce exactly 15 pages in IEEE journal style, including references, with all claims supported by the provided project artifacts.

## Figure Rules

- Exactly five figures, all newly generated from AIRTOS project materials: one full-width PaperBanana architecture figure and four statistical analysis figures derived from the experimental log.
- Do not copy, trace, modify, or include any legacy image under `paper3_airtos/figures/`.
- Render each figure as a separate 300 DPI PNG with print-safe colors and legible single-column labels.
- Figures must appear before the Conclusion and must have evidence-bound captions without a manual `Figure N:` prefix.

## Evidence and Anonymity Rules

- Use only numbers recorded in `experimental_log.md`.
- Preserve all negative findings, especially WCET violations and the failed strict overhead criterion.
- Do not claim hard real time, general NPU performance, physical late-IRQ behavior, hard-reset recovery, power results, 24-hour stability, or board-to-board generalization.
- Identify the physical scope as one CanMV-K230-LP4 V3.0 board and the workload as a fixed Add+ReLU plan.
- Keep author names, affiliations, emails, acknowledgments, repository identities, and machine-user paths out of the manuscript.

## Literature Cutoff

- No submission deadline was supplied. Following the PaperOrchestra default, use `2026-07-05` as the literature cutoff, one month before manuscript preparation.
- Official specifications and local project documentation may be used as implementation sources, but later work must not be framed as a prior baseline.
