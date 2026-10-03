"""Register the six user-authorized references without importing candidate facts."""

import argparse
from pathlib import Path

from career.db import SessionLocal
from career.references import import_directory, listing

parser = argparse.ArgumentParser()
parser.add_argument("directory", type=Path)
parser.add_argument("--user", required=True)
args = parser.parse_args()
with SessionLocal.begin() as db:
    import_directory(db, args.user, args.directory)
    print(f"추가 자료 등록: {len([r for r in listing(db, args.user) if r['active']])} files")
