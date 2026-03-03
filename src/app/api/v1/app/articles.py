from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import rate_limiter_dependency
from app.core.db.database import async_get_db
from app.core.schemas import Actor, PaginatedResponse
from app.core.utils.cache import cache
from app.schemas.article import ArticleRead
from app.services.article_service import ArticleService

router = APIRouter(prefix="/articles", tags=["Articles"])


def get_service(db: Annotated[AsyncSession, Depends(async_get_db)]) -> ArticleService:
    return ArticleService(db=db)


ArticleServiceDependency = Annotated[ArticleService, Depends(get_service)]
ActorDependency = Annotated[Actor, Depends(rate_limiter_dependency)]


@router.get("", response_model=PaginatedResponse[ArticleRead], status_code=status.HTTP_200_OK)
@cache(
    key_prefix="app:articles:list",
    resource_id_name=["page", "items_per_page"],
    namespace="app:articles",
    expiration=60,
)
async def list_articles(
    request: Request,
    actor: ActorDependency,
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
    key_prefix="app:articles:detail",
    resource_id_name="article_id",
    expiration=60,
)
async def get_article(
    request: Request,
    article_id: int,
    actor: ActorDependency,
    service: ArticleServiceDependency,
) -> ArticleRead:
    return await service.get_article(actor=actor, article_id=article_id)
