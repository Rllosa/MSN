from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.api.schemas import AdminUserInfo, CreateUserRequest, UpdateUserRequest
from app.auth.dependencies import AdminUser
from app.auth.hashing import hash_password
from app.db.session import SessionDep

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users", response_model=list[AdminUserInfo])
async def list_users(_: AdminUser, session: SessionDep) -> list[AdminUserInfo]:
    rows = (
        await session.execute(
            text(
                "SELECT id::text, email, is_active, is_admin, created_at"
                " FROM users ORDER BY created_at ASC"
            )
        )
    ).fetchall()
    return [
        AdminUserInfo(
            id=row.id,
            email=row.email,
            is_active=row.is_active,
            is_admin=row.is_admin,
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.post(
    "/users", response_model=AdminUserInfo, status_code=status.HTTP_201_CREATED
)
async def create_user(
    body: CreateUserRequest, _: AdminUser, session: SessionDep
) -> AdminUserInfo:
    pw_hash = hash_password(body.password)
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO users (email, password_hash, is_active, is_admin)"
                    " VALUES (:email, :pw_hash, TRUE, :is_admin)"
                    " RETURNING id::text, email, is_active, is_admin, created_at"
                ),
                {"email": body.email, "pw_hash": pw_hash, "is_admin": body.is_admin},
            )
        ).fetchone()
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )
    return AdminUserInfo(
        id=row.id,
        email=row.email,
        is_active=row.is_active,
        is_admin=row.is_admin,
        created_at=row.created_at,
    )


@router.delete(
    "/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None
)
async def delete_user(user_id: str, _: AdminUser, session: SessionDep) -> None:
    # Verify user exists
    target = (
        await session.execute(
            text("SELECT is_admin FROM users WHERE id = :id"),
            {"id": user_id},
        )
    ).fetchone()
    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    # Block deletion if this is the last admin
    if target.is_admin:
        admin_count = (
            await session.execute(
                text("SELECT COUNT(*) FROM users WHERE is_admin = TRUE")
            )
        ).scalar()
        if admin_count <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete the last admin",
            )

    await session.execute(
        text("DELETE FROM users WHERE id = :id"),
        {"id": user_id},
    )
    await session.commit()


@router.patch("/users/{user_id}", response_model=AdminUserInfo)
async def patch_user(
    user_id: str, body: UpdateUserRequest, _: AdminUser, session: SessionDep
) -> AdminUserInfo:
    # Build SET clause from only the fields that were provided
    updates: dict[str, object] = {}
    if body.password is not None:
        updates["password_hash"] = hash_password(body.password)
    if body.is_admin is not None:
        updates["is_admin"] = body.is_admin
    if body.is_active is not None:
        updates["is_active"] = body.is_active

    if not updates:
        # No-op: just return current state
        row = (
            await session.execute(
                text(
                    "SELECT id::text, email, is_active, is_admin, created_at"
                    " FROM users WHERE id = :id"
                ),
                {"id": user_id},
            )
        ).fetchone()
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )
        return AdminUserInfo(
            id=row.id,
            email=row.email,
            is_active=row.is_active,
            is_admin=row.is_admin,
            created_at=row.created_at,
        )

    set_clause = ", ".join(f"{col} = :{col}" for col in updates)
    updates["id"] = user_id
    row = (
        await session.execute(
            text(
                f"UPDATE users SET {set_clause} WHERE id = :id"  # noqa: S608
                " RETURNING id::text, email, is_active, is_admin, created_at"
            ),
            updates,
        )
    ).fetchone()
    await session.commit()

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    return AdminUserInfo(
        id=row.id,
        email=row.email,
        is_active=row.is_active,
        is_admin=row.is_admin,
        created_at=row.created_at,
    )
