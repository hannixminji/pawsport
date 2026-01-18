import json
from typing import Any

import cv2
import numpy as np
from ai.detect import crop_objects, detect
from ai.extract_features import extract_features
from ai.pose import align_eyes, detect_pose
from fastapi import FastAPI, File, Form, UploadFile
from google_cloud_storage import load_images

app = FastAPI()


@app.post("/extract_features")
async def create_embedding(
    species: str = Form(...),
    image_object_keys: str | None = Form(None),
    files: list[UploadFile] | None = File(None)
) -> list[dict[str, Any]]:
    images: dict[str, np.ndarray] = {}

    species = species.lower().strip()
    if species not in {"cat", "dog"}:
        raise ValueError("species must be 'cat' or 'dog'")

    if image_object_keys:
        items = {str(item["id"]): item["image_object_key"] for item in json.loads(image_object_keys)}
        images.update(load_images("pawsport", items))

    elif files:
        for index, file in enumerate(files):
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
            aligned_image = align_eyes(
                detect_processed[image_id],
                keypoints,
                species=species
            )
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
async def search_pet(file: UploadFile) -> dict[str, Any]:
    content = await file.read()
    np_arr = np.frombuffer(content, np.uint8)
    img_bgr = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

    if img_bgr is None:
        return {"message": "Hmm... that doesn't look like a valid image."}

    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    images = {"0": img_rgb}

    cat_results = detect(images, species="cat")
    dog_results = detect(images, species="dog")

    cat_boxes = cat_results.get("0", {}).get("boxes", [])
    dog_boxes = dog_results.get("0", {}).get("boxes", [])

    cat_confidence = cat_results.get("0", {}).get("scores", [0])[0] if len(cat_boxes) > 0 else 0
    dog_confidence = dog_results.get("0", {}).get("scores", [0])[0] if len(dog_boxes) > 0 else 0

    if cat_confidence <= 0.5 and dog_confidence <= 0.5:
        return {"message": "No cat or dog detected in the image - try another one?"}

    if cat_confidence >= dog_confidence:
        detection_results = cat_results
        detected_species = "cat"
        confidence = cat_confidence
    else:
        detection_results = dog_results
        detected_species = "dog"
        confidence = dog_confidence

    detect_processed: dict[str, np.ndarray] = {}
    for image_id, detection_result in detection_results.items():
        image = images.get(image_id)
        boxes = detection_result["boxes"]

        if len(boxes) == 0:
            return {"message": f"No {detected_species} detected in the image - try another one?"}

        if len(boxes) > 1:
            return {"message": f"Multiple {detected_species}s detected! Please upload one pet at a time."}

        cropped_image = crop_objects(image, boxes)[0]
        detect_processed[image_id] = cropped_image

    if not detect_processed:
        return {"message": "No valid detection found."}

    pose_results = detect_pose(detect_processed, species=detected_species)

    aligned_processed: dict[str, np.ndarray] = {}
    for image_id, keypoints in pose_results.items():
        if keypoints.size > 0:
            aligned_image = align_eyes(detect_processed[image_id], keypoints)
            aligned_processed[image_id] = aligned_image

    if not aligned_processed:
        return {"message": f"Couldn't align the {detected_species}'s face properly."}

    embeddings = extract_features(aligned_processed)

    embedding = list(embeddings.values())[0].tolist()

    return {
        "message": f"{detected_species.capitalize()} detected successfully!",
        "embedding": embedding,
        "species": detected_species,
        "confidence": float(confidence),
    }
