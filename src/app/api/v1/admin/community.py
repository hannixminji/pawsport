from typing import Annotated

from fastapi import Depends, Query, Request, status

from app.api.csrf_router import CSRFProtectedRouter
from app.api.dependencies import get_current_superuser_actor, require_permission
from app.core.schemas import Actor, PaginatedResponse
from app.core.utils.cache import cache, invalidate_namespace
from app.schemas.community import (
    ChatRead,
    CommentBulkDelete,
    CommentCreate,
    CommentRead,
    CommentUpdate,
    FirestoreUserRead,
    FirestoreUserUpdate,
    MessageRead,
    PostBulkDelete,
    PostCreate,
    PostRead,
    PostTag,
    PostTagUpdate,
    PostUpdate,
    WarnUserRead,
)
from app.services.firestore_service import FirestoreService

router = CSRFProtectedRouter(prefix="/community", tags=["Community"])


def get_service() -> FirestoreService:
    return FirestoreService()


FirestoreServiceDependency = Annotated[FirestoreService, Depends(get_service)]
SuperuserActorDependency = Annotated[Actor, Depends(get_current_superuser_actor)]


@router.get("/posts", response_model=PaginatedResponse[PostRead], status_code=status.HTTP_200_OK)
@cache(
    key_prefix="admin:community:posts:list",
    resource_id_name=["page", "items_per_page", "user_id", "tag", "include_deleted", "include_hidden"],
    namespace="community-posts",
    expiration=60,
)
async def list_posts(
    request: Request,
    actor: Annotated[Actor, Depends(require_permission("community_post:read"))],
    service: FirestoreServiceDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    items_per_page: Annotated[int, Query(ge=1, le=100, alias="itemsPerPage")] = 10,
    user_id: Annotated[str | None, Query(alias="userId")] = None,
    tag: Annotated[PostTag | None, Query()] = None,
    include_deleted: Annotated[bool, Query(alias="includeDeleted")] = False,
    include_hidden: Annotated[bool, Query(alias="includeHidden")] = False,
) -> PaginatedResponse[PostRead]:
    return await service.list_posts(
        actor=actor,
        page=page,
        items_per_page=items_per_page,
        user_id=user_id,
        tag=tag,
        include_deleted=include_deleted,
        include_hidden=include_hidden,
    )


@router.get("/posts/{post_id}", response_model=PostRead, status_code=status.HTTP_200_OK)
@cache(
    key_prefix="admin:community:posts:detail",
    resource_id_name="post_id",
    expiration=60,
)
async def get_post(
    request: Request,
    post_id: str,
    actor: Annotated[Actor, Depends(require_permission("community_post:read"))],
    service: FirestoreServiceDependency,
) -> PostRead:
    return await service.get_post(actor=actor, post_id=post_id)


@router.post("/posts", response_model=PostRead, status_code=status.HTTP_201_CREATED)
async def create_post(
    payload: PostCreate,
    actor: Annotated[Actor, Depends(require_permission("community_post:create"))],
    service: FirestoreServiceDependency,
) -> PostRead:
    result = await service.create_post(actor=actor, post_input=payload)
    await invalidate_namespace("community-posts")
    return result


@router.patch("/posts/bulk/delete", status_code=status.HTTP_204_NO_CONTENT)
async def bulk_soft_delete_posts(
    payload: PostBulkDelete,
    actor: Annotated[Actor, Depends(require_permission("community_post:bulk_soft_delete"))],
    service: FirestoreServiceDependency,
) -> None:
    await service.bulk_soft_delete_posts(actor=actor, post_ids=payload.ids)
    await invalidate_namespace("community-posts")


@router.patch("/posts/{post_id}/tag", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:community:posts:detail",
    resource_id_name="post_id",
    namespaces_to_invalidate=["community-posts"],
)
async def set_post_tag(
    request: Request,
    post_id: str,
    payload: PostTagUpdate,
    actor: Annotated[Actor, Depends(require_permission("community_post:update"))],
    service: FirestoreServiceDependency,
) -> None:
    await service.set_post_tag(actor=actor, post_id=post_id, tag=payload.tag)


