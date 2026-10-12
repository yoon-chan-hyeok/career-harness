import asyncio
import json
import os
import sys
from pathlib import Path

from career.db import Base
from career.truth import add_fact, register_source
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def test_mcp_reads_same_truth_through_stdio(tmp_path):
    url = f"sqlite:///{tmp_path / 'mcp.db'}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        source, _ = register_source(db, "alice", "proof", "graduated", "USER_CORRECTION")
        add_fact(db, "alice", source.id, "profile", "graduation", {"text": "graduated"})
        from career.project_boundaries import bind, catalog, fingerprint
        from career.references import register
        from career.truth import add_evidence

        register(db, "alice", "cover", "# 10. Projects\n## Synthetic component\n전체 시스템을 처음부터 개발했다고 쓰지 않는다.")
        component, _ = register_source(db, "alice", "component", "구성요소를 수정했다.", "RAW_RESULT")
        evidence = add_evidence(db, "alice", component.id, "Synthetic component", "구성요소를 수정했다.", status="VERIFIED")
        bind(db, "alice", evidence.id, {"rule_id": catalog(db, "alice")[0]["id"],
             "evidence_hash": fingerprint(evidence), "confirmed": True})
        evidence_id = evidence.id
        db.commit()
    engine.dispose()

    async def check():
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "career.mcp_server"],
            env={
                **os.environ,
                "DATABASE_URL": url,
                "AUTH_TOKENS": json.dumps({"test-key": "alice"}),
                "CAREER_MCP_TOKEN": "test-key",
                "PYTHONPATH": str(Path("backend").resolve()),
            },
        )
        async with stdio_client(parameters) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert {t.name for t in tools.tools} == {
                    "career_profile",
                    "career_evidence",
                    "career_project_boundary",
                    "career_submission",
                }
                result = await session.call_tool("career_profile")
                assert not result.isError
                assert "graduated" in str(result.content)
                boundary = await session.call_tool("career_project_boundary", {"evidence_id": evidence_id})
                assert not boundary.isError and "FULL_BUILD" in str(boundary.content)
                assert "fact_authority" in str(boundary.content)
                denied_boundary = await session.call_tool("career_project_boundary", {"evidence_id":"another-owners-evidence"})
                assert denied_boundary.isError
                denied = await session.call_tool(
                    "career_submission", {"workspace_id": "someone-elses-workspace"}
                )
                assert denied.isError

    asyncio.run(check())
