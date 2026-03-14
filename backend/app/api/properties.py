from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.api.schemas import CreatePropertyRequest, PropertyInfo, UpdatePropertyRequest
from app.auth.dependencies import AdminUser, CurrentUser
from app.db.session import SessionDep

router = APIRouter(prefix="/properties", tags=["properties"])


def _slugify(name: str) -> str:
    """Lowercase, replace non-alphanumeric runs with hyphens, strip edge hyphens."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


@router.get("/", response_model=list[PropertyInfo])
async def list_properties(_: CurrentUser, session: SessionDep) -> list[PropertyInfo]:
    rows = (
        await session.execute(
            text(
                "SELECT id::text, name, slug, beds24_property_id, created_at"
                " FROM properties"
                " WHERE is_active = TRUE"
                " ORDER BY name ASC"
            )
        )
    ).fetchall()
    return [
        PropertyInfo(
            id=row.id,
            name=row.name,
            slug=row.slug,
            beds24_property_id=row.beds24_property_id,
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.post("/", response_model=PropertyInfo, status_code=status.HTTP_201_CREATED)
async def create_property(
    body: CreatePropertyRequest, _: AdminUser, session: SessionDep
) -> PropertyInfo:
    slug = body.slug if body.slug is not None else _slugify(body.name)
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO properties (name, slug)"
                    " VALUES (:name, :slug)"
                    " RETURNING id::text, name, slug, created_at"
                ),
                {"name": body.name, "slug": slug},
            )
        ).fetchone()
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Slug already exists",
        )
    return PropertyInfo(
        id=row.id,
        name=row.name,
        slug=row.slug,
        beds24_property_id=getattr(row, "beds24_property_id", None),
        created_at=row.created_at,
    )


@router.patch("/{property_id}", response_model=PropertyInfo)
async def patch_property(
    property_id: str,
    body: UpdatePropertyRequest,
    _: AdminUser,
    session: SessionDep,
) -> PropertyInfo:
    updates: dict[str, object] = {}
    if body.name is not None:
        updates["name"] = body.name
    if body.slug is not None:
        updates["slug"] = body.slug
    elif body.name is not None:
        # Auto-regenerate slug from new name when slug not explicitly provided
        updates["slug"] = _slugify(body.name)

    if not updates:
        row = (
            await session.execute(
                text(
                    "SELECT id::text, name, slug, created_at"
                    " FROM properties WHERE id = :id"
                ),
                {"id": property_id},
            )
        ).fetchone()
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Property not found"
            )
        return PropertyInfo(
            id=row.id,
            name=row.name,
            slug=row.slug,
            created_at=row.created_at,
        )

    set_clause = ", ".join(f"{col} = :{col}" for col in updates)
    updates["id"] = property_id
    try:
        row = (
            await session.execute(
                text(
                    f"UPDATE properties SET {set_clause} WHERE id = :id"  # noqa: S608
                    " RETURNING id::text, name, slug, created_at"
                ),
                updates,
            )
        ).fetchone()
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Slug already exists",
        )

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Property not found"
        )
    return PropertyInfo(
        id=row.id,
        name=row.name,
        slug=row.slug,
        beds24_property_id=getattr(row, "beds24_property_id", None),
        created_at=row.created_at,
    )


@router.delete(
    "/{property_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None
)
async def delete_property(property_id: str, _: AdminUser, session: SessionDep) -> None:
    # Verify the property exists
    target = (
        await session.execute(
            text("SELECT id FROM properties WHERE id = :id AND is_active = TRUE"),
            {"id": property_id},
        )
    ).fetchone()
    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Property not found"
        )

    # Block soft-delete if any conversations reference this property
    conv_count = (
        await session.execute(
            text("SELECT COUNT(*) FROM conversations WHERE property_id = :id"),
            {"id": property_id},
        )
    ).scalar()
    if conv_count:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Property has active conversations",
        )

    await session.execute(
        text("UPDATE properties SET is_active = FALSE WHERE id = :id"),
        {"id": property_id},
    )
    await session.commit()