@router.patch("/posts/{post_id}/pin", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:community:posts:detail",
    resource_id_name="post_id",
    namespaces_to_invalidate=["community-posts"],
)
async def pin_post(
    request: Request,
    post_id: str,
    actor: Annotated[Actor, Depends(require_permission("community_post:update"))],
    service: FirestoreServiceDependency,
) -> None:
    await service.pin_post(actor=actor, post_id=post_id)


@router.patch("/posts/{post_id}/unpin", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:community:posts:detail",
    resource_id_name="post_id",
    namespaces_to_invalidate=["community-posts"],
)
async def unpin_post(
    request: Request,
    post_id: str,
    actor: Annotated[Actor, Depends(require_permission("community_post:update"))],
    service: FirestoreServiceDependency,
) -> None:
    await service.unpin_post(actor=actor, post_id=post_id)


@router.patch("/posts/{post_id}/announce", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:community:posts:detail",
    resource_id_name="post_id",
    namespaces_to_invalidate=["community-posts"],
)
async def mark_as_announcement(
    request: Request,
    post_id: str,
    actor: Annotated[Actor, Depends(require_permission("community_post:update"))],
    service: FirestoreServiceDependency,
) -> None:
    await service.mark_as_announcement(actor=actor, post_id=post_id)


@router.patch("/posts/{post_id}/unannounce", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:community:posts:detail",
    resource_id_name="post_id",
    namespaces_to_invalidate=["community-posts"],
)
async def unmark_as_announcement(
    request: Request,
    post_id: str,
    actor: Annotated[Actor, Depends(require_permission("community_post:update"))],
    service: FirestoreServiceDependency,
) -> None:
    await service.unmark_as_announcement(actor=actor, post_id=post_id)


@router.patch("/posts/{post_id}/lock", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:community:posts:detail",
    resource_id_name="post_id",
    namespaces_to_invalidate=["community-posts"],
)
async def lock_post(
    request: Request,
    post_id: str,
    actor: Annotated[Actor, Depends(require_permission("community_post:update"))],
    service: FirestoreServiceDependency,
) -> None:
    await service.lock_post(actor=actor, post_id=post_id)


@router.patch("/posts/{post_id}/unlock", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:community:posts:detail",
    resource_id_name="post_id",
    namespaces_to_invalidate=["community-posts"],
)
async def unlock_post(
    request: Request,
    post_id: str,
    actor: Annotated[Actor, Depends(require_permission("community_post:update"))],
    service: FirestoreServiceDependency,
) -> None:
    await service.unlock_post(actor=actor, post_id=post_id)


@router.patch("/posts/{post_id}/hide", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:community:posts:detail",
    resource_id_name="post_id",
    namespaces_to_invalidate=["community-posts"],
)
async def hide_post(
    request: Request,
    post_id: str,
    actor: Annotated[Actor, Depends(require_permission("community_post:update"))],
    service: FirestoreServiceDependency,
) -> None:
    await service.hide_post(actor=actor, post_id=post_id)


@router.patch("/posts/{post_id}/unhide", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:community:posts:detail",
    resource_id_name="post_id",
    namespaces_to_invalidate=["community-posts"],
)
async def unhide_post(
    request: Request,
    post_id: str,
    actor: Annotated[Actor, Depends(require_permission("community_post:update"))],
    service: FirestoreServiceDependency,
) -> None:
    await service.unhide_post(actor=actor, post_id=post_id)


@router.patch("/posts/{post_id}/recount-comments", response_model=int, status_code=status.HTTP_200_OK)
async def recount_comments(
    post_id: str,
    actor: Annotated[Actor, Depends(require_permission("community_post:update"))],
    service: FirestoreServiceDependency,
) -> int:
    return await service.recount_comments(actor=actor, post_id=post_id)


