"""Identity-only adapters for private-account lifecycle and deletion retries."""

from typing import Callable, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from career.account_lifecycle import DeletionPending, account_status, delete_account


class AccountDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    confirmation: Literal["DELETE"]
    reauthentication_token: str = Field(min_length=1, max_length=16384, repr=False)

    @field_validator("reauthentication_token")
    @classmethod
    def bare_token(cls, value: str):
        if any(character.isspace() for character in value):
            raise ValueError("이메일 재인증 결과를 확인해 주세요.")
        return value


def build_account_router(database_dep: Callable, identity_dep: Callable):
    router = APIRouter(prefix="/api/account")

    @router.get("")
    def read_account(db: Session = Depends(database_dep, scope="function"), ident: str = Depends(identity_dep)):
        return account_status(db, ident)

    @router.post("/delete")
    def remove_account(body: AccountDeleteRequest, db: Session = Depends(database_dep, scope="function"),
                       ident: str = Depends(identity_dep)):
        try:
            return delete_account(db, ident, body.confirmation, body.reauthentication_token)
        except DeletionPending as error:
            return JSONResponse(status_code=503, content=error.payload)

    return router
