from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.http.models import (
    Distance,
    Filter,
    PayloadSchemaType,
    PointIdsList,
    PointStruct,
    UpdateResult,
    VectorParams,
)

from ..config import settings

COLLECTIONS = {
    "pet_profile_images": 1_536,
    "report_sightings": 1_536
}

INDEX_FIELDS = {
    "pet_profile_images": {
        "species": PayloadSchemaType.KEYWORD,
        "is_missing": PayloadSchemaType.BOOL
    }
}

client = QdrantClient(
    url=settings.QDRANT_CLOUD_URL,
    api_key=settings.QDRANT_CLOUD_API_KEY.get_secret_value()
)


def init_collections() -> None:
    existing_collections = [collection.name for collection in client.get_collections().collections]
    for collection_name, vector_size in COLLECTIONS.items():
        if collection_name not in existing_collections:
            client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(
                    size=vector_size,
                    distance=Distance.COSINE
                )
            )

    for collection_name, fields in INDEX_FIELDS.items():
        collection_info = client.get_collection(collection_name)
        existing_indexes = set(collection_info.payload_schema.keys())

        for field_name, schema in fields.items():
            if field_name not in existing_indexes:
                client.create_payload_index(
                    collection_name=collection_name,
                    field_name=field_name,
                    field_schema=schema
                )


def upsert_embedding(collection_name: str, points: PointStruct | list[PointStruct]) -> UpdateResult:
    if isinstance(points, PointStruct):
        points = [points]

    return client.upsert(
        collection_name=collection_name,
        points=points
    )


def search_pet(
    collection_name: str,
    query_vector: list[float],
    limit: int = 10,
    score_threshold: float = 0.60,
    query_filter: Filter | None = None,
) -> list[dict[str, Any]]:
    query_response = client.query_points(
        collection_name=collection_name,
        query=query_vector,
        limit=limit * 5,
        score_threshold=score_threshold,
        query_filter=query_filter,
        with_payload=True,
    )

    scored_points = query_response.points or []

    best_per_pet: dict[Any, dict[str, Any]] = {}

    for scored_point in scored_points:
        payload = scored_point.payload or {}
        pet_id = payload.get("pet_id")

        if pet_id is not None:
            pet_id = str(pet_id)

            prev = best_per_pet.get(pet_id)
            if prev is None or scored_point.score > prev["score"]:
                best_per_pet[pet_id] = {
                    "id": scored_point.id,
                    "pet_id": pet_id,
                    "score": scored_point.score,
                    "payload": payload,
                }

    return sorted(best_per_pet.values(), key=lambda x: x["score"], reverse=True)[:limit]


def update_payload(
    collection_name: str,
    point_ids: int | str | list[int | str],
    payload: dict
) -> UpdateResult:
    if not isinstance(point_ids, list):
        point_ids = [point_ids]

    return client.set_payload(
        collection_name=collection_name,
        payload=payload,
        points=point_ids
    )


def delete_embedding(collection_name: str, point_ids: int | str | list[int | str]) -> UpdateResult:
    if not isinstance(point_ids, list):
        point_ids = [point_ids]

    return client.delete(
        collection_name=collection_name,
        points_selector=PointIdsList(points=point_ids)
    )


def soft_delete_embedding(collection_name: str, point_ids: int | str | list[int | str]) -> UpdateResult:
    if not isinstance(point_ids, list):
        point_ids = [point_ids]

    return client.set_payload(
        collection_name=collection_name,
        payload={"is_deleted": True},
        points=point_ids
    )