@router.patch("/posts/{post_id}/delete", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:community:posts:detail",
    resource_id_name="post_id",
    namespaces_to_invalidate=["community-posts"],
)
async def soft_delete_post(
    request: Request,
    post_id: str,
    actor: Annotated[Actor, Depends(require_permission("community_post:soft_delete"))],
    service: FirestoreServiceDependency,
) -> None:
    await service.soft_delete_post(actor=actor, post_id=post_id)


@router.patch("/posts/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:community:posts:detail",
    resource_id_name="post_id",
    namespaces_to_invalidate=["community-posts"],
)
async def update_post(
    request: Request,
    post_id: str,
    payload: PostUpdate,
    actor: Annotated[Actor, Depends(require_permission("community_post:update"))],
    service: FirestoreServiceDependency,
) -> None:
    await service.update_post(actor=actor, post_id=post_id, post_input=payload)


@router.delete("/posts/bulk", status_code=status.HTTP_204_NO_CONTENT)
async def bulk_hard_delete_posts(
    payload: PostBulkDelete,
    actor: SuperuserActorDependency,
    service: FirestoreServiceDependency,
) -> None:
    for post_id in payload.ids:
        await service.hard_delete_post(actor=actor, post_id=post_id)
    await invalidate_namespace("community-posts")


@router.delete("/posts/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:community:posts:detail",
    resource_id_name="post_id",
    namespaces_to_invalidate=["community-posts"],
)
async def hard_delete_post(
    request: Request,
    post_id: str,
    actor: SuperuserActorDependency,
    service: FirestoreServiceDependency,
) -> None:
    await service.hard_delete_post(actor=actor, post_id=post_id)


@router.get("/posts/{post_id}/comments", response_model=PaginatedResponse[CommentRead], status_code=status.HTTP_200_OK)
@cache(
    key_prefix="admin:community:comments:list",
    resource_id_name=["post_id", "page", "items_per_page", "include_deleted"],
    namespace="community-comments",
    expiration=60,
)
async def list_comments(
    request: Request,
    post_id: str,
    actor: Annotated[Actor, Depends(require_permission("community_comment:read"))],
    service: FirestoreServiceDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    items_per_page: Annotated[int, Query(ge=1, le=100, alias="itemsPerPage")] = 10,
    include_deleted: Annotated[bool, Query(alias="includeDeleted")] = False,
) -> PaginatedResponse[CommentRead]:
    return await service.list_comments(
        actor=actor,
        post_id=post_id,
        page=page,
        items_per_page=items_per_page,
        include_deleted=include_deleted,
    )


@router.get("/posts/{post_id}/comments/{comment_id}", response_model=CommentRead, status_code=status.HTTP_200_OK)
@cache(
    key_prefix="admin:community:comments:detail",
    resource_id_name="comment_id",
    expiration=60,
)
async def get_comment(
    request: Request,
    post_id: str,
    comment_id: str,
    actor: Annotated[Actor, Depends(require_permission("community_comment:read"))],
    service: FirestoreServiceDependency,
) -> CommentRead:
    return await service.get_comment(actor=actor, post_id=post_id, comment_id=comment_id)


@router.post("/posts/{post_id}/comments", response_model=CommentRead, status_code=status.HTTP_201_CREATED)
async def create_comment(
    post_id: str,
    payload: CommentCreate,
    actor: Annotated[Actor, Depends(require_permission("community_comment:create"))],
    service: FirestoreServiceDependency,
) -> CommentRead:
    result = await service.create_comment(actor=actor, post_id=post_id, comment_input=payload)
    await invalidate_namespace("community-comments")
    return result


