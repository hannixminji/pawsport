import logging
from datetime import UTC, datetime
from enum import Enum
from typing import Annotated, Any, Literal, Union

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastcrud import PaginatedListResponse, compute_offset, paginated_response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import and_, func, not_, or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.dependencies import get_authenticated_superuser
from ...core.db.database import async_get_db
from ...core.exceptions.http_exceptions import (
    BadRequestException,
    NotFoundException,
)
from ...core.utils.cache import cache
from ...models.article import Article, ArticleCategory, ArticlePetType
from ...schemas.article import ArticleCreate, ArticleRead, ArticleUpdate

LOGGER = logging.getLogger(__name__)

router = APIRouter(tags=["articles"])


class SortOrder(str, Enum):
    ASC = "asc"
    DESC = "desc"


class ArticleSortBy(str, Enum):
    TITLE = "title"
    CATEGORY = "category"
    PET_TYPE = "pet_type"
    CREATED_AT = "created_at"


class FilterOp(str, Enum):
    EQ = "eq"
    ILIKE = "ilike"
    GTE = "gte"
    LTE = "lte"
    IN = "in"


class ArticleFilterField(str, Enum):
    TITLE = "title"
    CATEGORY = "category"
    PET_TYPE = "pet_type"


class WhereRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["rule"]
    field: ArticleFilterField
    op: FilterOp
    value: Any


class WhereGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["group"]
    op: Literal["and", "or"]
    conditions: list["WhereNode"] = Field(min_length=1, max_length=50)


class WhereNot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["not"]
    condition: "WhereNode"


WhereNode = Annotated[Union[WhereRule, WhereGroup, WhereNot], Field(discriminator="type")]


class ArticleSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(1, ge=1)
    items_per_page: int = Field(10, ge=1, le=100)

    sort_by: ArticleSortBy = ArticleSortBy.CREATED_AT
    sort_order: SortOrder = SortOrder.DESC

    where: WhereNode | None = None

    @model_validator(mode="after")
    def limit_complexity(self):
        def count_nodes(node: WhereNode, depth: int = 0) -> int:
            if depth > 10:
                raise ValueError("where is too deeply nested")

            if isinstance(node, WhereRule):
                return 1

            if isinstance(node, WhereNot):
                return 1 + count_nodes(node.condition, depth + 1)

            total = 1
            for child in node.conditions:
                total += count_nodes(child, depth + 1)
            return total

        if self.where is not None:
            total = count_nodes(self.where, 0)
            if total > 200:
                raise ValueError("where is too large")
        return self


