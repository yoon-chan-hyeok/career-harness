"""Read-only stdio adapter. Inherits the same token identity as REST."""

import os

from mcp.server.fastmcp import FastMCP

from career.api import user
from career.db import SessionLocal
from career.retrieval import search
from career.truth import canonical, view
from career.workflow import Workflow

mcp = FastMCP("Career Harness")


def identity():
    with SessionLocal() as db:
        return user("Bearer " + os.getenv("CAREER_MCP_TOKEN", ""), db)


@mcp.tool()
def career_profile() -> dict:
    """Read current canonical profile for the configured token owner."""
    with SessionLocal() as db:
        return canonical(db, identity())


@mcp.tool()
def career_evidence(query: str) -> list[dict]:
    """Search verified career evidence; expression records are excluded."""
    with SessionLocal() as db:
        return search(db, identity(), query)


@mcp.tool()
def career_project_boundary(evidence_id: str) -> dict:
    """Read current project guidance and confirmation state; never confirms a binding."""
    from career.project_boundaries import context

    with SessionLocal() as db:
        return context(db, identity(), evidence_id)


@mcp.tool()
def career_submission(workspace_id: str) -> dict:
    """Read an immutable submission snapshot. Never changes submission status."""
    with SessionLocal() as db:
        return view(Workflow(db, identity()).artifact(workspace_id, "SubmissionBundle"))


if __name__ == "__main__":
    mcp.run(transport="stdio")
