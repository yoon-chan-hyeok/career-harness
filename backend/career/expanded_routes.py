"""Authenticated experience choices and read-only personal administration."""

from typing import Callable

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from career import admin
from career.activity import run_operation
from career.experience_options import ExperienceChoiceRequest, choose, options
from career.workflow import Workflow


def build_expanded_router(database_dep: Callable, user_dep: Callable):
    router = APIRouter(prefix="/api")

    @router.get("/applications/{workspace}/experience-options")
    def experience_options(workspace: str, slot: str = Query("strategy", min_length=1, max_length=100),
                           db: Session = Depends(database_dep, scope="function"), ident: str = Depends(user_dep)):
        return options(Workflow(db, ident), workspace, slot)

    @router.post("/applications/{workspace}/experience-options/select")
    def experience_choice(workspace: str, body: ExperienceChoiceRequest,
                          db: Session = Depends(database_dep, scope="function"), ident: str = Depends(user_dep)):
        return run_operation(db, ident, workspace, "select-experience",
                             lambda: choose(Workflow(db, ident), workspace, body), uses_ai=False)

    @router.get("/admin/access")
    def admin_access(ident: str = Depends(user_dep)):
        return {"is_admin": admin.is_admin(ident)}

    @router.get("/admin/status")
    def admin_status(db: Session = Depends(database_dep, scope="function"), ident: str = Depends(user_dep)):
        return admin.status(db, ident)

    return router