def build_where(node: WhereNode, filter_columns: dict[ArticleFilterField, Any]):  # noqa: C901
    if isinstance(node, WhereRule):
        column = filter_columns[node.field]
        value = node.value

        if node.field == ArticleFilterField.CATEGORY:
            if node.op == FilterOp.EQ:
                if isinstance(value, str):
                    try:
                        value = ArticleCategory(value.lower())
                    except ValueError:
                        raise BadRequestException("Invalid category.")
                if not isinstance(value, ArticleCategory):
                    raise BadRequestException("Invalid category.")

            elif node.op == FilterOp.IN:
                if not isinstance(value, list) or not value:
                    raise BadRequestException("IN value must be a non-empty list.")
                converted: list[ArticleCategory] = []
                for item in value:
                    if not isinstance(item, str):
                        raise BadRequestException("category IN values must be strings.")
                    try:
                        converted.append(ArticleCategory(item.lower()))
                    except ValueError:
                        raise BadRequestException("Invalid category.")
                value = converted

            else:
                raise BadRequestException("category only supports eq or in.")

        if node.field == ArticleFilterField.PET_TYPE:
            if node.op == FilterOp.EQ:
                if isinstance(value, str):
                    try:
                        value = ArticlePetType(value.lower())
                    except ValueError:
                        raise BadRequestException("Invalid pet_type.")
                if not isinstance(value, ArticlePetType):
                    raise BadRequestException("Invalid pet_type.")

            elif node.op == FilterOp.IN:
                if not isinstance(value, list) or not value:
                    raise BadRequestException("IN value must be a non-empty list.")
                converted: list[ArticlePetType] = []
                for item in value:
                    if not isinstance(item, str):
                        raise BadRequestException("pet_type IN values must be strings.")
                    try:
                        converted.append(ArticlePetType(item.lower()))
                    except ValueError:
                        raise BadRequestException("Invalid pet_type.")
                value = converted

            else:
                raise BadRequestException("pet_type only supports eq or in.")

        if node.field == ArticleFilterField.TITLE:
            if node.op not in {FilterOp.EQ, FilterOp.ILIKE, FilterOp.IN}:
                raise BadRequestException("title only supports eq, ilike, or in.")

        if node.op == FilterOp.EQ:
            return column == value

        if node.op == FilterOp.ILIKE:
            if not isinstance(value, str):
                raise BadRequestException("ILIKE value must be a string.")
            return column.ilike(f"%{value}%")

        if node.op == FilterOp.GTE:
            return column >= value

        if node.op == FilterOp.LTE:
            return column <= value

        if node.op == FilterOp.IN:
            if not isinstance(value, list) or not value:
                raise BadRequestException("IN value must be a non-empty list.")
            return column.in_(value)

        raise BadRequestException("Invalid filter operator.")

    if isinstance(node, WhereNot):
        return not_(build_where(node.condition, filter_columns))

    children = [build_where(child, filter_columns) for child in node.conditions]
    return and_(*children) if node.op == "and" else or_(*children)


@router.post("/articles", response_model=ArticleRead, status_code=201)
async def write_article(
    request: Request,
    article: ArticleCreate,
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> ArticleRead:
    article_model = Article(**article.model_dump())
    db.add(article_model)

    try:
        await db.commit()

    except IntegrityError as error:
        await db.rollback()

        if "uq_article_title_active" in str(getattr(error, "orig", "")):
            raise BadRequestException("This article title already exists.")

        raise BadRequestException("Unable to create the article. Please try again.")

    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while creating the article. Please try again later.",
        )

    await db.refresh(article_model)

    return ArticleRead.model_validate(article_model)


