from typing import Annotated

from fastapi import Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.csrf_router import CSRFProtectedRouter
from app.api.dependencies import get_current_superuser_actor, require_permission
from app.core.db.database import async_get_db
from app.core.schemas import Actor, PaginatedResponse
from app.core.search_engine.schemas import SearchRequest
from app.core.utils.cache import cache, invalidate_namespace
from app.schemas.article import (
    ArticleBulkDelete,
    ArticleCreate,
    ArticleRead,
    ArticleUpdate,
)
from app.services.article_service import ArticleService

router = CSRFProtectedRouter(prefix="/articles", tags=["Articles"])


def get_service(db: Annotated[AsyncSession, Depends(async_get_db)]) -> ArticleService:
    return ArticleService(db=db)


ArticleServiceDependency = Annotated[ArticleService, Depends(get_service)]
SuperuserActorDependency = Annotated[Actor, Depends(get_current_superuser_actor)]


@router.post("", response_model=ArticleRead, status_code=status.HTTP_201_CREATED)
async def create_article(
    request: Request,
    payload: ArticleCreate,
    actor: Annotated[Actor, Depends(require_permission("article:create"))],
    service: ArticleServiceDependency,
) -> ArticleRead:
    result = await service.create(actor=actor, article_input=payload)
    await invalidate_namespace("admin:articles")
    return result


@router.post("/search", response_model=PaginatedResponse[ArticleRead], status_code=status.HTTP_200_OK)
async def search_articles(
    search_request: SearchRequest,
    actor: Annotated[Actor, Depends(require_permission("article:search"))],
    service: ArticleServiceDependency,
) -> PaginatedResponse[ArticleRead]:
    return await service.search(actor=actor, search_request=search_request)


@router.get("", response_model=PaginatedResponse[ArticleRead], status_code=status.HTTP_200_OK)
@cache(
    key_prefix="admin:articles:list",
    resource_id_name=["page", "items_per_page"],
    namespace="admin:articles",
    expiration=60,
)
async def list_articles(
    request: Request,
    actor: Annotated[Actor, Depends(require_permission("article:read"))],
    service: ArticleServiceDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    items_per_page: Annotated[int, Query(ge=1, le=100, alias="itemsPerPage")] = 10,
) -> PaginatedResponse[ArticleRead]:
    return await service.get_all_articles(
        actor=actor,
        page=page,
        items_per_page=items_per_page,
    )


@router.get("/{article_id}", response_model=ArticleRead, status_code=status.HTTP_200_OK)
@cache(
    key_prefix="admin:articles:detail",
    resource_id_name="article_id",
    expiration=60,
)
async def get_article(
    request: Request,
    article_id: int,
    actor: Annotated[Actor, Depends(require_permission("article:read"))],
    service: ArticleServiceDependency,
) -> ArticleRead:
    return await service.get_article(actor=actor, article_id=article_id)


@router.patch("/bulk/delete", status_code=status.HTTP_204_NO_CONTENT)
async def bulk_soft_delete_articles(
    payload: ArticleBulkDelete,
    actor: Annotated[Actor, Depends(require_permission("article:bulk_soft_delete"))],
    service: ArticleServiceDependency,
) -> None:
    await service.bulk_soft_delete(actor=actor, article_ids=payload.ids)
    await invalidate_namespace("admin:articles")


@router.patch("/{article_id}/delete", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:articles:detail",
    resource_id_name="article_id",
    namespaces_to_invalidate=["admin:articles"],
)
async def soft_delete_article(
    request: Request,
    article_id: int,
    actor: Annotated[Actor, Depends(require_permission("article:soft_delete"))],
    service: ArticleServiceDependency,
) -> None:
    await service.soft_delete(actor=actor, article_id=article_id)


@router.patch("/{article_id}", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:articles:detail",
    resource_id_name="article_id",
    namespaces_to_invalidate=["admin:articles"],
)
async def update_article(
    request: Request,
    article_id: int,
    payload: ArticleUpdate,
    actor: Annotated[Actor, Depends(require_permission("article:update"))],
    service: ArticleServiceDependency,
) -> None:
    await service.update(actor=actor, article_id=article_id, article_input=payload)


@router.delete("/bulk", status_code=status.HTTP_204_NO_CONTENT)
async def bulk_hard_delete_articles(
    payload: ArticleBulkDelete,
    actor: SuperuserActorDependency,
    service: ArticleServiceDependency,
) -> None:
    await service.bulk_hard_delete(actor=actor, article_ids=payload.ids)
    await invalidate_namespace("admin:articles")


@router.delete("/{article_id}", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:articles:detail",
    resource_id_name="article_id",
    namespaces_to_invalidate=["admin:articles"],
)
async def hard_delete_article(
    request: Request,
    article_id: int,
    actor: SuperuserActorDependency,
    service: ArticleServiceDependency,
) -> None:
    await service.hard_delete(actor=actor, article_id=article_id)
