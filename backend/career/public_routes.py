"""Public configuration and authenticated, consent-exempt onboarding endpoints."""

from typing import Callable, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from career.public_service import accept_policy, onboarding_status, public_service_configuration


class PolicyAcceptance(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    policy_version: str = Field(min_length=1, max_length=64)
    accepted: Literal[True]


def make_router(database_dep: Callable, identity_member_dep: Callable):
    router = APIRouter(prefix="/api")

    @router.get("/service/public")
    def public_service():
        return public_service_configuration()

    @router.get("/account/onboarding")
    def account_onboarding(db: Session = Depends(database_dep, scope="function"), user: str = Depends(identity_member_dep)):
        return onboarding_status(db, user)

    @router.post("/account/onboarding")
    def account_accept(body: PolicyAcceptance, db: Session = Depends(database_dep, scope="function"),
                       user: str = Depends(identity_member_dep)):
        return accept_policy(db, user, body.policy_version)

    return router
