# Verified usage demonstration

This directory records the successful clean-clone demonstration executed on
2026-08-24 UTC. The tested source commit was `f6ece84`; later documentation-only
commits add these records and screenshots.

The demonstration used the private GitHub repository and its published dependency
and Paper 3 evidence releases. No mock inputs were used. The complete AIRTOS runner
finished with exit code 0 and generated `RUN_PASS`, 161 checksum records, one
RISC-V RT-Thread system pass and four ARM system-model passes.

- `logs/`: searchable command and result records used to render the screenshots.
- `screenshots/`: terminal-style PNG renderings embedded in the root `README.md`.

The demonstration covers the complete board-free workflow. Model-service execution
requires the user's own API credential, and physical K230 experiments require the
board and instruments described by the Paper 3 protocol; credentials are never
captured in screenshots.
