from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException

from app.domain.enums import Role


@dataclass(frozen=True)
class Caller:
    role: Role
    site_scope: str | None
    user: str


def get_caller(
    x_role: Annotated[str, Header()] = Role.DATA_MANAGER.value,
    x_site_scope: Annotated[str | None, Header()] = None,
    x_user: Annotated[str, Header()] = "demo_user",
) -> Caller:
    try:
        role = Role(x_role)
    except ValueError:
        raise HTTPException(400, f"unknown role: {x_role}")
    return Caller(role=role, site_scope=x_site_scope or None, user=x_user)