@router.patch("/posts/{post_id}/comments/bulk/delete", status_code=status.HTTP_204_NO_CONTENT)
async def bulk_soft_delete_comments(
    post_id: str,
    payload: CommentBulkDelete,
    actor: Annotated[Actor, Depends(require_permission("community_comment:bulk_soft_delete"))],
    service: FirestoreServiceDependency,
) -> None:
    await service.bulk_soft_delete_comments(actor=actor, post_id=post_id, comment_ids=payload.ids)
    await invalidate_namespace("community-comments")


@router.patch("/posts/{post_id}/comments/{comment_id}/delete", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:community:comments:detail",
    resource_id_name="comment_id",
    namespaces_to_invalidate=["community-comments"],
)
async def soft_delete_comment(
    request: Request,
    post_id: str,
    comment_id: str,
    actor: Annotated[Actor, Depends(require_permission("community_comment:soft_delete"))],
    service: FirestoreServiceDependency,
) -> None:
    await service.soft_delete_comment(actor=actor, post_id=post_id, comment_id=comment_id)


@router.patch("/posts/{post_id}/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:community:comments:detail",
    resource_id_name="comment_id",
    namespaces_to_invalidate=["community-comments"],
)
async def update_comment(
    request: Request,
    post_id: str,
    comment_id: str,
    payload: CommentUpdate,
    actor: Annotated[Actor, Depends(require_permission("community_comment:update"))],
    service: FirestoreServiceDependency,
) -> None:
    await service.update_comment(actor=actor, post_id=post_id, comment_id=comment_id, comment_input=payload)


@router.delete("/posts/{post_id}/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:community:comments:detail",
    resource_id_name="comment_id",
    namespaces_to_invalidate=["community-comments"],
)
async def hard_delete_comment(
    request: Request,
    post_id: str,
    comment_id: str,
    actor: SuperuserActorDependency,
    service: FirestoreServiceDependency,
) -> None:
    await service.hard_delete_comment(actor=actor, post_id=post_id, comment_id=comment_id)


@router.get("/chats", response_model=PaginatedResponse[ChatRead], status_code=status.HTTP_200_OK)
@cache(
    key_prefix="admin:community:chats:list",
    resource_id_name=["page", "items_per_page", "user_id"],
    namespace="community-chats",
    expiration=60,
)
async def list_chats(
    request: Request,
    actor: Annotated[Actor, Depends(require_permission("community_chat:read"))],
    service: FirestoreServiceDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    items_per_page: Annotated[int, Query(ge=1, le=100, alias="itemsPerPage")] = 10,
    user_id: Annotated[str | None, Query(alias="userId")] = None,
) -> PaginatedResponse[ChatRead]:
    return await service.list_chats(
        actor=actor,
        page=page,
        items_per_page=items_per_page,
        user_id=user_id,
    )


@router.get("/chats/{chat_id}", response_model=ChatRead, status_code=status.HTTP_200_OK)
@cache(
    key_prefix="admin:community:chats:detail",
    resource_id_name="chat_id",
    expiration=60,
)
async def get_chat(
    request: Request,
    chat_id: str,
    actor: Annotated[Actor, Depends(require_permission("community_chat:read"))],
    service: FirestoreServiceDependency,
) -> ChatRead:
    return await service.get_chat(actor=actor, chat_id=chat_id)


@router.delete("/chats/{chat_id}", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:community:chats:detail",
    resource_id_name="chat_id",
    namespaces_to_invalidate=["community-chats"],
)
async def hard_delete_chat(
    request: Request,
    chat_id: str,
    actor: SuperuserActorDependency,
    service: FirestoreServiceDependency,
) -> None:
    await service.hard_delete_chat(actor=actor, chat_id=chat_id)


@router.get("/chats/{chat_id}/messages", response_model=PaginatedResponse[MessageRead], status_code=status.HTTP_200_OK)
@cache(
    key_prefix="admin:community:messages:list",
    resource_id_name=["chat_id", "page", "items_per_page"],
    namespace="community-messages",
    expiration=60,
)
async def list_messages(
    request: Request,
    chat_id: str,
    actor: Annotated[Actor, Depends(require_permission("community_chat:read"))],
    service: FirestoreServiceDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    items_per_page: Annotated[int, Query(ge=1, le=100, alias="itemsPerPage")] = 10,
) -> PaginatedResponse[MessageRead]:
    return await service.list_messages(
        actor=actor,
        chat_id=chat_id,
        page=page,
        items_per_page=items_per_page,
    )


