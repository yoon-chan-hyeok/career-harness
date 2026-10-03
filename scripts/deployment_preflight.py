"""No network or writes by default. Opt-in probes use synthetic data, never private documents."""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from career.authentication import authentication_configuration, configured_verifier  # noqa: E402
from career.production import readiness, validate_runtime_settings  # noqa: E402
from pydantic import BaseModel  # noqa: E402


class ProbeResponse(BaseModel):
    ok: bool


def run(args: argparse.Namespace) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    try:
        validate_runtime_settings()
        checks["configuration"] = {"status": "ok"}
    except Exception as error:
        # Only validation messages (setting names) are printed, never unexpected error text.
        checks["configuration"] = {"status": "failed", "error_type": type(error).__name__}
    if args.check_database:
        try:
            from career.db import engine

            status, report = readiness(engine)
            checks["database_readiness"] = {"status": "ok" if status == 200 else "failed", "report": report}
        except Exception as error:
            checks["database_readiness"] = {"status": "failed", "error_type": type(error).__name__}
    if args.check_public_keys:
        try:
            config = authentication_configuration()
            if config.mode != "supabase":
                raise ValueError("Public keys apply only to Supabase")
            verifier = configured_verifier(config)
            with verifier._lock:
                verifier._refresh()
            checks["supabase_public_keys"] = {"status": "ok", "live_verified": True}
        except Exception as error:
            checks["supabase_public_keys"] = {"status": "failed", "error_type": type(error).__name__}
    if getattr(args, "live_ai", False):
        try:
            from career.providers import configured_provider

            provider = configured_provider()
            if provider is None:
                raise ValueError("No configured AI provider")
            response = provider.structured(
                "deployment_probe", {"synthetic": "Return ok=true."}, ProbeResponse
            )
            checks["selected_ai"] = {
                "status": "ok" if response.ok else "failed", "live_verified": True
            }
        except Exception as error:
            checks["selected_ai"] = {"status": "failed", "error_type": type(error).__name__}
    if args.live_openai:
        try:
            from career.providers import OpenAIProvider

            provider = OpenAIProvider()
            response = provider.structured(
                "deployment_probe", {"synthetic": "Return ok=true."}, ProbeResponse
            )
            checks["openai"] = {"status": "ok" if response.ok else "failed", "live_verified": True}
        except Exception as error:
            checks["openai"] = {"status": "failed", "error_type": type(error).__name__}
    if args.live_jev:
        try:
            from career.decisions import JevDecisionProvider

            response = JevDecisionProvider().choose(
                "direct_answer",
                {"question": "What color is the sky?", "answer": "Blue.", "synthetic": True},
                ["yes", "no"],
            )
            checks["jev"] = {
                "status": "ok" if response.choice in {"yes", "no"} else "failed",
                "live_verified": True,
            }
        except Exception as error:
            checks["jev"] = {"status": "failed", "error_type": type(error).__name__}
    return {
        "status": "ok" if all(c["status"] == "ok" for c in checks.values()) else "not_ready",
        "checks": checks,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-database", action="store_true", help="Read-only DB/migration/privacy checks")
    parser.add_argument("--check-public-keys", action="store_true", help="Fetch only public Supabase JWKS")
    parser.add_argument(
        "--live-ai", action="store_true",
        help="Opt-in synthetic API call to the selected provider; consumes quota and may incur account charges",
    )
    parser.add_argument(
        "--live-openai", action="store_true", help="Opt-in paid API call with synthetic input"
    )
    parser.add_argument(
        "--live-jev", action="store_true", help="Opt-in paid shadow API call with synthetic input"
    )
    result = run(parser.parse_args())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] == "ok" else 1)


if __name__ == "__main__":
    main()
