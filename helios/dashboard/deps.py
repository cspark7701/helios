"""Dependencies for HELIOS dashboard routes."""

import time
from collections.abc import Callable

from fastapi import Header, HTTPException, Request

from helios.core.plan_engine import PlanStore
from helios.interfaces.base import BaseControlInterface
from helios.safety.rollback import RollbackController
from helios.security.rbac import AuthToken, Permission, RBACManager


def get_plan_store(request: Request) -> PlanStore:
    return request.app.state.plan_store


def get_rollback_controller(request: Request) -> RollbackController:
    return request.app.state.rollback_controller


def get_rbac_manager(request: Request) -> RBACManager:
    return request.app.state.rbac


def get_control_interface(request: Request) -> BaseControlInterface:
    return request.app.state.control_interface


def require_permission(required_perm: Permission) -> Callable:
    async def dependency(
        request: Request,
        authorization: str | None = Header(None, alias="Authorization"),
        x_auth_token: str | None = Header(None, alias="X-Auth-Token"),
    ) -> AuthToken:
        token_str = None
        if authorization:
            if authorization.lower().startswith("bearer "):
                token_str = authorization[7:].strip()
            else:
                token_str = authorization.strip()
        elif x_auth_token:
            token_str = x_auth_token.strip()

        if not token_str:
            raise HTTPException(
                status_code=401,
                detail="Authentication credentials were not provided. Expected Bearer or X-Auth-Token.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        rbac: RBACManager = request.app.state.rbac
        token = rbac._active_tokens.get(token_str)
        if not token or time.time() > token.expires_at:
            raise HTTPException(
                status_code=401,
                detail="Invalid or expired session authorization token.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if not rbac.verify_permission(token_str, required_perm):
            raise HTTPException(
                status_code=403,
                detail=f"Forbidden: role '{token.role.value}' lacks required permission '{required_perm.value}'.",
            )

        return token

    return dependency
