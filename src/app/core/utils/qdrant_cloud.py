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
        "type": PayloadSchemaType.KEYWORD,
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
    query_filter: Filter = None
) -> list[dict[str, Any]]:
    search_results = client.query_points(
        collection_name=collection_name,
        query_vector=query_vector,
        limit=limit * 5,
        score_threshold=score_threshold,
        query_filter=query_filter
    )

    best_per_pet = {}

    for result in search_results:
        pet_id = result.payload.get("pet_id")

        if pet_id and (
            pet_id not in best_per_pet
            or result.score > best_per_pet[pet_id]["score"]
        ):
            best_per_pet[pet_id] = {
                "id": result.id,
                "pet_id": pet_id,
                "score": result.score,
                "payload": result.payload,
            }

    unique_results = sorted(best_per_pet.values(), key=lambda x: x["score"], reverse=True)
    return unique_results[:limit]


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
