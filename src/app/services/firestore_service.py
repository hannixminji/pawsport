import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import ClassVar

from firebase_admin import firestore, firestore_async
from google.api_core.exceptions import GoogleAPICallError, RetryError, ServiceUnavailable
from google.cloud.firestore_v1 import AsyncClient, AsyncCollectionReference
from google.cloud.firestore_v1.base_query import FieldFilter

from ..core.enums import ActorType
from ..core.exceptions.authorization_exceptions import ForbiddenError
from ..core.exceptions.db_exceptions import NonTransientDatabaseError, TransientDatabaseError
from ..core.exceptions.domain_exceptions import NotFoundError
from ..core.schemas import Actor, PaginatedResponse
from ..core.utils.pagination import compute_offset
from ..schemas.community import (
    ChatRead,
    CommentCreate,
    CommentRead,
    CommentUpdate,
    FirestoreUserRead,
    FirestoreUserUpdate,
    MessageRead,
    PostCreate,
    PostRead,
    PostTag,
    PostUpdate,
)

LOGGER = logging.getLogger(__name__)

_POSTS = "posts"
_COMMENTS = "comments"
_CHATS = "chats"
_MESSAGES = "messages"
_USERS = "users"


def _now() -> datetime:
    return datetime.now(UTC)


def _client() -> AsyncClient:
    LOGGER.debug("Creating Firestore async client")
    return firestore_async.client()


def _map_firestore_error(error: GoogleAPICallError, action: str) -> None:
    LOGGER.exception("Firestore error during '%s': %s", action, error)
    if isinstance(error, (ServiceUnavailable, RetryError)):
        raise TransientDatabaseError(
            f"{action} Please try again later."
        ) from error

    raise NonTransientDatabaseError(action) from error


def _serialize_post(doc_id: str, data: dict) -> PostRead:
    return PostRead(
        id=doc_id,
        user_id=data.get("user_id", ""),
        username=data.get("username", ""),
        user_profile_image=data.get("user_profile_image", ""),
        text=data.get("text", ""),
        tag=data.get("tag", PostTag.GENERAL),
        image_urls=data.get("image_urls", []),
        video_url=data.get("video_url"),
        likes_count=data.get("likes_count", 0),
        comments_count=data.get("comments_count", 0),
        is_pinned=data.get("is_pinned", False),
        is_announcement=data.get("is_announcement", False),
        is_locked=data.get("is_locked", False),
        is_hidden=data.get("is_hidden", False),
        is_deleted=data.get("is_deleted", False),
        created_at=data.get("created_at", _now()),
        updated_at=data.get("updated_at"),
    )


def _serialize_comment(doc_id: str, post_id: str, data: dict) -> CommentRead:
    return CommentRead(
        id=doc_id,
        post_id=post_id,
        user_id=data.get("user_id", ""),
        username=data.get("username", ""),
        user_profile_image=data.get("user_profile_image", ""),
        text=data.get("text", ""),
        likes_count=data.get("likes_count", 0),
        reply_count=data.get("reply_count", 0),
        is_deleted=data.get("is_deleted", False),
        created_at=data.get("created_at", _now()),
        updated_at=data.get("updated_at"),
    )


def _serialize_message(doc_id: str, chat_id: str, data: dict) -> MessageRead:
    return MessageRead(
        id=doc_id,
        chat_id=chat_id,
        sender_id=data.get("sender_id", ""),
        text=data.get("text"),
        image_url=data.get("image_url"),
        created_at=data.get("created_at", _now()),
    )


def _serialize_firestore_user(doc_id: str, data: dict) -> FirestoreUserRead:
    return FirestoreUserRead(
        id=doc_id,
        postgres_id=data.get("id"),
        username=data.get("username", ""),
        user_profile_image=data.get("user_profile_image", ""),
        is_banned=data.get("is_banned", False),
        is_muted=data.get("is_muted", False),
        is_post_restricted=data.get("is_post_restricted", False),
        is_shadow_banned=data.get("is_shadow_banned", False),
        warning_count=data.get("warning_count", 0),
        is_deleted=data.get("is_deleted", False),
        created_at=data.get("created_at"),
        updated_at=data.get("updated_at"),
    )


