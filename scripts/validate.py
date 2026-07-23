#!/usr/bin/env python3
"""Validate the Thirdpass cargo-vet audit evidence repository."""

from __future__ import annotations

import argparse
import contextlib
import http.server
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import tomllib
from collections.abc import Iterator


CRITERION = "thirdpass-full-crate-archive-reviewed/v1"
EVIDENCE_SCHEMA_VERSION = 4
EVIDENCE_URL_PREFIX = (
    "https://github.com/thirdpass-org/cargo-vet-audits/blob/main/"
)
EXPECTED_SCHEMA_PATH = "schema/evidence-v4.schema.json"
IMPORT_TEST_CRATE = "version_check"
IMPORT_TEST_VERSION = "0.9.5"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate cargo-vet audit metadata and evidence files."
    )
    parser.add_argument(
        "--root",
        type=pathlib.Path,
        default=pathlib.Path(__file__).resolve().parents[1],
        help="Repository root. Defaults to the parent of this script directory.",
    )
    parser.add_argument(
        "--cargo-vet-import",
        action="store_true",
        help="Run a cargo-vet import smoke test using a local HTTP server.",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    audits = load_toml(root / "audits.toml")
    load_json(root / EXPECTED_SCHEMA_PATH)
    audit_count = validate_audits_and_evidence(root, audits)
    print(f"validated {audit_count} cargo-vet audit entries")

    if args.cargo_vet_import:
        validate_cargo_vet_import(root)
        print("validated cargo-vet import with criteria-map")

    return 0


def load_toml(path: pathlib.Path) -> dict:
    try:
        return tomllib.loads(path.read_text())
    except Exception as exc:
        raise ValidationError(f"failed to parse TOML {path}: {exc}") from exc


def load_json(path: pathlib.Path) -> object:
    try:
        return json.loads(path.read_text())
    except Exception as exc:
        raise ValidationError(f"failed to parse JSON {path}: {exc}") from exc


def validate_audits_and_evidence(root: pathlib.Path, audits: dict) -> int:
    criteria = audits.get("criteria", {})
    expect(CRITERION in criteria, f"missing criterion {CRITERION!r}")

    audit_entries = audits.get("audits", {})
    expect(isinstance(audit_entries, dict), "missing audits table")

    seen_versions: set[tuple[str, str]] = set()
    referenced_evidence: set[pathlib.Path] = set()
    audit_count = 0

    for package_name, entries in sorted(audit_entries.items()):
        expect(isinstance(entries, list), f"audits.{package_name} is not a list")
        for entry in entries:
            audit_count += 1
            validate_audit_entry(
                root,
                package_name,
                entry,
                seen_versions,
                referenced_evidence,
            )

    evidence_files = set((root / "evidence").rglob("*.json"))
    extra_evidence = sorted(evidence_files - referenced_evidence)
    missing_evidence = sorted(referenced_evidence - evidence_files)
    expect(
        not missing_evidence,
        "audit notes reference missing evidence files: "
        + ", ".join(path_display(root, path) for path in missing_evidence[:10]),
    )
    expect(
        not extra_evidence,
        "evidence files are not referenced by audits.toml: "
        + ", ".join(path_display(root, path) for path in extra_evidence[:10]),
    )

    return audit_count


def validate_audit_entry(
    root: pathlib.Path,
    package_name: str,
    entry: dict,
    seen_versions: set[tuple[str, str]],
    referenced_evidence: set[pathlib.Path],
) -> None:
    version = required_string(entry, "version", f"audits.{package_name}")
    expect(
        (package_name, version) not in seen_versions,
        f"duplicate audit entry for {package_name}@{version}",
    )
    seen_versions.add((package_name, version))

    expect(
        entry.get("criteria") == CRITERION,
        f"{package_name}@{version} has unexpected criteria",
    )
    expect(entry.get("who") == "Thirdpass", f"{package_name}@{version} has wrong who")
    notes = required_string(entry, "notes", f"audits.{package_name}@{version}")
    expect(
        "Evidence file: evidence/" not in notes,
        f"{package_name}@{version} uses a relative evidence path",
    )

    evidence_url = note_value(notes, "Evidence file")
    expect(
        evidence_url.startswith(EVIDENCE_URL_PREFIX),
        f"{package_name}@{version} evidence URL is not a GitHub URL",
    )
    evidence_relative = pathlib.Path(evidence_url.removeprefix(EVIDENCE_URL_PREFIX))
    expect(
        str(evidence_relative).startswith("evidence/"),
        f"{package_name}@{version} evidence URL does not point under evidence/",
    )
    evidence_path = root / evidence_relative
    referenced_evidence.add(evidence_path)
    evidence = load_json(evidence_path)
    expect(isinstance(evidence, dict), f"{path_display(root, evidence_path)} is not an object")

    validate_evidence_record(root, evidence_path, evidence, package_name, version, notes)


def validate_evidence_record(
    root: pathlib.Path,
    evidence_path: pathlib.Path,
    evidence: dict,
    package_name: str,
    version: str,
    notes: str,
) -> None:
    label = path_display(root, evidence_path)
    expect(
        evidence.get("schema_version") == EVIDENCE_SCHEMA_VERSION,
        f"{label} has unexpected schema_version",
    )
    expect(evidence.get("criterion") == CRITERION, f"{label} has unexpected criterion")

    package = evidence.get("package")
    expect(isinstance(package, dict), f"{label} missing package object")
    expect(package.get("registry_host") == "crates.io", f"{label} is not crates.io")
    expect(package.get("package_name") == package_name, f"{label} package name mismatch")
    expect(package.get("package_version") == version, f"{label} package version mismatch")
    package_hash = required_string(package, "package_hash", label)
    expect(note_value(notes, "Package hash") == package_hash, f"{label} hash mismatch")

    coverage = evidence.get("coverage")
    expect(isinstance(coverage, dict), f"{label} missing coverage object")
    expect(coverage.get("has_authoritative_manifest") is True, f"{label} lacks manifest")
    for metric_name in ("files", "lines", "bytes"):
        metric = coverage.get(metric_name)
        expect(isinstance(metric, dict), f"{label} missing {metric_name} coverage")
        expect(metric.get("pending") == 0, f"{label} has pending {metric_name}")
        expect(metric.get("unreviewed") == 0, f"{label} has unreviewed {metric_name}")
        expect(
            metric.get("reviewed") == metric.get("total"),
            f"{label} has incomplete {metric_name} coverage",
        )

    manifest = evidence.get("manifest")
    expect(isinstance(manifest, dict), f"{label} missing manifest object")
    expect(manifest.get("authoritative") is True, f"{label} manifest is not authoritative")
    manifest_files = manifest.get("files")
    expect(isinstance(manifest_files, list), f"{label} manifest.files is not a list")
    manifest_paths = {required_string(file, "path", label) for file in manifest_files}

    reviewed_files = evidence.get("reviewed_files")
    expect(isinstance(reviewed_files, list), f"{label} reviewed_files is not a list")
    expect(
        set(reviewed_files) == manifest_paths,
        f"{label} reviewed_files do not match manifest files",
    )
    expect(
        coverage["files"].get("total") == len(manifest_paths),
        f"{label} file coverage total does not match manifest",
    )

    reviews = evidence.get("reviews")
    expect(isinstance(reviews, list) and reviews, f"{label} has no reviews")
    for review in reviews:
        review_files = review.get("files")
        expect(isinstance(review_files, list) and review_files, f"{label} review has no files")
        for file_record in review_files:
            file_path = required_string(file_record, "file_path", label)
            expect(file_path in manifest_paths, f"{label} review file outside manifest")


def validate_cargo_vet_import(root: pathlib.Path) -> None:
    expect(shutil.which("cargo") is not None, "cargo is not available")

    with local_http_server(root) as import_url:
        with tempfile.TemporaryDirectory() as temp_dir:
            work = pathlib.Path(temp_dir)
            run(["cargo", "new", "--lib", "vetcheck"], cwd=work)
            project = work / "vetcheck"
            cargo_toml = project / "Cargo.toml"
            cargo_toml.write_text(
                cargo_toml.read_text().replace(
                    "[dependencies]",
                    f'[dependencies]\n{IMPORT_TEST_CRATE} = "={IMPORT_TEST_VERSION}"',
                )
            )
            run(["cargo", "generate-lockfile"], cwd=project)
            run(["cargo", "vet", "init"], cwd=project)
            supply_chain = project / "supply-chain"
            (supply_chain / "audits.toml").write_text(
                f"""# cargo-vet audits file

[criteria."{CRITERION}"]
description = "Every file in the crate archive manifest was reviewed by Thirdpass."

[audits]
"""
            )
            (supply_chain / "config.toml").write_text(
                f"""# cargo-vet config file

[cargo-vet]
version = "0.10"

[imports.thirdpass]
url = "{import_url}/audits.toml"

[imports.thirdpass.criteria-map]
"{CRITERION}" = "{CRITERION}"

[policy.vetcheck]
dependency-criteria = {{ {IMPORT_TEST_CRATE} = "{CRITERION}" }}
"""
            )
            run(["cargo", "vet", "regenerate", "imports"], cwd=project)
            imports_lock = (supply_chain / "imports.lock").read_text()
            expect(
                f"[[audits.thirdpass.audits.{IMPORT_TEST_CRATE}]]" in imports_lock,
                f"cargo-vet did not import {IMPORT_TEST_CRATE}",
            )
            expect(CRITERION in imports_lock, "cargo-vet did not import the criterion")
            run(["cargo", "vet", "check"], cwd=project)


@contextlib.contextmanager
def local_http_server(root: pathlib.Path) -> Iterator[str]:
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, directory=str(root), **kwargs)

        def log_message(self, _format: str, *args: object) -> None:
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    _host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        thread.join()


def note_value(notes: str, key: str) -> str:
    match = re.search(rf"^{re.escape(key)}: (.+)$", notes, flags=re.MULTILINE)
    expect(match is not None, f"missing note field {key!r}")
    return match.group(1)


def required_string(value: object, key: str, label: str) -> str:
    expect(isinstance(value, dict), f"{label} is not an object")
    field = value.get(key)
    expect(isinstance(field, str) and field, f"{label} missing string field {key}")
    return field


def run(command: list[str], cwd: pathlib.Path) -> None:
    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if result.returncode != 0:
        raise ValidationError(
            f"{' '.join(command)} failed in {cwd}:\n{result.stdout.rstrip()}"
        )


def path_display(root: pathlib.Path, path: pathlib.Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


class ValidationError(Exception):
    """Raised when repository validation fails."""


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValidationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