@router.post("/articles/search", response_model=PaginatedListResponse[ArticleRead])
async def search_articles(
    request: Request,
    values: ArticleSearchRequest,
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> dict[str, Any]:
    filter_columns = {
        ArticleFilterField.TITLE: Article.title,
        ArticleFilterField.CATEGORY: Article.category,
        ArticleFilterField.PET_TYPE: Article.pet_type,
    }

    sort_columns = {
        ArticleSortBy.TITLE: Article.title,
        ArticleSortBy.CATEGORY: Article.category,
        ArticleSortBy.PET_TYPE: Article.pet_type,
        ArticleSortBy.CREATED_AT: Article.created_at,
    }

    where_clauses = [
        ~Article.is_deleted
    ]

    if values.where is not None:
        where_clauses.append(build_where(values.where, filter_columns))

    sort_column = sort_columns.get(values.sort_by)
    if not sort_column:
        raise BadRequestException("Invalid sort_by field.")

    order_by_clause = sort_column.asc() if values.sort_order == SortOrder.ASC else sort_column.desc()

    db_articles = (
        await db.execute(
            select(Article)
            .where(*where_clauses)
            .order_by(order_by_clause)
            .offset(compute_offset(values.page, values.items_per_page))
            .limit(values.items_per_page)
        )
    ).scalars().all()

    total_count = (
        await db.execute(
            select(func.count())
            .select_from(Article)
            .where(*where_clauses)
        )
    ).scalar_one()

    articles_data = {
        "data": [ArticleRead.model_validate(item) for item in db_articles],
        "total_count": total_count
    }

    response: dict[str, Any] = paginated_response(
        crud_data=articles_data,
        page=values.page,
        items_per_page=values.items_per_page
    )
    return response


@router.get("/articles", response_model=PaginatedListResponse[ArticleRead])
@cache(
    key_prefix="articles:page_{page}:items_per_page:{items_per_page}",
    resource_id_name="page",
    expiration=60,
)
async def read_articles(
    request: Request,
    db: Annotated[AsyncSession, Depends(async_get_db)],
    page: int = 1,
    items_per_page: int = 10,
) -> dict[str, Any]:
    db_articles = (
        await db.execute(
            select(Article)
            .where(
                ~Article.is_deleted
            )
            .offset(compute_offset(page, items_per_page))
            .limit(items_per_page)
        )
    ).scalars().all()

    total_count = (
        await db.execute(
            select(func.count())
            .select_from(Article)
            .where(
                ~Article.is_deleted
            )
        )
    ).scalar_one()

    articles_data = {
        "data": [ArticleRead.model_validate(article) for article in db_articles],
        "total_count": total_count
    }

    response: dict[str, Any] = paginated_response(
        crud_data=articles_data,
        page=page,
        items_per_page=items_per_page
    )
    return response


@router.get("/articles/{id}", response_model=ArticleRead)
@cache(key_prefix="article_cache", resource_id_name="id")
async def read_article(
    request: Request,
    id: int,
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> ArticleRead:
    db_article = (
        await db.execute(
            select(Article)
            .where(
                Article.id == id,
                ~Article.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_article:
        raise NotFoundException("Article not found")

    return ArticleRead.model_validate(db_article)


@router.patch("/articles/{id}")
@cache(
    "article_cache",
    resource_id_name="id",
    pattern_to_invalidate_extra=["articles:*"],
)
async def patch_article(
    request: Request,
    id: int,
    values: ArticleUpdate,
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> dict[str, str]:
    db_article = (
        await db.execute(
            select(Article)
            .where(
                Article.id == id,
                ~Article.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_article:
        raise NotFoundException("Article not found")

    for field, value in values.model_dump(exclude_unset=True).items():
        setattr(db_article, field, value)

    db_article.updated_at = datetime.now(UTC)

    try:
        await db.commit()

    except IntegrityError as error:
        await db.rollback()

        if "uq_article_title_active" in str(getattr(error, "orig", "")):
            raise BadRequestException("This article title already exists.")

        raise BadRequestException("Unable to update the article. Please try again.")

    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while updating the article. Please try again later.",
        )

    return {"message": "Article updated"}


@router.delete("/articles/{id}")
@cache(
    "article_cache",
    resource_id_name="id",
    to_invalidate_extra={"articles": "{id}"},
)
async def erase_article(
    request: Request,
    id: int,
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> dict[str, str]:
    db_article = (
        await db.execute(
            select(Article)
            .where(
                Article.id == id,
                ~Article.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_article:
        raise NotFoundException("Article not found")

    now = datetime.now(UTC)
    db_article.is_deleted = True
    db_article.deleted_at = now
    db.add(db_article)

    try:
        await db.commit()

    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while deleting the article. Please try again later.",
        )

    return {"message": "Article deleted"}


@router.delete(
    "/articles/db_article/{id}",
    dependencies=[Depends(get_authenticated_superuser)]
)
@cache(
    "article_cache",
    resource_id_name="id",
    to_invalidate_extra={"articles": "{id}"},
)
async def erase_db_article(
    request: Request,
    id: int,
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> dict[str, str]:
    db_article = (
        await db.execute(
            select(Article)
            .where(Article.id == id)
        )
    ).scalar_one_or_none()
    if not db_article:
        raise NotFoundException("Article not found")

    try:
        await db.delete(db_article)
        await db.commit()

    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while deleting the article. Please try again later.",
        )

    return {"message": "Article deleted from the database"}
