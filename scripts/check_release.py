#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 OpenJustSayAI
"""Check built Ducky distributions for required notices and excluded media."""

import tarfile
import zipfile
from pathlib import Path, PurePosixPath


def check_names(names):
    paths = [PurePosixPath(name) for name in names]
    for path in paths:
        if path.suffix.lower() in {".mp3", ".wav", ".zip", ".pem", ".key"}:
            raise ValueError(f"Private media/secret format in distribution: {path}")
        if path.name in {"manifest.json", "config.local.json", ".env"}:
            raise ValueError(f"Private runtime data in distribution: {path}")
    for notice in ("Ducky-MIT.txt", "LinguaLive-MIT.txt", "Reachy-Mini-Apache-2.0.txt"):
        if not any(path.name == notice for path in paths):
            raise ValueError(f"Missing license: {notice}")
    if not any(path.name == "LICENSE" for path in paths):
        raise ValueError("Missing root MIT license")
    if not any(path.parts[-2:] == ("ducky_reachy_mini", "main.py") for path in paths):
        raise ValueError("Missing Ducky app entry point")


def main():
    distributions = sorted(Path("dist").glob("*.whl")) + sorted(Path("dist").glob("*.tar.gz"))
    if not any(path.suffix == ".whl" for path in distributions):
        raise SystemExit("Build a wheel first")
    if not any(path.name.endswith(".tar.gz") for path in distributions):
        raise SystemExit("Build an sdist first")
    for path in distributions:
        if path.suffix == ".whl":
            with zipfile.ZipFile(path) as archive:
                check_names(archive.namelist())
        else:
            with tarfile.open(path, "r:gz") as archive:
                check_names(archive.getnames())
        print(f"Checked {path}: notices present, excluded formats absent")


if __name__ == "__main__":
    main()
