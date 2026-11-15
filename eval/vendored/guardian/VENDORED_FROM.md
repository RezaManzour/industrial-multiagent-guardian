# Vendored Source Reference

The files in this directory (`state.py`, `guardrail.py`, `graph.py`, `llm_client.py`)
are vendored (copied, not linked) from Project 1.

- **Source repository:** https://github.com/RezaManzour/industrial-multiagent-guardian
- **Pinned commit hash:** f2364eccfe69d5209d1ef3a01e02d6aa7927ddc4
- **Vendored on:** 2026-09-20

## Why vendored instead of a submodule or pip dependency

This is a deliberate architectural decision: vendoring pins the exact system under
evaluation, making the adversarial evaluation results in this repository fully
reproducible regardless of later changes to Project 1's live repository.

## Updating

If Project 1 changes in a way that should be reflected here, re-copy the relevant
files manually and update the pinned commit hash above — do not silently drift.
