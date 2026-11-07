"""Private state maintenance: tubisoft-admin backup --database ... --output ..."""
import argparse
import json
from .ladder import LadderStore
from pathlib import Path

from .accounts import backup_database, initialize_database


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("init-db", "backup", "ladder"))
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--product")
    parser.add_argument("--mode")
    args = parser.parse_args()
    if args.operation == "init-db":
        initialize_database(args.database)
    elif args.operation=='ladder':
        if not args.product:parser.error('ladder requires --product')
        print(json.dumps(LadderStore(args.database).leaderboard(args.product,mode=args.mode),indent=2))
        return
    else:
        if args.output is None:
            parser.error("backup requires --output")
        backup_database(args.database.resolve(), args.output.resolve())
    print("Operation completed; no account data printed.")


if __name__ == "__main__":
    main()
