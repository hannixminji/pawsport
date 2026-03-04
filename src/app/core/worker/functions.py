import asyncio
import hashlib
import json
import logging

import firebase_admin
import httpx
import resend
import uvloop
from arq.worker import Worker
from qdrant_client.http.models import PointStruct

from ...core.config import settings
from ...core.db.database import async_engine, local_session
from ...core.enums import NotificationFeature
from ...core.notifications.service import notify_users_near_event_using_alert_center_radius
from ...core.utils.qdrant_cloud import delete_embedding, soft_delete_embedding, update_payload, upsert_embedding

asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")


# -------- background tasks --------
async def sample_background_task(ctx: Worker, name: str) -> str:
    await asyncio.sleep(5)
    return f"Task {name} is complete!"


async def send_email_task(
    ctx: Worker,
    *,
    to_email: str,
    subject: str,
    html: str,
) -> None:
    try:
        logging.info(f"Sending email to {to_email} (subject={subject})")

        resend.api_key = settings.RESEND_API_KEY.get_secret_value()
        resend.Emails.send({
            "from": settings.RESEND_FROM_EMAIL,
            "to": to_email,
            "subject": subject,
            "html": html,
        })

        logging.info(f"Email sent successfully to {to_email}")

    except Exception as error:
        logging.exception(f"send_email_task failed for {to_email}: {error}")
        raise


async def extract_features_task(ctx, data: list[dict], collection_name: str = "pet_photos"):
    if not data:
        logging.warning("extract_features_task called with empty data")
        return

    data_hash = hashlib.md5(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()
    job_id = f"extract_features:{data_hash}"
    logging.info(f"Starting feature extraction task: {job_id} (attempt {ctx.get('job_try')})")

    timeout = httpx.Timeout(connect=60.0, write=120.0, read=900.0, pool=None)

    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            payload = json.dumps(
                [{"id": str(item["id"]), "object_key": item["object_key"]} for item in data]
            )

            species_raw = data[0].get("payload", {}).get("species")
            if species_raw is None:
                raise KeyError("payload.species is missing")

            if hasattr(species_raw, "value"):
                species_raw = species_raw.value
            species = str(species_raw).lower().strip()

            response = await client.post(
                f"{settings.ML_BASE_URL}/extract_features",
                data={"species": species, "image_object_keys": payload},
            )
            response.raise_for_status()

            embeddings_data = response.json()
            if not embeddings_data:
                logging.warning(f"No valid embeddings returned for job {job_id}")
                return

            by_id = {str(item["id"]): item for item in data}
            points = []

            for embedding_item in embeddings_data:
                embedding_id = str(embedding_item["id"])
                original_item = by_id.get(embedding_id)
                if original_item:
                    points.append(
                        PointStruct(
                            id=embedding_id,
                            vector=embedding_item["embedding"],
                            payload=original_item.get("payload"),
                        )
                    )

            upsert_embedding(collection_name, points)
            logging.info(f"Upserted {len(points)} embeddings into Qdrant for job {job_id}")

        except httpx.RequestError as error:
            logging.error(f"Connection failed while contacting ML service: {error}")
        except httpx.HTTPStatusError as error:
            logging.error(f"ML service returned {error.response.status_code}: {error.response.text}")
        except Exception as error:
            logging.error(f"Unexpected error during feature extraction: {error}")


async def notify_nearby_alert_center_task(
    worker_context: Worker,
    *,
    event_longitude: float,
    event_latitude: float,
    notification_title: str,
    notification_body: str,
    notification_data: dict[str, str],
    notification_feature: NotificationFeature = NotificationFeature.NEARBY_REPORT_ALERTS,
    radius_in_meters: int = 3_000,
    excluded_user_id: int | None = None,
) -> None:
    database_sessionmaker = worker_context["database_sessionmaker"]

    if isinstance(notification_feature, str):
        notification_feature = NotificationFeature(notification_feature)

    try:
        logging.info(
            "Starting notify_nearby_alert_center_task "
            f"(event_longitude={event_longitude}, event_latitude={event_latitude}, "
            f"notification_feature={notification_feature.value}, radius_in_meters={radius_in_meters}, "
            f"excluded_user_id={excluded_user_id})"
        )

        async with database_sessionmaker() as database_session:
            await notify_users_near_event_using_alert_center_radius(
                database_session,
                event_longitude=event_longitude,
                event_latitude=event_latitude,
                notification_title=notification_title,
                notification_body=notification_body,
                notification_data=notification_data,
                notification_feature=notification_feature,
                radius_in_meters=radius_in_meters,
                excluded_user_id=excluded_user_id,
            )
            await database_session.commit()

        logging.info(
            "Finished notify_nearby_alert_center_task "
            f"(event_longitude={event_longitude}, event_latitude={event_latitude}, "
            f"notification_feature={notification_feature.value}, radius_in_meters={radius_in_meters}, "
            f"excluded_user_id={excluded_user_id})"
        )

    except Exception as error:
        logging.exception(f"notify_nearby_alert_center_task failed: {error}")
        raise


async def qdrant_update_payload_task(
    collection_name: str,
    point_ids: list[str],
    payload: dict,
) -> None:
    try:
        update_payload(collection_name, point_ids, payload)

    except Exception as error:
        logging.error(f"Qdrant payload update failed for {collection_name}: {error}")
        raise


async def qdrant_soft_delete_embeddings_task(
    collection_name: str,
    point_ids: list[str],
) -> None:
    try:
        soft_delete_embedding(collection_name, point_ids)

    except Exception as error:
        logging.error(f"Qdrant soft delete failed for collection {collection_name}: {error}")
        raise


async def qdrant_hard_delete_embeddings_task(
    collection_name: str,
    point_ids: list[str],
) -> None:
    try:
        delete_embedding(collection_name, point_ids)

    except Exception as error:
        logging.error(f"Qdrant hard delete failed for collection {collection_name}: {error}")
        raise


async def startup(ctx: Worker) -> None:
    if not firebase_admin._apps:
        firebase_admin.initialize_app()

    ctx["database_engine"] = async_engine
    ctx["database_sessionmaker"] = local_session

    logging.info("Worker Started")


async def shutdown(ctx: Worker) -> None:
    database_engine = ctx.get("database_engine")
    if database_engine is not None:
        await database_engine.dispose()

    logging.info("Worker end")
