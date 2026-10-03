import json
import subprocess
from pathlib import Path

VERCEL_PRIVATE_EXCLUSIONS = [
    "**/.env*", "**/*.env", "**/*.env.*", "**/.local-settings.json", "**/.provider-settings.json",
    "**/.provider-settings.json.*.tmp", "**/private_input/**", "**/work/**",
    "**/*.db*", "**/*.sqlite*", "**/*.dump", "**/*.backup", "**/*.key", "**/*.pem",
    "**/__pycache__/**",
]


def check_vercel_exclusions(project: Path) -> None:
    """Both deployment roots must end with rules that cannot be silently undone."""
    for relative in (".vercelignore", "frontend/.vercelignore"):
        try:
            rules = [
                line.strip() for line in (project / relative).read_text(encoding="utf-8-sig").splitlines()
                if line.strip() and not line.startswith("#")
            ]
        except OSError:
            raise SystemExit("Vercel privacy exclusions could not be checked") from None
        if rules[-len(VERCEL_PRIVATE_EXCLUSIONS):] != VERCEL_PRIVATE_EXCLUSIONS:
            raise SystemExit("Vercel deployment exclusions must end with private file protection")
        if relative == ".vercelignore" and (
            not rules or rules[0] != "/*" or "!/app.py" not in rules or "!/backend/career/*.py" not in rules
        ):
            raise SystemExit("Vercel backend must use a runtime source allowlist")


def check_docker_provider_exclusions(project: Path) -> None:
    """Require final Docker exclusions, including credentials that are not Git tracked.

    Docker applies the last matching rule. Keeping these exact root patterns last
    makes the guarantee independent of earlier wildcards or negated rules, without
    trying to reproduce the complete Docker ignore matcher in this privacy check.
    """
    expected = [
        "**/.env*", "**/*.env", "**/*.env.*", "**/.local-settings.json",
        "**/.provider-settings.json", "**/.provider-settings.json.*.tmp",
        "**/private_input/**", "**/work/**", "**/source_specs/**",
        "**/*.db*", "**/*.sqlite*", "**/*.dump", "**/*.backup", "**/*.key", "**/*.pem",
        "**/__pycache__/**", ".provider-settings.json", ".provider-settings.json.*.tmp",
    ]
    try:
        rules = [
            line.strip()
            for line in (project / ".dockerignore").read_text(encoding="utf-8-sig").splitlines()
            if line.strip() and not line.startswith("#")
        ]
    except OSError:
        raise SystemExit("Docker privacy exclusions could not be checked") from None
    if rules[-len(expected):] != expected:
        raise SystemExit("Docker build context must end with private provider exclusions")

def private_path(relative: str) -> bool:
    parts = relative.replace("\\", "/").lower().split("/")
    name = parts[-1]
    private_input = "private_input" in parts and relative not in {
        "private_input/.gitkeep", "private_input/README.md",
    } and name != ".gitkeep"
    return (
        private_input
        or "work" in parts
        or name in {".local-settings.json", ".provider-settings.json"}
        or (name.startswith(".provider-settings.json.") and name.endswith(".tmp"))
        or (name.startswith(".env") and name != ".env.example")
        or (name.endswith(".env") and not name.endswith(".env.example"))
        or (".env." in name and not name.endswith(".env.example"))
        or ".db" in Path(name).suffixes
        or any(suffix.startswith(".db-") or suffix.startswith(".sqlite") for suffix in Path(name).suffixes)
        or name.endswith((".dump", ".backup", ".key", ".pem"))
        or (len(parts) == 1 and name.startswith("ui-") and name.endswith(".png"))
        or ("source_specs" in parts and name.endswith("canonical.txt"))
    )


def check_source_candidates(project: Path) -> None:
    # Include unstaged source in an unborn repository. A tracked-only check can
    # otherwise pass before a first commit while private files remain eligible.
    output = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=project, text=True, encoding="utf-8",
    )
    files = output.rstrip("\0").split("\0") if "\0" in output else output.splitlines()
    bad = sorted({relative for relative in files if private_path(relative)})
    if bad:
        raise SystemExit("Private paths tracked or eligible for staging: " + ", ".join(bad))


def check_public_regressions(project: Path) -> None:
    """This explicitly curated fixture must never be an imported personal corpus."""
    try:
        cases = [json.loads(line) for line in (project / "evals/historical_cases.jsonl").read_text(
            encoding="utf-8",
        ).splitlines() if line.strip()]
        valid = bool(cases) and all(
            case.get("fixture_origin") == "SYNTHETIC"
            and case.get("source_id", "").startswith("synthetic-")
            for case in cases
        )
    except (OSError, ValueError, AttributeError):
        valid = False
    if not valid:
        raise SystemExit("Public regression fixture requires reviewed synthetic cases; keep personal history private")


project = Path(__file__).resolve().parents[1]
check_source_candidates(project)
check_public_regressions(project)
check_docker_provider_exclusions(project)
check_vercel_exclusions(project)
print("Privacy check passed")
