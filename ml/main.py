import json
from typing import Any

import cv2
import numpy as np
from ai.detect import crop_objects, detect
from ai.extract_features import extract_features
from ai.pose import align_eyes, detect_pose
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from google_cloud_storage import load_images

app = FastAPI()


@app.post("/extract_features")
async def create_embedding(
    species: str = Form(...),
    image_object_keys: str | None = Form(None),
    files: list[UploadFile] | None = File(None),
) -> list[dict[str, Any]]:
    species = species.lower().strip()
    if species not in {"cat", "dog"}:
        raise HTTPException(status_code=400, detail="species must be 'cat' or 'dog'")

    if (image_object_keys is None and not files) or (image_object_keys is not None and files):
        raise HTTPException(
            status_code=400,
            detail="Provide exactly one: image_object_keys or files",
        )

    images: dict[str, np.ndarray] = {}

    if image_object_keys is not None:
        items = {str(item["id"]): item["image_object_key"] for item in json.loads(image_object_keys)}
        images.update(load_images("pawsport", items))
    else:
        for index, file in enumerate(files or []):
            content = await file.read()
            np_arr = np.frombuffer(content, np.uint8)
            img_bgr = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if img_bgr is not None:
                img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
                images[str(index)] = img_rgb

    if not images:
        return []

    detection_results = detect(images, species=species)

    detect_processed: dict[str, np.ndarray] = {}
    for image_id, detection_result in detection_results.items():
        image = images.get(image_id)
        boxes = detection_result["boxes"]

        if image is not None and len(boxes) == 1:
            cropped_image = crop_objects(image, boxes)[0]
            detect_processed[image_id] = cropped_image

    if not detect_processed:
        return []

    pose_results = detect_pose(detect_processed, species=species)

    aligned_processed: dict[str, np.ndarray] = {}
    for image_id, keypoints in pose_results.items():
        if keypoints.size > 0:
            aligned_image = align_eyes(detect_processed[image_id], keypoints, species=species)
            aligned_processed[image_id] = aligned_image

    if not aligned_processed:
        return []

    embeddings = extract_features(aligned_processed)

    results = [
        {"id": image_id, "embedding": embedding.tolist()}
        for image_id, embedding in embeddings.items()
    ]

    return results


@app.post("/search_pet")
async def search_pet(
    file: UploadFile = File(...),
    species: str = Form(...),
) -> dict[str, Any]:
    species = species.lower().strip()
    if species not in {"cat", "dog"}:
        return {"message": "species must be 'cat' or 'dog'."}

    content = await file.read()
    np_arr = np.frombuffer(content, np.uint8)
    img_bgr = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

    if img_bgr is None:
        return {"message": "Hmm... that doesn't look like a valid image."}

    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    images = {"0": img_rgb}

    detection_results = detect(images, species=species)

    boxes = detection_results.get("0", {}).get("boxes", [])
    scores = detection_results.get("0", {}).get("scores", [])
    confidence = float(scores[0]) if len(boxes) > 0 and len(scores) > 0 else 0.0

    if confidence <= 0.5:
        return {"message": f"No {species} detected in the image - try another one?"}

    detect_processed: dict[str, np.ndarray] = {}
    for image_id, detection_result in detection_results.items():
        image = images.get(image_id)
        boxes = detection_result["boxes"]

        if len(boxes) == 0:
            return {"message": f"No {species} detected in the image - try another one?"}

        if len(boxes) > 1:
            return {"message": f"Multiple {species}s detected! Please upload one pet at a time."}

        cropped_image = crop_objects(image, boxes)[0]
        detect_processed[image_id] = cropped_image

    if not detect_processed:
        return {"message": "No valid detection found."}

    pose_results = detect_pose(detect_processed, species=species)

    aligned_processed: dict[str, np.ndarray] = {}
    for image_id, keypoints in pose_results.items():
        if keypoints.size > 0:
            aligned_image = align_eyes(detect_processed[image_id], keypoints, species=species)
            aligned_processed[image_id] = aligned_image

    if not aligned_processed:
        return {"message": f"Couldn't align the {species}'s face properly."}

    embeddings = extract_features(aligned_processed)
    embedding = list(embeddings.values())[0].tolist()

    return {
        "message": f"{species.capitalize()} detected successfully!",
        "embedding": embedding,
        "species": species,
        "confidence": float(confidence),
    }
