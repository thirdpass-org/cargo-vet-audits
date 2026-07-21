# Thirdpass cargo-vet audits

This repository publishes cargo-vet audits backed by Thirdpass review evidence.
Each audit records that Thirdpass has review coverage for a crate archive against
the authoritative crates.io package manifest.

The audit criterion published by this repository is
`thirdpass-full-crate-archive-reviewed/v1`.

This criterion means every file in the crate archive manifest was reviewed by
Thirdpass. It records Thirdpass review evidence. It is not cargo-vet
`safe-to-run` or `safe-to-deploy` unless an importing project chooses to map it
to one of those meanings.

## Contents

- `audits.toml` contains the cargo-vet audit entries.
- `evidence/` contains machine-readable evidence for each crate version.
- `procedures/file-focused-review-v1.md` explains the review procedure used to
  produce the underlying review records.

Each audit note links to its evidence JSON file. Evidence includes the crate
target, package hash, manifest inventory, coverage counts, review records,
reviewed file paths, agent model and effort, and runtime/token metrics when the
review records reported them.

## Using this repository

Add this repository as a cargo-vet import source, then decide in your own
project policy how to treat the
`thirdpass-full-crate-archive-reviewed/v1` criterion.

The audits are generated from Thirdpass coverage data. Manual edits to generated
files may be overwritten by the next export.
