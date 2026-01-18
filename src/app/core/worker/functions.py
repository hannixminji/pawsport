import asyncio
import hashlib
import json
import logging

import httpx
import uvloop
from arq.worker import Worker
from qdrant_client.http.models import PointStruct

from ...core.utils.qdrant_cloud import upsert_embedding

asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")


# -------- background tasks --------
async def sample_background_task(ctx: Worker, name: str) -> str:
    await asyncio.sleep(5)
    return f"Task {name} is complete!"


async def extract_features_task(ctx, data: list[dict], collection_name: str = "pet_profile_images"):
    data_hash = hashlib.md5(json.dumps(data, sort_keys=True).encode()).hexdigest()
    job_id = f"extract_features:{data_hash}"
    logging.info(f"🚀 Starting feature extraction task: {job_id} (attempt {ctx['job_try']})")

    timeout = httpx.Timeout(
        connect=60.0,
        write=120.0,
        read=900.0,
        pool=None,
    )

    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            payload = json.dumps([
                {"id": str(item["id"]), "image_object_key": item["image_object_key"]}
                for item in data
            ])

            species = data[0]["payload"]["pet_type"].lower().strip()

            response = await client.post(
                "http://ml:9000/extract_features",
                data={
                    "species": species,
                    "image_object_keys": payload,
                },
            )
            response.raise_for_status()

            embeddings_data = response.json()
            if not embeddings_data:
                logging.warning(f"⚠️ No valid embeddings returned for job {job_id}")
                return

            points = []
            for embedding_item in embeddings_data:
                embedding_id = str(embedding_item["id"])
                original_item = next((item for item in data if str(item["id"]) == embedding_id), None)
                if original_item:
                    points.append(PointStruct(
                        id=embedding_id,
                        vector=embedding_item["embedding"],
                        payload=original_item.get("payload")
                    ))

            upsert_embedding(collection_name, points)
            logging.info(f"✅ Upserted {len(points)} embeddings into Qdrant for job {job_id}")

        except httpx.RequestError as error:
            logging.error(f"❌ Connection failed while contacting ML service: {error}")

        except httpx.HTTPStatusError as error:
            logging.error(f"❌ ML service returned {error.response.status_code}: {error.response.text}")

        except Exception as error:
            logging.error(f"❌ Unexpected error during feature extraction: {error}")


# -------- base functions --------
async def startup(ctx: Worker) -> None:
    logging.info("Worker Started")


async def shutdown(ctx: Worker) -> None:
    logging.info("Worker end")
