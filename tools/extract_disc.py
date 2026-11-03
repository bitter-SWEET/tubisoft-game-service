#!/usr/bin/env python3
"""Extract only the XIII USA files needed for network analysis."""
import argparse
import hashlib
from pathlib import Path
import subprocess

FILES = ("SYSTEM.CNF", "PSX2GAME.INI", "SLUS_206.77", "OVL/NET_M.OVL", "OVL/DNAS_M.OVL")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("iso", type=Path, help="Path to your XIII USA disc image")
    parser.add_argument("--output", type=Path, default=Path("work/disc"))
    args = parser.parse_args()
    if not args.iso.is_file():
        parser.error(f"Disc image does not exist: {args.iso}")
    args.output.mkdir(parents=True, exist_ok=True)
    subprocess.run(["7z", "x", "-aos", f"-o{args.output.resolve()}", str(args.iso.resolve()), *FILES], check=True)
    for name in FILES:
        path = args.output / name
        if not path.is_file():
            raise SystemExit(f"Missing expected disc file: {name}")
        print(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {name}")


if __name__ == "__main__":
    main()