@router.delete("/chats/{chat_id}/messages/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:community:messages:detail",
    resource_id_name="message_id",
    namespaces_to_invalidate=["community-messages"],
)
async def hard_delete_message(
    request: Request,
    chat_id: str,
    message_id: str,
    actor: SuperuserActorDependency,
    service: FirestoreServiceDependency,
) -> None:
    await service.hard_delete_message(actor=actor, chat_id=chat_id, message_id=message_id)


@router.get("/users", response_model=PaginatedResponse[FirestoreUserRead], status_code=status.HTTP_200_OK)
@cache(
    key_prefix="admin:community:users:list",
    resource_id_name=["page", "items_per_page", "include_deleted"],
    namespace="community-users",
    expiration=60,
)
async def list_firestore_users(
    request: Request,
    actor: Annotated[Actor, Depends(require_permission("community_user:read"))],
    service: FirestoreServiceDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    items_per_page: Annotated[int, Query(ge=1, le=100, alias="itemsPerPage")] = 10,
    include_deleted: Annotated[bool, Query(alias="includeDeleted")] = False,
) -> PaginatedResponse[FirestoreUserRead]:
    return await service.list_firestore_users(
        actor=actor,
        page=page,
        items_per_page=items_per_page,
        include_deleted=include_deleted,
    )


@router.get("/users/{uid}", response_model=FirestoreUserRead, status_code=status.HTTP_200_OK)
@cache(
    key_prefix="admin:community:users:detail",
    resource_id_name="uid",
    expiration=60,
)
async def get_firestore_user(
    request: Request,
    uid: str,
    actor: Annotated[Actor, Depends(require_permission("community_user:read"))],
    service: FirestoreServiceDependency,
) -> FirestoreUserRead:
    return await service.get_firestore_user(actor=actor, uid=uid)


@router.patch("/users/{uid}/ban", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:community:users:detail",
    resource_id_name="uid",
    namespaces_to_invalidate=["community-users"],
)
async def ban_user(
    request: Request,
    uid: str,
    actor: Annotated[Actor, Depends(require_permission("community_user:moderate"))],
    service: FirestoreServiceDependency,
) -> None:
    await service.ban_user(actor=actor, uid=uid)


@router.patch("/users/{uid}/unban", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:community:users:detail",
    resource_id_name="uid",
    namespaces_to_invalidate=["community-users"],
)
async def unban_user(
    request: Request,
    uid: str,
    actor: Annotated[Actor, Depends(require_permission("community_user:moderate"))],
    service: FirestoreServiceDependency,
) -> None:
    await service.unban_user(actor=actor, uid=uid)


@router.patch("/users/{uid}/mute", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:community:users:detail",
    resource_id_name="uid",
    namespaces_to_invalidate=["community-users"],
)
async def mute_user(
    request: Request,
    uid: str,
    actor: Annotated[Actor, Depends(require_permission("community_user:moderate"))],
    service: FirestoreServiceDependency,
) -> None:
    await service.mute_user(actor=actor, uid=uid)


@router.patch("/users/{uid}/unmute", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:community:users:detail",
    resource_id_name="uid",
    namespaces_to_invalidate=["community-users"],
)
async def unmute_user(
    request: Request,
    uid: str,
    actor: Annotated[Actor, Depends(require_permission("community_user:moderate"))],
    service: FirestoreServiceDependency,
) -> None:
    await service.unmute_user(actor=actor, uid=uid)


