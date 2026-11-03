#!/usr/bin/env python3
"""Extract private Ghost Recon 2 USA analysis inputs from an owned disc image.

The .SOZ files contain an expanded-size word followed by a zlib stream.
Never add these outputs, configurations, or generated disassembly to Git.
"""
import argparse
import hashlib
from pathlib import Path
import struct
import subprocess
import zlib

FILES = ("SYSTEM.CNF", "SLUS_211.05", "MP.SOZ", "SP.SOZ", "GVS.DAT", "GSROUTER.DAT")
MAX_EXPANDED = 32 * 1024 * 1024


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("iso", type=Path, help="Path to your Ghost Recon 2 USA disc image")
    parser.add_argument("--output", type=Path, default=Path("work/gr2/disc"))
    args = parser.parse_args()
    if not args.iso.is_file():
        parser.error("Disc image does not exist")
    args.output.mkdir(parents=True, exist_ok=True, mode=0o700)
    subprocess.run(["7z", "x", "-aos", f"-o{args.output.resolve()}",
                    str(args.iso.resolve()), *FILES], check=True)
    for name in FILES:
        path = args.output / name
        if not path.is_file():
            raise SystemExit(f"Missing expected disc file: {name}")
        path.chmod(0o600)
        raw = path.read_bytes()
        print(f"{hashlib.sha256(raw).hexdigest()}  {name}")
        if name.endswith(".SOZ"):
            if len(raw) < 6:
                raise SystemExit(f"Truncated compressed executable: {name}")
            expected, = struct.unpack_from("<I", raw)
            if not 0 < expected <= MAX_EXPANDED:
                raise SystemExit(f"Expanded size exceeds analysis limit: {name}")
            decoder = zlib.decompressobj()
            expanded = decoder.decompress(raw[4:], expected + 1)
            if len(expanded) != expected or not decoder.eof or decoder.unused_data:
                raise SystemExit(f"Compressed executable size/stream mismatch: {name}")
            target = path.with_name(name + ".unpacked")
            with target.open("wb") as output:
                target.chmod(0o600)
                output.write(expanded)
            print(f"{hashlib.sha256(expanded).hexdigest()}  {target.name}")


if __name__ == "__main__":
    main()