@dataclass(slots=True)
class FirestoreService:
    DEFAULT_PAGE_SIZE: ClassVar[int] = 20
    MAX_PAGE_SIZE: ClassVar[int] = 100
    MAX_BULK_DELETE_SIZE: ClassVar[int] = 500

    @staticmethod
    def _require_admin(actor: Actor, action: str) -> None:
        if actor.actor_type != ActorType.ADMIN_USER:
            raise ForbiddenError(f"Admin privileges are required to {action}.")

    @staticmethod
    async def _cascade_delete_subcollection(
        collection_ref: AsyncCollectionReference,
    ) -> None:
        async for doc in collection_ref.stream():
            await doc.reference.delete()

    async def _require_user_exists(self, *, uid: str) -> None:
        try:
            doc = await _client().collection(_USERS).document(uid).get()
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to fetch the user.")

        if not doc.exists:
            raise NotFoundError("Firestore user not found.")

    async def get_post(
        self,
        *,
        actor: Actor,
        post_id: str,
    ) -> PostRead:
        self._require_admin(actor, "view posts")

        try:
            doc = await _client().collection(_POSTS).document(post_id).get()
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to fetch the post.")
        except Exception as exc:
            LOGGER.exception("Unexpected error fetching post '%s'", post_id)
            raise RuntimeError(f"Unexpected error fetching post '{post_id}'.") from exc

        if not doc.exists:
            raise NotFoundError("Post not found.")

        return _serialize_post(doc.id, doc.to_dict())

    async def list_posts(
        self,
        *,
        actor: Actor,
        page: int,
        items_per_page: int,
        user_id: str | None = None,
        tag: PostTag | None = None,
        include_deleted: bool = False,
        include_hidden: bool = False,
    ) -> PaginatedResponse[PostRead]:
        self._require_admin(actor, "list posts")

        try:
            db = _client()
            query = db.collection(_POSTS)

            if not include_deleted:
                query = query.where(filter=FieldFilter("is_deleted", "==", False))

            if not include_hidden:
                query = query.where(filter=FieldFilter("is_hidden", "==", False))

            if user_id is not None:
                query = query.where(filter=FieldFilter("user_id", "==", user_id))

            if tag is not None:
                query = query.where(filter=FieldFilter("tag", "==", tag.value))

            query = (
                query
                .order_by("is_announcement", direction="DESCENDING")
                .order_by("is_pinned", direction="DESCENDING")
                .order_by("created_at", direction="DESCENDING")
                .offset(compute_offset(page, items_per_page))
                .limit(items_per_page + 1)
            )

            docs = [doc async for doc in query.stream()]
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to fetch posts.")
        except Exception as exc:
            LOGGER.exception("Unexpected error listing posts")
            raise RuntimeError("Unexpected error listing posts.") from exc

        has_more = len(docs) > items_per_page
        data = [
            _serialize_post(doc.id, doc.to_dict())
            for doc in docs[:items_per_page]
        ]

        return PaginatedResponse[PostRead](
            data=data,
            total_count=-1,
            has_more=has_more,
            page=page,
            items_per_page=items_per_page,
        )

    async def create_post(
        self,
        *,
        actor: Actor,
        post_input: PostCreate,
    ) -> PostRead:
        self._require_admin(actor, "create posts")

        now = _now()
        payload = {
            **post_input.model_dump(),
            "likes_count": 0,
            "comments_count": 0,
            "is_pinned": False,
            "is_announcement": False,
            "is_locked": False,
            "is_hidden": False,
            "is_deleted": False,
            "created_at": now,
            "updated_at": now,
        }

        try:
            _, ref = await _client().collection(_POSTS).add(payload)
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to create the post.")
        except Exception as exc:
            LOGGER.exception("Unexpected error creating post")
            raise RuntimeError("Unexpected error creating post.") from exc

        return _serialize_post(ref.id, payload)

    async def update_post(
        self,
        *,
        actor: Actor,
        post_id: str,
        post_input: PostUpdate,
    ) -> None:
        self._require_admin(actor, "update posts")

        db = _client()
        ref = db.collection(_POSTS).document(post_id)

        try:
            doc = await ref.get()
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to fetch the post.")
        except Exception as exc:
            LOGGER.exception("Unexpected error fetching post '%s'", post_id)
            raise RuntimeError(f"Unexpected error fetching post '{post_id}'.") from exc

        if not doc.exists:
            raise NotFoundError("Post not found.")

        updates = {k: v for k, v in post_input.model_dump().items() if v is not None}
        updates["updated_at"] = _now()

        try:
            await ref.update(updates)
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to update the post.")
        except Exception as exc:
            LOGGER.exception("Unexpected error updating post '%s'", post_id)
            raise RuntimeError(f"Unexpected error updating post '{post_id}'.") from exc

    async def set_post_tag(
        self,
        *,
        actor: Actor,
        post_id: str,
        tag: PostTag,
    ) -> None:
        self._require_admin(actor, "tag posts")

        db = _client()
        ref = db.collection(_POSTS).document(post_id)

        try:
            doc = await ref.get()
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to fetch the post.")
        except Exception as exc:
            LOGGER.exception("Unexpected error fetching post '%s'", post_id)
            raise RuntimeError(f"Unexpected error fetching post '{post_id}'.") from exc

        if not doc.exists:
            raise NotFoundError("Post not found.")

        try:
            await ref.update({"tag": tag.value, "updated_at": _now()})
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to set the post tag.")
        except Exception as exc:
            LOGGER.exception("Unexpected error setting tag on post '%s'", post_id)
            raise RuntimeError(f"Unexpected error setting tag on post '{post_id}'.") from exc

    async def pin_post(
        self,
        *,
        actor: Actor,
        post_id: str,
    ) -> None:
        self._require_admin(actor, "pin posts")

        db = _client()
        ref = db.collection(_POSTS).document(post_id)

        try:
            doc = await ref.get()
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to fetch the post.")
        except Exception as exc:
            LOGGER.exception("Unexpected error fetching post '%s'", post_id)
            raise RuntimeError(f"Unexpected error fetching post '{post_id}'.") from exc

        if not doc.exists:
            raise NotFoundError("Post not found.")

        try:
            await ref.update({"is_pinned": True, "updated_at": _now()})
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to pin the post.")
        except Exception as exc:
            LOGGER.exception("Unexpected error pinning post '%s'", post_id)
            raise RuntimeError(f"Unexpected error pinning post '{post_id}'.") from exc

    async def unpin_post(
        self,
        *,
        actor: Actor,
        post_id: str,
    ) -> None:
        self._require_admin(actor, "unpin posts")

        db = _client()
        ref = db.collection(_POSTS).document(post_id)

        try:
            doc = await ref.get()
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to fetch the post.")
        except Exception as exc:
            LOGGER.exception("Unexpected error fetching post '%s'", post_id)
            raise RuntimeError(f"Unexpected error fetching post '{post_id}'.") from exc

        if not doc.exists:
            raise NotFoundError("Post not found.")

        try:
            await ref.update({"is_pinned": False, "updated_at": _now()})
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to unpin the post.")
        except Exception as exc:
            LOGGER.exception("Unexpected error unpinning post '%s'", post_id)
            raise RuntimeError(f"Unexpected error unpinning post '{post_id}'.") from exc

    async def mark_as_announcement(
        self,
        *,
        actor: Actor,
        post_id: str,
    ) -> None:
        self._require_admin(actor, "mark posts as announcements")

        db = _client()
        ref = db.collection(_POSTS).document(post_id)

        try:
            doc = await ref.get()
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to fetch the post.")
        except Exception as exc:
            LOGGER.exception("Unexpected error fetching post '%s'", post_id)
            raise RuntimeError(f"Unexpected error fetching post '{post_id}'.") from exc

        if not doc.exists:
            raise NotFoundError("Post not found.")

        try:
            await ref.update({"is_announcement": True, "updated_at": _now()})
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to mark the post as an announcement.")
        except Exception as exc:
            LOGGER.exception("Unexpected error marking post '%s' as announcement", post_id)
            raise RuntimeError(f"Unexpected error marking post '{post_id}' as announcement.") from exc

    async def unmark_as_announcement(
        self,
        *,
        actor: Actor,
        post_id: str,
    ) -> None:
        self._require_admin(actor, "unmark announcements")

        db = _client()
        ref = db.collection(_POSTS).document(post_id)

        try:
            doc = await ref.get()
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to fetch the post.")
        except Exception as exc:
            LOGGER.exception("Unexpected error fetching post '%s'", post_id)
            raise RuntimeError(f"Unexpected error fetching post '{post_id}'.") from exc

        if not doc.exists:
            raise NotFoundError("Post not found.")

        try:
            await ref.update({"is_announcement": False, "updated_at": _now()})
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to unmark the announcement.")
        except Exception as exc:
            LOGGER.exception("Unexpected error unmarking post '%s' as announcement", post_id)
            raise RuntimeError(f"Unexpected error unmarking post '{post_id}' as announcement.") from exc

    async def lock_post(
        self,
        *,
        actor: Actor,
        post_id: str,
    ) -> None:
        self._require_admin(actor, "lock posts")

        db = _client()
        ref = db.collection(_POSTS).document(post_id)

        try:
            doc = await ref.get()
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to fetch the post.")
        except Exception as exc:
            LOGGER.exception("Unexpected error fetching post '%s'", post_id)
            raise RuntimeError(f"Unexpected error fetching post '{post_id}'.") from exc

        if not doc.exists:
            raise NotFoundError("Post not found.")

        try:
            await ref.update({"is_locked": True, "updated_at": _now()})
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to lock the post.")
        except Exception as exc:
            LOGGER.exception("Unexpected error locking post '%s'", post_id)
            raise RuntimeError(f"Unexpected error locking post '{post_id}'.") from exc

    async def unlock_post(
        self,
        *,
        actor: Actor,
        post_id: str,
    ) -> None:
        self._require_admin(actor, "unlock posts")

        db = _client()
        ref = db.collection(_POSTS).document(post_id)

        try:
            doc = await ref.get()
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to fetch the post.")
        except Exception as exc:
            LOGGER.exception("Unexpected error fetching post '%s'", post_id)
            raise RuntimeError(f"Unexpected error fetching post '{post_id}'.") from exc

        if not doc.exists:
            raise NotFoundError("Post not found.")

        try:
            await ref.update({"is_locked": False, "updated_at": _now()})
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to unlock the post.")
        except Exception as exc:
            LOGGER.exception("Unexpected error unlocking post '%s'", post_id)
            raise RuntimeError(f"Unexpected error unlocking post '{post_id}'.") from exc

    async def hide_post(
        self,
        *,
        actor: Actor,
        post_id: str,
    ) -> None:
        self._require_admin(actor, "hide posts")

        db = _client()
        ref = db.collection(_POSTS).document(post_id)

        try:
            doc = await ref.get()
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to fetch the post.")
        except Exception as exc:
            LOGGER.exception("Unexpected error fetching post '%s'", post_id)
            raise RuntimeError(f"Unexpected error fetching post '{post_id}'.") from exc

        if not doc.exists:
            raise NotFoundError("Post not found.")

        try:
            await ref.update({"is_hidden": True, "updated_at": _now()})
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to hide the post.")
        except Exception as exc:
            LOGGER.exception("Unexpected error hiding post '%s'", post_id)
            raise RuntimeError(f"Unexpected error hiding post '{post_id}'.") from exc

    async def unhide_post(
        self,
        *,
        actor: Actor,
        post_id: str,
    ) -> None:
        self._require_admin(actor, "unhide posts")

        db = _client()
        ref = db.collection(_POSTS).document(post_id)

        try:
            doc = await ref.get()
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to fetch the post.")
        except Exception as exc:
            LOGGER.exception("Unexpected error fetching post '%s'", post_id)
            raise RuntimeError(f"Unexpected error fetching post '{post_id}'.") from exc

        if not doc.exists:
            raise NotFoundError("Post not found.")

        try:
            await ref.update({"is_hidden": False, "updated_at": _now()})
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to unhide the post.")
        except Exception as exc:
            LOGGER.exception("Unexpected error unhiding post '%s'", post_id)
            raise RuntimeError(f"Unexpected error unhiding post '{post_id}'.") from exc

    async def recount_comments(
        self,
        *,
        actor: Actor,
        post_id: str,
    ) -> int:
        self._require_admin(actor, "recount comments")

        db = _client()
        ref = db.collection(_POSTS).document(post_id)

        try:
            doc = await ref.get()
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to fetch the post.")
        except Exception as exc:
            LOGGER.exception("Unexpected error fetching post '%s'", post_id)
            raise RuntimeError(f"Unexpected error fetching post '{post_id}'.") from exc

        if not doc.exists:
            raise NotFoundError("Post not found.")

        try:
            count = sum(
                1
                async for doc in ref.collection(_COMMENTS)
                .where(filter=FieldFilter("is_deleted", "==", False))
                .stream()
            )
            await ref.update({"comments_count": count, "updated_at": _now()})
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to recount comments.")
        except Exception as exc:
            LOGGER.exception("Unexpected error recounting comments on post '%s'", post_id)
            raise RuntimeError(f"Unexpected error recounting comments on post '{post_id}'.") from exc

        return count

    async def soft_delete_post(
        self,
        *,
        actor: Actor,
        post_id: str,
    ) -> None:
        self._require_admin(actor, "delete posts")

        db = _client()
        ref = db.collection(_POSTS).document(post_id)

        try:
            doc = await ref.get()
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to fetch the post.")
        except Exception as exc:
            LOGGER.exception("Unexpected error fetching post '%s'", post_id)
            raise RuntimeError(f"Unexpected error fetching post '{post_id}'.") from exc

        if not doc.exists:
            raise NotFoundError("Post not found.")

        try:
            await ref.update({"is_deleted": True, "updated_at": _now()})
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to delete the post.")
        except Exception as exc:
            LOGGER.exception("Unexpected error soft-deleting post '%s'", post_id)
            raise RuntimeError(f"Unexpected error soft-deleting post '{post_id}'.") from exc

    async def hard_delete_post(
        self,
        *,
        actor: Actor,
        post_id: str,
    ) -> None:
        if not actor.is_superuser:
            raise ForbiddenError("Superuser privileges are required to permanently delete a post.")

        db = _client()
        ref = db.collection(_POSTS).document(post_id)

        try:
            doc = await ref.get()
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to fetch the post.")
        except Exception as exc:
            LOGGER.exception("Unexpected error fetching post '%s'", post_id)
            raise RuntimeError(f"Unexpected error fetching post '{post_id}'.") from exc

        if not doc.exists:
            raise NotFoundError("Post not found.")

        try:
            await self._cascade_delete_subcollection(ref.collection(_COMMENTS))
            await ref.delete()
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to permanently delete the post.")
        except Exception as exc:
            LOGGER.exception("Unexpected error hard-deleting post '%s'", post_id)
            raise RuntimeError(f"Unexpected error hard-deleting post '{post_id}'.") from exc

    async def bulk_soft_delete_posts(
        self,
        *,
        actor: Actor,
        post_ids: set[str],
    ) -> None:
        self._require_admin(actor, "bulk delete posts")

        if not post_ids:
            return

        if len(post_ids) > self.MAX_BULK_DELETE_SIZE:
            raise ForbiddenError(f"Bulk delete is limited to {self.MAX_BULK_DELETE_SIZE} posts at a time.")

        db = _client()
        batch = db.batch()
        now = _now()

        for post_id in post_ids:
            ref = db.collection(_POSTS).document(post_id)
            batch.update(ref, {"is_deleted": True, "updated_at": now})

        try:
            await batch.commit()
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to bulk delete posts.")
        except Exception as exc:
            LOGGER.exception("Unexpected error bulk soft-deleting posts")
            raise RuntimeError("Unexpected error bulk soft-deleting posts.") from exc

    async def get_comment(
        self,
        *,
        actor: Actor,
        post_id: str,
        comment_id: str,
    ) -> CommentRead:
        self._require_admin(actor, "view comments")

        try:
            doc = await (
                _client()
                .collection(_POSTS)
                .document(post_id)
                .collection(_COMMENTS)
                .document(comment_id)
                .get()
            )
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to fetch the comment.")
        except Exception as exc:
            LOGGER.exception("Unexpected error fetching comment '%s' on post '%s'", comment_id, post_id)
            raise RuntimeError(f"Unexpected error fetching comment '{comment_id}' on post '{post_id}'.") from exc

        if not doc.exists:
            raise NotFoundError("Comment not found.")

        return _serialize_comment(doc.id, post_id, doc.to_dict())

    async def list_comments(
        self,
        *,
        actor: Actor,
        post_id: str,
        page: int,
        items_per_page: int,
        include_deleted: bool = False,
    ) -> PaginatedResponse[CommentRead]:
        self._require_admin(actor, "list comments")

        db = _client()
        query = db.collection(_POSTS).document(post_id).collection(_COMMENTS)

        if not include_deleted:
            query = query.where(filter=FieldFilter("is_deleted", "==", False))

        query = (
            query
            .order_by("created_at", direction="ASCENDING")
            .offset(compute_offset(page, items_per_page))
            .limit(items_per_page + 1)
        )

        try:
            docs = [doc async for doc in query.stream()]
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to fetch comments.")
        except Exception as exc:
            LOGGER.exception("Unexpected error listing comments on post '%s'", post_id)
            raise RuntimeError(f"Unexpected error listing comments on post '{post_id}'.") from exc

        has_more = len(docs) > items_per_page
        data = [
            _serialize_comment(doc.id, post_id, doc.to_dict())
            for doc in docs[:items_per_page]
        ]

        return PaginatedResponse[CommentRead](
            data=data,
            total_count=-1,
            has_more=has_more,
            page=page,
            items_per_page=items_per_page,
        )

    async def create_comment(
        self,
        *,
        actor: Actor,
        post_id: str,
        comment_input: CommentCreate,
    ) -> CommentRead:
        self._require_admin(actor, "create comments")

        db = _client()
        post_ref = db.collection(_POSTS).document(post_id)

        try:
            post_doc = await post_ref.get()
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to fetch the post.")
        except Exception as exc:
            LOGGER.exception("Unexpected error fetching post '%s'", post_id)
            raise RuntimeError(f"Unexpected error fetching post '{post_id}'.") from exc

        if not post_doc.exists:
            raise NotFoundError("Post not found.")

        now = _now()
        payload = {
            **comment_input.model_dump(),
            "is_deleted": False,
            "created_at": now,
            "updated_at": now,
        }

        try:
            _, ref = await post_ref.collection(_COMMENTS).add(payload)
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to create the comment.")
        except Exception as exc:
            LOGGER.exception("Unexpected error creating comment on post '%s'", post_id)
            raise RuntimeError(f"Unexpected error creating comment on post '{post_id}'.") from exc

        return _serialize_comment(ref.id, post_id, payload)

    async def update_comment(
        self,
        *,
        actor: Actor,
        post_id: str,
        comment_id: str,
        comment_input: CommentUpdate,
    ) -> None:
        self._require_admin(actor, "update comments")

        db = _client()
        ref = (
            db.collection(_POSTS)
            .document(post_id)
            .collection(_COMMENTS)
            .document(comment_id)
        )

        try:
            doc = await ref.get()
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to fetch the comment.")
        except Exception as exc:
            LOGGER.exception("Unexpected error fetching comment '%s' on post '%s'", comment_id, post_id)
            raise RuntimeError(f"Unexpected error fetching comment '{comment_id}' on post '{post_id}'.") from exc

        if not doc.exists:
            raise NotFoundError("Comment not found.")

        updates = {k: v for k, v in comment_input.model_dump().items() if v is not None}
        updates["updated_at"] = _now()

        try:
            await ref.update(updates)
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to update the comment.")
        except Exception as exc:
            LOGGER.exception("Unexpected error updating comment '%s' on post '%s'", comment_id, post_id)
            raise RuntimeError(f"Unexpected error updating comment '{comment_id}' on post '{post_id}'.") from exc

    async def soft_delete_comment(
        self,
        *,
        actor: Actor,
        post_id: str,
        comment_id: str,
    ) -> None:
        self._require_admin(actor, "delete comments")

        db = _client()
        post_ref = db.collection(_POSTS).document(post_id)
        ref = post_ref.collection(_COMMENTS).document(comment_id)

        try:
            doc = await ref.get()
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to fetch the comment.")
        except Exception as exc:
            LOGGER.exception("Unexpected error fetching comment '%s' on post '%s'", comment_id, post_id)
            raise RuntimeError(f"Unexpected error fetching comment '{comment_id}' on post '{post_id}'.") from exc

        if not doc.exists:
            raise NotFoundError("Comment not found.")

        try:
            await ref.update({"is_deleted": True, "updated_at": _now()})
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to delete the comment.")
        except Exception as exc:
            LOGGER.exception("Unexpected error soft-deleting comment '%s' on post '%s'", comment_id, post_id)
            raise RuntimeError(f"Unexpected error soft-deleting comment '{comment_id}' on post '{post_id}'.") from exc

    async def hard_delete_comment(
        self,
        *,
        actor: Actor,
        post_id: str,
        comment_id: str,
    ) -> None:
        if not actor.is_superuser:
            raise ForbiddenError("Superuser privileges are required to permanently delete a comment.")

        db = _client()
        post_ref = db.collection(_POSTS).document(post_id)
        ref = post_ref.collection(_COMMENTS).document(comment_id)

        try:
            doc = await ref.get()
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to fetch the comment.")
        except Exception as exc:
            LOGGER.exception("Unexpected error fetching comment '%s' on post '%s'", comment_id, post_id)
            raise RuntimeError(f"Unexpected error fetching comment '{comment_id}' on post '{post_id}'.") from exc

        if not doc.exists:
            raise NotFoundError("Comment not found.")

        try:
            await ref.delete()
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to permanently delete the comment.")
        except Exception as exc:
            LOGGER.exception("Unexpected error hard-deleting comment '%s' on post '%s'", comment_id, post_id)
            raise RuntimeError(f"Unexpected error hard-deleting comment '{comment_id}' on post '{post_id}'.") from exc

    async def bulk_soft_delete_comments(
        self,
        *,
        actor: Actor,
        post_id: str,
        comment_ids: set[str],
    ) -> None:
        self._require_admin(actor, "bulk delete comments")

        if not comment_ids:
            return

        if len(comment_ids) > self.MAX_BULK_DELETE_SIZE:
            raise ForbiddenError(f"Bulk delete is limited to {self.MAX_BULK_DELETE_SIZE} comments at a time.")

        db = _client()
        post_ref = db.collection(_POSTS).document(post_id)
        batch = db.batch()
        now = _now()

        for comment_id in comment_ids:
            ref = post_ref.collection(_COMMENTS).document(comment_id)
            batch.update(ref, {"is_deleted": True, "updated_at": now})

        try:
            await batch.commit()
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to bulk delete comments.")
        except Exception as exc:
            LOGGER.exception("Unexpected error bulk soft-deleting comments on post '%s'", post_id)
            raise RuntimeError(f"Unexpected error bulk soft-deleting comments on post '{post_id}'.") from exc

    async def get_chat(
        self,
        *,
        actor: Actor,
        chat_id: str,
    ) -> ChatRead:
        self._require_admin(actor, "view chats")

        try:
            doc = await _client().collection(_CHATS).document(chat_id).get()
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to fetch the chat.")
        except Exception as exc:
            LOGGER.exception("Unexpected error fetching chat '%s'", chat_id)
            raise RuntimeError(f"Unexpected error fetching chat '{chat_id}'.") from exc

        if not doc.exists:
            raise NotFoundError("Chat not found.")

        return ChatRead(id=doc.id, **doc.to_dict())

    async def list_chats(
        self,
        *,
        actor: Actor,
        page: int,
        items_per_page: int,
        user_id: str | None = None,
    ) -> PaginatedResponse[ChatRead]:
        self._require_admin(actor, "list chats")

        db = _client()
        query = db.collection(_CHATS)

        if user_id is not None:
            query = query.where(
                filter=FieldFilter("participants", "array_contains", user_id)
            )

        query = (
            query
            .order_by("last_message_time", direction="DESCENDING")
            .offset(compute_offset(page, items_per_page))
            .limit(items_per_page + 1)
        )

        try:
            docs = [doc async for doc in query.stream()]
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to fetch chats.")
        except Exception as exc:
            LOGGER.exception("Unexpected error listing chats")
            raise RuntimeError("Unexpected error listing chats.") from exc

        has_more = len(docs) > items_per_page
        data = [
            ChatRead(id=doc.id, **doc.to_dict())
            for doc in docs[:items_per_page]
        ]

        return PaginatedResponse[ChatRead](
            data=data,
            total_count=-1,
            has_more=has_more,
            page=page,
            items_per_page=items_per_page,
        )

    async def hard_delete_chat(
        self,
        *,
        actor: Actor,
        chat_id: str,
    ) -> None:
        if not actor.is_superuser:
            raise ForbiddenError("Superuser privileges are required to permanently delete a chat.")

        db = _client()
        ref = db.collection(_CHATS).document(chat_id)

        try:
            doc = await ref.get()
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to fetch the chat.")
        except Exception as exc:
            LOGGER.exception("Unexpected error fetching chat '%s'", chat_id)
            raise RuntimeError(f"Unexpected error fetching chat '{chat_id}'.") from exc

        if not doc.exists:
            raise NotFoundError("Chat not found.")

        try:
            await self._cascade_delete_subcollection(ref.collection(_MESSAGES))
            await ref.delete()
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to permanently delete the chat.")
        except Exception as exc:
            LOGGER.exception("Unexpected error hard-deleting chat '%s'", chat_id)
            raise RuntimeError(f"Unexpected error hard-deleting chat '{chat_id}'.") from exc

    async def list_messages(
        self,
        *,
        actor: Actor,
        chat_id: str,
        page: int,
        items_per_page: int,
    ) -> PaginatedResponse[MessageRead]:
        self._require_admin(actor, "list messages")

        db = _client()
        query = (
            db.collection(_CHATS)
            .document(chat_id)
            .collection(_MESSAGES)
            .order_by("created_at", direction="ASCENDING")
            .offset(compute_offset(page, items_per_page))
            .limit(items_per_page + 1)
        )

        try:
            docs = [doc async for doc in query.stream()]
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to fetch messages.")
        except Exception as exc:
            LOGGER.exception("Unexpected error listing messages in chat '%s'", chat_id)
            raise RuntimeError(f"Unexpected error listing messages in chat '{chat_id}'.") from exc

        has_more = len(docs) > items_per_page
        data = [
            _serialize_message(doc.id, chat_id, doc.to_dict())
            for doc in docs[:items_per_page]
        ]

        return PaginatedResponse[MessageRead](
            data=data,
            total_count=-1,
            has_more=has_more,
            page=page,
            items_per_page=items_per_page,
        )

    async def hard_delete_message(
        self,
        *,
        actor: Actor,
        chat_id: str,
        message_id: str,
    ) -> None:
        if not actor.is_superuser:
            raise ForbiddenError("Superuser privileges are required to permanently delete a message.")

        db = _client()
        ref = (
            db.collection(_CHATS)
            .document(chat_id)
            .collection(_MESSAGES)
            .document(message_id)
        )

        try:
            doc = await ref.get()
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to fetch the message.")
        except Exception as exc:
            LOGGER.exception("Unexpected error fetching message '%s' in chat '%s'", message_id, chat_id)
            raise RuntimeError(f"Unexpected error fetching message '{message_id}' in chat '{chat_id}'.") from exc

        if not doc.exists:
            raise NotFoundError("Message not found.")

        try:
            await ref.delete()
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to permanently delete the message.")
        except Exception as exc:
            LOGGER.exception("Unexpected error hard-deleting message '%s' in chat '%s'", message_id, chat_id)
            raise RuntimeError(f"Unexpected error hard-deleting message '{message_id}' in chat '{chat_id}'.") from exc

    async def get_firestore_user(
        self,
        *,
        actor: Actor,
        uid: str,
    ) -> FirestoreUserRead:
        self._require_admin(actor, "view users")

        try:
            doc = await _client().collection(_USERS).document(uid).get()
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to fetch the user.")
        except Exception as exc:
            LOGGER.exception("Unexpected error fetching user '%s'", uid)
            raise RuntimeError(f"Unexpected error fetching user '{uid}'.") from exc

        if not doc.exists:
            raise NotFoundError("Firestore user not found.")

        return _serialize_firestore_user(doc.id, doc.to_dict())

    async def list_firestore_users(
        self,
        *,
        actor: Actor,
        page: int,
        items_per_page: int,
        include_deleted: bool = False,
    ) -> PaginatedResponse[FirestoreUserRead]:
        self._require_admin(actor, "list users")

        db = _client()
        query = db.collection(_USERS)

        if not include_deleted:
            query = query.where(filter=FieldFilter("is_deleted", "==", False))

        query = (
            query
            .order_by("created_at", direction="DESCENDING")
            .offset(compute_offset(page, items_per_page))
            .limit(items_per_page + 1)
        )

        try:
            docs = [doc async for doc in query.stream()]
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to fetch users.")
        except Exception as exc:
            LOGGER.exception("Unexpected error listing users")
            raise RuntimeError("Unexpected error listing users.") from exc

        has_more = len(docs) > items_per_page
        data = [
            _serialize_firestore_user(doc.id, doc.to_dict())
            for doc in docs[:items_per_page]
        ]

        return PaginatedResponse[FirestoreUserRead](
            data=data,
            total_count=-1,
            has_more=has_more,
            page=page,
            items_per_page=items_per_page,
        )

    async def update_firestore_user(
        self,
        *,
        actor: Actor,
        uid: str,
        user_input: FirestoreUserUpdate,
    ) -> None:
        self._require_admin(actor, "update users")

        db = _client()
        ref = db.collection(_USERS).document(uid)

        try:
            doc = await ref.get()
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to fetch the user.")
        except Exception as exc:
            LOGGER.exception("Unexpected error fetching user '%s'", uid)
            raise RuntimeError(f"Unexpected error fetching user '{uid}'.") from exc

        if not doc.exists:
            raise NotFoundError("Firestore user not found.")

        updates = {k: v for k, v in user_input.model_dump().items() if v is not None}
        updates["updated_at"] = _now()

        try:
            await ref.update(updates)
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to update the user.")
        except Exception as exc:
            LOGGER.exception("Unexpected error updating user '%s'", uid)
            raise RuntimeError(f"Unexpected error updating user '{uid}'.") from exc

    async def ban_user(
        self,
        *,
        actor: Actor,
        uid: str,
    ) -> None:
        self._require_admin(actor, "ban users")
        await self._require_user_exists(uid=uid)

        try:
            await _client().collection(_USERS).document(uid).update(
                {"is_banned": True, "updated_at": _now()}
            )
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to ban the user.")
        except Exception as exc:
            LOGGER.exception("Unexpected error banning user '%s'", uid)
            raise RuntimeError(f"Unexpected error banning user '{uid}'.") from exc

    async def unban_user(
        self,
        *,
        actor: Actor,
        uid: str,
    ) -> None:
        self._require_admin(actor, "unban users")
        await self._require_user_exists(uid=uid)

        try:
            await _client().collection(_USERS).document(uid).update(
                {"is_banned": False, "updated_at": _now()}
            )
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to unban the user.")
        except Exception as exc:
            LOGGER.exception("Unexpected error unbanning user '%s'", uid)
            raise RuntimeError(f"Unexpected error unbanning user '{uid}'.") from exc

    async def mute_user(
        self,
        *,
        actor: Actor,
        uid: str,
    ) -> None:
        self._require_admin(actor, "mute users")
        await self._require_user_exists(uid=uid)

        try:
            await _client().collection(_USERS).document(uid).update(
                {"is_muted": True, "updated_at": _now()}
            )
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to mute the user.")
        except Exception as exc:
            LOGGER.exception("Unexpected error muting user '%s'", uid)
            raise RuntimeError(f"Unexpected error muting user '{uid}'.") from exc

    async def unmute_user(
        self,
        *,
        actor: Actor,
        uid: str,
    ) -> None:
        self._require_admin(actor, "unmute users")
        await self._require_user_exists(uid=uid)

        try:
            await _client().collection(_USERS).document(uid).update(
                {"is_muted": False, "updated_at": _now()}
            )
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to unmute the user.")
        except Exception as exc:
            LOGGER.exception("Unexpected error unmuting user '%s'", uid)
            raise RuntimeError(f"Unexpected error unmuting user '{uid}'.") from exc

    async def restrict_post_user(
        self,
        *,
        actor: Actor,
        uid: str,
    ) -> None:
        self._require_admin(actor, "restrict users from posting")
        await self._require_user_exists(uid=uid)

        try:
            await _client().collection(_USERS).document(uid).update(
                {"is_post_restricted": True, "updated_at": _now()}
            )
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to restrict the user from posting.")
        except Exception as exc:
            LOGGER.exception("Unexpected error restricting post for user '%s'", uid)
            raise RuntimeError(f"Unexpected error restricting post for user '{uid}'.") from exc

    async def unrestrict_post_user(
        self,
        *,
        actor: Actor,
        uid: str,
    ) -> None:
        self._require_admin(actor, "unrestrict users from posting")
        await self._require_user_exists(uid=uid)

        try:
            await _client().collection(_USERS).document(uid).update(
                {"is_post_restricted": False, "updated_at": _now()}
            )
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to unrestrict the user from posting.")
        except Exception as exc:
            LOGGER.exception("Unexpected error unrestricting post for user '%s'", uid)
            raise RuntimeError(f"Unexpected error unrestricting post for user '{uid}'.") from exc

    async def shadow_ban_user(
        self,
        *,
        actor: Actor,
        uid: str,
    ) -> None:
        self._require_admin(actor, "shadow ban users")
        await self._require_user_exists(uid=uid)

        try:
            await _client().collection(_USERS).document(uid).update(
                {"is_shadow_banned": True, "updated_at": _now()}
            )
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to shadow ban the user.")
        except Exception as exc:
            LOGGER.exception("Unexpected error shadow banning user '%s'", uid)
            raise RuntimeError(f"Unexpected error shadow banning user '{uid}'.") from exc

    async def unshadow_ban_user(
        self,
        *,
        actor: Actor,
        uid: str,
    ) -> None:
        self._require_admin(actor, "remove shadow ban from users")
        await self._require_user_exists(uid=uid)

        try:
            await _client().collection(_USERS).document(uid).update(
                {"is_shadow_banned": False, "updated_at": _now()}
            )
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to remove the shadow ban from the user.")
        except Exception as exc:
            LOGGER.exception("Unexpected error removing shadow ban from user '%s'", uid)
            raise RuntimeError(f"Unexpected error removing shadow ban from user '{uid}'.") from exc

    async def warn_user(
        self,
        *,
        actor: Actor,
        uid: str,
    ) -> int:
        self._require_admin(actor, "warn users")
        await self._require_user_exists(uid=uid)

        try:
            ref = _client().collection(_USERS).document(uid)
            await ref.update(
                {
                    "warning_count": firestore.Increment(1),
                    "updated_at": _now(),
                }
            )
            doc = await ref.get()
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to warn the user.")
        except Exception as exc:
            LOGGER.exception("Unexpected error warning user '%s'", uid)
            raise RuntimeError(f"Unexpected error warning user '{uid}'.") from exc

        return doc.to_dict().get("warning_count", 1)

    async def reset_warnings(
        self,
        *,
        actor: Actor,
        uid: str,
    ) -> None:
        self._require_admin(actor, "reset user warnings")
        await self._require_user_exists(uid=uid)

        try:
            await _client().collection(_USERS).document(uid).update(
                {"warning_count": 0, "updated_at": _now()}
            )
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to reset the user's warnings.")
        except Exception as exc:
            LOGGER.exception("Unexpected error resetting warnings for user '%s'", uid)
            raise RuntimeError(f"Unexpected error resetting warnings for user '{uid}'.") from exc

    async def soft_delete_firestore_user(
        self,
        *,
        actor: Actor,
        uid: str,
    ) -> None:
        self._require_admin(actor, "delete users")
        await self._require_user_exists(uid=uid)

        try:
            await _client().collection(_USERS).document(uid).update(
                {"is_deleted": True, "updated_at": _now()}
            )
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to delete the user.")
        except Exception as exc:
            LOGGER.exception("Unexpected error soft-deleting user '%s'", uid)
            raise RuntimeError(f"Unexpected error soft-deleting user '{uid}'.") from exc

    async def hard_delete_firestore_user(
        self,
        *,
        actor: Actor,
        uid: str,
    ) -> None:
        if not actor.is_superuser:
            raise ForbiddenError("Superuser privileges are required to permanently delete a user.")

        await self._require_user_exists(uid=uid)

        try:
            await _client().collection(_USERS).document(uid).delete()
        except GoogleAPICallError as error:
            _map_firestore_error(error, "Failed to permanently delete the user.")
        except Exception as exc:
            LOGGER.exception("Unexpected error hard-deleting user '%s'", uid)
            raise RuntimeError(f"Unexpected error hard-deleting user '{uid}'.") from exc
