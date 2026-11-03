#!/usr/bin/env python3
"""Audit the publication candidate, reporting locations without exposing values.

Use --git to inspect every staged/tracked file in a clean publication checkout.
This is a bounded secret/privacy check, not a guarantee against every secret format.
"""
from __future__ import annotations

import argparse
import ipaddress
from pathlib import Path
import re
import subprocess

PUBLIC_DIRS = ("src", "tests", "tools", "ghidra", "deploy", "docs", ".github")
PUBLIC_FILES = ("README.md", "THIRD_PARTY_NOTICES.md", "LICENSE", "pyproject.toml", "compose.yaml",
                "Dockerfile", ".dockerignore", ".gitignore", ".env.example")
PATTERNS = {
    "private-key material": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "GitHub token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b"),
    "cloud access key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "personal home path": re.compile(r"/(?:home|Users)/[A-Za-z0-9_.-]+/"),
    "email address": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
}
DOCUMENTATION_NETWORKS = tuple(ipaddress.IPv4Network(value) for value in
                             ("0.0.0.0/32", "127.0.0.0/8", "192.0.2.0/24", "198.51.100.0/24",
                              "203.0.113.0/24", "255.255.255.255/32"))
FORBIDDEN_SUFFIXES = (".pem", ".key", ".pfx", ".p12", ".iso", ".ovl", ".umd", ".ps2", ".pcap", ".pcapng", ".log", ".raw", ".pyc", ".bin")


def candidate_files(root: Path, *, git: bool = False) -> list[Path]:
    if git:
        output = subprocess.check_output(["git", "ls-files", "-z", "--cached"], cwd=root)
        return [root / name.decode() for name in output.split(b"\0") if name]
    paths = [root / name for name in PUBLIC_FILES if (root / name).exists()]
    for directory in PUBLIC_DIRS:
        paths.extend(path for path in (root / directory).rglob("*")
                     if path.is_file() and "__pycache__" not in path.parts and not any(p.endswith(".egg-info") for p in path.parts))
    return sorted(paths)


def inspect(path: Path) -> list[tuple[int, str]]:
    findings = []
    lowered = path.name.lower()
    if (lowered.endswith(FORBIDDEN_SUFFIXES) or ".sqlite" in lowered or lowered.endswith(".db")
            or lowered in ("id_rsa", "id_ed25519") or lowered.startswith(".env") and lowered != ".env.example"):
        return [(0, "private/runtime artifact filename")]
    if path.is_symlink():
        return [(0, "symlink requires separate review")]
    try:
        content = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return [(0, "unreadable or non-text artifact")]
    for number, line in enumerate(content.splitlines(), 1):
        for label, pattern in PATTERNS.items():
            if pattern.search(line):
                findings.append((number, label))
        for match in re.finditer(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", line):
            try:
                address = ipaddress.IPv4Address(match.group())
            except ValueError:
                continue
            if not any(address in network for network in DOCUMENTATION_NETWORKS):
                findings.append((number, "non-example network address"))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--git", action="store_true")
    args = parser.parse_args()
    paths = candidate_files(args.root, git=args.git)
    failures = 0
    for path in paths:
        for line, label in inspect(path):
            print(f"{path.relative_to(args.root)}:{line}: {label}")
            failures += 1
    print(f"Audited {len(paths)} publication files; {failures} findings. No matched values printed.")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
