"""Local curator tools. Does not connect to a database, model, or publication service."""

import argparse
import json
import os
from pathlib import Path

from career.question_contracts import QuestionContract
from career.question_guide_import import ReleaseLedger, import_file, load_catalog, read_json
from career.question_guide_search import retrieve


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    intake = commands.add_parser("import")
    intake.add_argument("source", type=Path)
    intake.add_argument("--catalog", type=Path, required=True)
    intake.add_argument("--legacy-mini-kit", action="store_true")
    for name in ("inventory", "search"):
        sub = commands.add_parser(name)
        sub.add_argument("--catalog", type=Path, required=True)
        if name == "search":
            sub.add_argument("question", type=Path)
            sub.add_argument("--enable-guide-preview", action="store_true", help="Explicit opt-in for offline I01 retrieval")
            sub.add_argument("--releases", type=Path,
                             help="Separate curator-reviewed release ledger; never a raw guide's approval fields")
    args = parser.parse_args()
    if args.command == "import":
        path = import_file(args.source, args.catalog, legacy=args.legacy_mini_kit)
        print(json.dumps({"imported_file": str(path), "rights_status": "REVIEW_REQUIRED"}))
    else:
        rows = load_catalog(args.catalog)
        if args.command == "inventory":
            result = {"unique_guides": len(rows), "guides": [
                {"guide_id": row.guide.guide_id, "version": row.guide.version, "hash": row.content_hash,
                 "rights": row.rights_status, "source_verified_live": row.source_verified_live} for row in rows]}
        else:
            releases = ReleaseLedger.model_validate(read_json(args.releases)).reviews if args.releases else ()
            result = retrieve(QuestionContract.model_validate(read_json(args.question)), rows, releases=releases,
                              enabled=args.enable_guide_preview or os.getenv("QUESTION_GUIDE_RAG_ENABLED", "0") == "1")
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
