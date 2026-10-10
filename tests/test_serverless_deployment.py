import json
import os
import runpy
import shutil
import ssl
import subprocess
import sys
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from career.db import make_engine
from career.serverless import prepare_serverless_environment
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from sqlalchemy.engine import make_url
from sqlalchemy.pool import QueuePool

PROJECT = Path(__file__).resolve().parents[1]
FONT_ASSETS = ("CareerKR-Regular.ttf", "CareerKR-Bold.ttf", "OFL.txt", "SOURCE.json")


@pytest.fixture
def serverless_environment(monkeypatch, tmp_path):
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "synthetic-test-ca")])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC) - timedelta(days=1))
        .not_valid_after(datetime.now(UTC) + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    pem = certificate.public_bytes(serialization.Encoding.PEM).decode("ascii")
    settings = {
        "CAREER_ENV": "production",
        "AUTH_MODE": "supabase",
        "AUTH_TOKENS": "{}",
        "SUPABASE_URL": "https://synthetic.supabase.co",
        "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_synthetic",
        "SUPABASE_JWT_AUDIENCE": "authenticated",
        "SUPABASE_JWT_ALGORITHMS": "ES256,RS256",
        "CAREER_ALLOWED_USER_IDS": "",
        "CAREER_ALLOWED_HOSTS": "career-api.vercel.app",
        "CAREER_CORS_ORIGINS": "",
        "CAREER_LLM_PROVIDER": "none",
        "CAREER_REQUIRE_AI": "0",
        "DATABASE_URL": "postgresql://synthetic:safe%40value@synthetic.invalid:6543/postgres?sslmode=verify-full",
        "CAREER_DATABASE_CA_PEM": pem,
        "RUN_MIGRATIONS": "0",
        "VERCEL": "1",
    }
    for name, value in settings.items():
        monkeypatch.setenv(name, value)
    for name in (
        "DATABASE_POOL_MODE",
        "DATABASE_POOL_SIZE",
        "DATABASE_MAX_OVERFLOW",
        "CAREER_MAX_REQUEST_BYTES",
        "EXECUTION_TIMEOUT_SECONDS",
        "CAREER_SERVERLESS_RUNTIME",
        "VERCEL_URL",
        "SUPABASE_JWT_ISSUER",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    return pem


def test_serverless_preserves_verified_tls_and_bounds_connections(serverless_environment):
    prepare_serverless_environment()
    url = make_url(os.environ["DATABASE_URL"])
    assert url.host == "synthetic.invalid" and url.password == "safe@value"
    assert url.query["sslmode"] == "verify-full"
    path = Path(str(url.query["sslrootcert"]))
    assert path.read_text() == serverless_environment
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(cafile=str(path))
    assert context.cert_store_stats()["x509_ca"] == 1
    engine = make_engine()
    try:
        assert isinstance(engine.pool, QueuePool)
        assert engine.pool.size() == 1
        assert engine.pool._max_overflow == 0
        assert engine.url.query["sslrootcert"] == str(path)
        _, connection = engine.dialect.create_connect_args(engine.url)
        assert connection["sslmode"] == "verify-full"
        assert os.environ["DATABASE_POOL_MODE"] == "transaction"
    finally:
        engine.dispose()


@pytest.mark.parametrize("mode", ["require", "verify-ca", "disable", ""])
def test_serverless_never_downgrades_tls(serverless_environment, monkeypatch, tmp_path, mode):
    monkeypatch.setenv("DATABASE_URL", f"postgresql://synthetic:private@host.invalid/postgres?sslmode={mode}")
    with pytest.raises(ValueError) as error:
        prepare_serverless_environment()
    assert "private" not in str(error.value)
    assert "verify-full" in str(error.value)
    assert not list(tmp_path.glob("career-database-ca-*"))


@pytest.mark.parametrize(
    "settings",
    [
        {"CAREER_ENV": "development"},
        {"AUTH_MODE": "local", "AUTH_TOKENS": '{"private-auth":"owner"}'},
        {"RUN_MIGRATIONS": "1"},
        {"DATABASE_POOL_SIZE": "5"},
        {"DATABASE_MAX_OVERFLOW": "1"},
        {"CAREER_MAX_REQUEST_BYTES": "4500000"},
        {"EXECUTION_TIMEOUT_SECONDS": "300"},
        {"CAREER_ALLOWED_HOSTS": "*"},
        {"VERCEL_URL": "https://private.invalid/"},
        {"DATABASE_URL": "sqlite:///private.db"},
    ],
)
def test_serverless_rejects_unsafe_startup_before_writes(
    serverless_environment, monkeypatch, tmp_path, settings
):
    for name, value in settings.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(ValueError) as error:
        prepare_serverless_environment()
    assert "private-auth" not in str(error.value) and "private.invalid" not in str(error.value)
    assert not list(tmp_path.glob("career-database-ca-*"))


@pytest.mark.parametrize(
    "certificate",
    ["", "private-certificate-content", "-----BEGIN CERTIFICATE-----\nbad\n-----END CERTIFICATE-----"],
)
def test_serverless_invalid_ca_is_redacted(serverless_environment, monkeypatch, certificate):
    monkeypatch.setenv("CAREER_DATABASE_CA_PEM", certificate)
    with pytest.raises(ValueError) as error:
        prepare_serverless_environment()
    assert "private-certificate-content" not in str(error.value)


def test_serverless_ca_rejects_private_key_material(serverless_environment, monkeypatch):
    monkeypatch.setenv(
        "CAREER_DATABASE_CA_PEM",
        serverless_environment + "\n-----BEGIN PRIVATE KEY-----\nprivate\n-----END PRIVATE KEY-----",
    )
    with pytest.raises(ValueError, match="only public PEM certificates"):
        prepare_serverless_environment()


def test_serverless_allows_only_exact_platform_hostname(serverless_environment, monkeypatch):
    monkeypatch.setenv("VERCEL_URL", "career-api-preview.vercel.app")
    prepare_serverless_environment()
    assert os.environ["CAREER_ALLOWED_HOSTS"] == "career-api.vercel.app,career-api-preview.vercel.app"
    assert os.environ["AUTH_MODE"] == "supabase" and os.environ["AUTH_TOKENS"] == "{}"


@pytest.mark.parametrize("mode", ["invite", "public"])
def test_packaged_entrypoint_imports_without_local_secrets_or_network(serverless_environment, tmp_path, monkeypatch, mode):
    monkeypatch.setenv("CAREER_ACCESS_MODE", mode)
    for name, value in {
        "CAREER_OPERATOR_NAME": "Synthetic Operator", "CAREER_SUPPORT_EMAIL": "support@example.test",
        "CAREER_CAPTCHA_SITE_KEY": "synthetic-turnstile-site-key",
        "CAREER_CAPTCHA_ENABLED_CONFIRMED": "1", "CAREER_SMTP_CONFIGURED_CONFIRMED": "1",
        "CAREER_EMAIL_CONFIRMATION_CONFIRMED": "1", "SUPABASE_SECRET_KEY": "sb_secret_synthetic-only",
        "CAREER_BACKUP_RETENTION_DAYS": "14",
    }.items():
        monkeypatch.setenv(name, value)
    stage = tmp_path / "package"
    stage.mkdir()
    for relative in ("app.py", "pyproject.toml", "vercel.json", "alembic.ini"):
        shutil.copy2(PROJECT / relative, stage / relative)
    for folder in ("backend/career", "migrations/versions"):
        (stage / folder).mkdir(parents=True)
        for source in (PROJECT / folder).glob("*.py"):
            shutil.copy2(source, stage / folder / source.name)
    shutil.copy2(PROJECT / "migrations/env.py", stage / "migrations/env.py")
    shutil.copy2(PROJECT / "migrations/script.py.mako", stage / "migrations/script.py.mako")
    (stage / "evals").mkdir()
    shutil.copy2(PROJECT / "evals/historical_cases.jsonl", stage / "evals/historical_cases.jsonl")
    fonts = stage / "backend/career/assets/fonts"
    shutil.copytree(PROJECT / "backend/career/assets/tokenizer", stage / "backend/career/assets/tokenizer")
    fonts.mkdir(parents=True)
    for name in FONT_ASSETS:
        shutil.copy2(PROJECT / "backend/career/assets/fonts" / name, fonts / name)
    probe = """
import hashlib, io, json, socket, dotenv
from pathlib import Path
def unexpected(*args, **kwargs):
    raise AssertionError("Import must not read dotenv or open network connections")
socket.create_connection = unexpected
dotenv.load_dotenv = unexpected
import alembic.command
alembic.command.upgrade = unexpected
import app
from career.db import engine
from career.production import migration_heads
from career.document_exports import FONT_PATH, render_pdf
from fastapi.testclient import TestClient
from pypdf import PdfReader
assert engine.url.query["sslmode"] == "verify-full"
assert engine.url.query["sslrootcert"]
assert migration_heads() == {"0013"}
from career.token_estimation import gpt_oss_input_tokens
assert gpt_oss_input_tokens({"messages": [{"role": "user", "content": "합성 한국어 근거"}]}) > 256
assert FONT_PATH.resolve().is_relative_to(Path.cwd().resolve())
font_metadata = json.loads((FONT_PATH / "SOURCE.json").read_text(encoding="utf-8"))
for name in ["CareerKR-Regular.ttf", "CareerKR-Bold.ttf", "OFL.txt"]:
    assert hashlib.sha256((FONT_PATH / name).read_bytes()).hexdigest() == font_metadata["sha256"][name]
# A packaged function must render/extract Korean using its packaged fonts,
# independently of system fonts, the source checkout or private local data.
rendered = render_pdf({"text":"합성 한국어 근거와 수행 범위를 확인했습니다.", "page_budget":2})
assert rendered.pages == 1 and not rendered.overflow
assert "수행 범위" in PdfReader(io.BytesIO(rendered.content)).pages[0].extract_text()
with TestClient(app.app, base_url="https://career-api.vercel.app") as client:
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/api/settings").status_code == 401
    assert client.get("/api/settings", headers={"authorization":"Bearer private-local-token"}).status_code == 401
    assert client.get("/api/semantic/profile").status_code == 401
    assert client.post("/api/semantic/index", json={"profile_id":"test", "items":[]}).status_code == 401
    assert client.get("/health", headers={"host":"attacker.invalid"}).status_code == 400
print(json.dumps({"import":"ok", "private_api":"authenticated", "migrations":"metadata_only", "packaged_korean_pdf":"ok"}))
"""
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=stage,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    audit = json.loads(result.stdout)
    assert audit["private_api"] == "authenticated" and audit["packaged_korean_pdf"] == "ok"
    assert not list(stage.rglob("*.db")) and not list(stage.rglob(".provider-settings.json"))


def test_deployment_ignore_blocks_nested_private_files_but_keeps_runtime(tmp_path):
    if not shutil.which("git"):
        pytest.skip("Git is required to verify ignore rules")
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True, capture_output=True)
    shutil.copy2(PROJECT / ".vercelignore", tmp_path / ".gitignore")
    allowed = [
        "app.py",
        "vercel.json",
        "pyproject.toml",
        "backend/career/serverless.py",
        "migrations/env.py",
        "migrations/versions/0011_editor_drafts.py",
        "evals/historical_cases.jsonl",
        *["backend/career/assets/fonts/" + name for name in FONT_ASSETS],
        "backend/career/assets/tokenizer/o200k_base.tiktoken",
        "backend/career/assets/tokenizer/LICENSE.txt",
    ]
    denied = [
        ".provider-settings.json",
        "backend/career/.provider-settings.json.secret.tmp",
        "backend/career/.env",
        "backend/career/private_input/raw.md",
        "career.db",
        "backend/career/career.db-wal",
        "backend/career/secret.env",
        "backend/career/secret.env.production",
        "private_input/resume.md",
        "work/backups/career.backup",
        "frontend/app/page.tsx",
        "tests/test_serverless_deployment.py",
        "backend/career/owner.key",
        "backend/career/private.pem",
        "backend/career/assets/fonts/owner.key",
        "backend/career/assets/fonts/.env",
        "backend/career/assets/fonts/secret.env",
        "backend/career/assets/fonts/unsupported.ttf",
        "backend/career/assets/fonts/private_input/resume.txt",
        "backend/career/assets/fonts/.provider-settings.json",
        "backend/career/assets/fonts/work/model.onnx",
    ]
    for relative in [*allowed, *denied]:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--stdin", "-z"],
        cwd=tmp_path,
        input="\0".join([*allowed, *denied]) + "\0",
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0
    assert set(result.stdout.rstrip("\0").split("\0")) == set(denied)


def test_backend_wheel_contains_korean_fonts_and_license_without_private_files(tmp_path):
    """Exercise setuptools package-data, not merely the source-tree font path."""
    stage = tmp_path / "wheel-source"
    stage.mkdir()
    shutil.copy2(PROJECT / "pyproject.toml", stage / "pyproject.toml")
    shutil.copytree(
        PROJECT / "backend/career",
        stage / "backend/career",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".env*", ".provider-settings*"),
    )
    result = subprocess.run(
        [sys.executable, "-c", "from setuptools.build_meta import build_wheel; build_wheel('dist')"],
        cwd=stage,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    wheels = list((stage / "dist").glob("*.whl"))
    assert len(wheels) == 1
    with zipfile.ZipFile(wheels[0]) as bundle:
        names = set(bundle.namelist())
        for name in FONT_ASSETS:
            relative = "career/assets/fonts/" + name
            assert relative in names
            assert bundle.read(relative) == (PROJECT / "backend/career/assets/fonts" / name).read_bytes()
        for name in ("o200k_base.tiktoken", "LICENSE.txt"):
            relative = "career/assets/tokenizer/" + name
            assert relative in names
            assert bundle.read(relative) == (PROJECT / "backend/career/assets/tokenizer" / name).read_bytes()
        assert not any(
            name.endswith((".db", ".key", ".pem"))
            or ".provider-settings" in name
            or "private_input/" in name
            or "work/" in name
            for name in names
        )


@pytest.mark.parametrize("root", ["", "frontend"])
def test_privacy_gate_rejects_late_deployment_reinclusion(monkeypatch, tmp_path, root):
    monkeypatch.setattr(subprocess, "check_output", lambda *args, **kwargs: "")
    check = runpy.run_path(str(PROJECT / "scripts/check_privacy.py"))["check_vercel_exclusions"]
    (tmp_path / "frontend").mkdir()
    for relative in (".vercelignore", "frontend/.vercelignore"):
        shutil.copy2(PROJECT / relative, tmp_path / relative)
    target = tmp_path / root / ".vercelignore"
    target.write_text(target.read_text() + "\n!**/.provider-settings.json\n")
    with pytest.raises(SystemExit, match="Vercel deployment exclusions"):
        check(tmp_path)
