# File-Focused Review v1

Procedure reference: file-focused-review/v1

Cargo-vet criterion: thirdpass-full-crate-archive-reviewed/v1

Website methodology: https://thirdpass.dev/docs/methodology/cargo-vet#file-focused-review

This procedure records how Thirdpass conducts file-focused review records for
package-relative files. Each accepted review records the selected file paths,
file-level security summaries, file-level confidence, review scope, reviewer
metadata, and agent provenance.

The cargo-vet export composes accepted file-focused review records into a
package-level audit only when those records cover every regular file in the
authoritative crates.io package manifest. Coverage is reported as reviewed
bytes. A crate version is included only when active approved Thirdpass reviews
cover 100% of package bytes with no pending or unreviewed manifest work.

The cargo-vet audit criterion records Thirdpass review coverage. It does not by
itself assert cargo-vet safe-to-run or safe-to-deploy unless an importing project
chooses to map this criterion to one of those meanings.

Each audit entry points to a machine-readable evidence JSON file. The evidence
contains the crate target, package hash, manifest inventory, coverage counts,
review records, reviewed file paths, per-review agent metadata, and per-file
review outcomes.

Agent provenance is recorded per review record. A single crate version may be
covered by multiple accepted reviews, and those reviews may use different agent
names, models, or reasoning efforts. The audit note summarizes the combinations;
the evidence JSON keeps the per-review and per-file detail.

Runtime and token metrics are provenance metadata. They are included when the
review record reported them. Older review records or records produced without
metric reporting may have no runtime or token data; that absence does not reduce
manifest coverage when the review record itself is active and accepted.