@router.patch("/users/{uid}/restrict-post", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:community:users:detail",
    resource_id_name="uid",
    namespaces_to_invalidate=["community-users"],
)
async def restrict_post_user(
    request: Request,
    uid: str,
    actor: Annotated[Actor, Depends(require_permission("community_user:moderate"))],
    service: FirestoreServiceDependency,
) -> None:
    await service.restrict_post_user(actor=actor, uid=uid)


@router.patch("/users/{uid}/unrestrict-post", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:community:users:detail",
    resource_id_name="uid",
    namespaces_to_invalidate=["community-users"],
)
async def unrestrict_post_user(
    request: Request,
    uid: str,
    actor: Annotated[Actor, Depends(require_permission("community_user:moderate"))],
    service: FirestoreServiceDependency,
) -> None:
    await service.unrestrict_post_user(actor=actor, uid=uid)


@router.patch("/users/{uid}/shadow-ban", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:community:users:detail",
    resource_id_name="uid",
    namespaces_to_invalidate=["community-users"],
)
async def shadow_ban_user(
    request: Request,
    uid: str,
    actor: Annotated[Actor, Depends(require_permission("community_user:moderate"))],
    service: FirestoreServiceDependency,
) -> None:
    await service.shadow_ban_user(actor=actor, uid=uid)


@router.patch("/users/{uid}/unshadow-ban", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:community:users:detail",
    resource_id_name="uid",
    namespaces_to_invalidate=["community-users"],
)
async def unshadow_ban_user(
    request: Request,
    uid: str,
    actor: Annotated[Actor, Depends(require_permission("community_user:moderate"))],
    service: FirestoreServiceDependency,
) -> None:
    await service.unshadow_ban_user(actor=actor, uid=uid)


@router.patch("/users/{uid}/warn", response_model=WarnUserRead, status_code=status.HTTP_200_OK)
@cache(
    key_prefix="admin:community:users:detail",
    resource_id_name="uid",
    namespaces_to_invalidate=["community-users"],
)
async def warn_user(
    request: Request,
    uid: str,
    actor: Annotated[Actor, Depends(require_permission("community_user:moderate"))],
    service: FirestoreServiceDependency,
) -> WarnUserRead:
    warning_count = await service.warn_user(actor=actor, uid=uid)
    return WarnUserRead(warning_count=warning_count)


@router.patch("/users/{uid}/reset-warnings", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:community:users:detail",
    resource_id_name="uid",
    namespaces_to_invalidate=["community-users"],
)
async def reset_warnings(
    request: Request,
    uid: str,
    actor: Annotated[Actor, Depends(require_permission("community_user:moderate"))],
    service: FirestoreServiceDependency,
) -> None:
    await service.reset_warnings(actor=actor, uid=uid)


@router.patch("/users/{uid}/delete", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:community:users:detail",
    resource_id_name="uid",
    namespaces_to_invalidate=["community-users"],
)
async def soft_delete_firestore_user(
    request: Request,
    uid: str,
    actor: Annotated[Actor, Depends(require_permission("community_user:soft_delete"))],
    service: FirestoreServiceDependency,
) -> None:
    await service.soft_delete_firestore_user(actor=actor, uid=uid)


@router.patch("/users/{uid}", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:community:users:detail",
    resource_id_name="uid",
    namespaces_to_invalidate=["community-users"],
)
async def update_firestore_user(
    request: Request,
    uid: str,
    payload: FirestoreUserUpdate,
    actor: Annotated[Actor, Depends(require_permission("community_user:update"))],
    service: FirestoreServiceDependency,
) -> None:
    await service.update_firestore_user(actor=actor, uid=uid, user_input=payload)


@router.delete("/users/{uid}", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:community:users:detail",
    resource_id_name="uid",
    namespaces_to_invalidate=["community-users"],
)
async def hard_delete_firestore_user(
    request: Request,
    uid: str,
    actor: SuperuserActorDependency,
    service: FirestoreServiceDependency,
) -> None:
    await service.hard_delete_firestore_user(actor=actor, uid=uid)
