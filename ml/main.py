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
    image_object_keys: str | None = Form(None),
    files: list[UploadFile] | None = File(None)
) -> list[dict[str, Any]]:
    images: dict[str, np.ndarray] = {}

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

    detection_results = detect(images)

    detect_processed: dict[str, np.ndarray] = {}
    for image_id, detection_result in detection_results.items():
        image = images.get(image_id)
        boxes = detection_result["boxes"]

        if image is not None and len(boxes) == 1:
            cropped_image = crop_objects(image, boxes)[0]
            detect_processed[image_id] = cropped_image

    if not detect_processed:
        return []

    pose_results = detect_pose(detect_processed)

    aligned_processed: dict[str, np.ndarray] = {}
    for image_id, keypoints in pose_results.items():
        if keypoints.size > 0:
            aligned_image = align_eyes(detect_processed[image_id], keypoints)
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
        return {"message": "Hmm... that doesn’t look like a valid image."}

    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    images = {"0": img_rgb}

    detection_results = detect(images)

    detect_processed: dict[str, np.ndarray] = {}
    for image_id, detection_result in detection_results.items():
        image = images.get(image_id)
        boxes = detection_result["boxes"]

        if len(boxes) == 0:
            return {"message": "No cat detected in the image — try another one?"}

        if len(boxes) > 1:
            return {"message": "Multiple cats detected! Please upload one cat at a time."}

        cropped_image = crop_objects(image, boxes)[0]
        detect_processed[image_id] = cropped_image

    if not detect_processed:
        return {"message": "No valid detection found."}

    pose_results = detect_pose(detect_processed)

    aligned_processed: dict[str, np.ndarray] = {}
    for image_id, keypoints in pose_results.items():
        if keypoints.size > 0:
            aligned_image = align_eyes(detect_processed[image_id], keypoints)
            aligned_processed[image_id] = aligned_image

    if not aligned_processed:
        return {"message": "Couldn’t align the cat’s pose properly."}

    embeddings = extract_features(aligned_processed)

    embedding = list(embeddings.values())[0].tolist()

    return {"message": "Cat detected successfully!", "embedding": embedding}


@app.post("/detect_cat")
async def detect_cat(
    image_object_keys: str | None = Form(None),
    files: list[UploadFile] | None = File(None)
) -> list[dict[str, Any]]:
    images: dict[str, np.ndarray] = {}

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

    detection_results = detect(images)

    results = [
        {"id": image_id, "count": len(result["boxes"])}
        for image_id, result in detection_results.items()
    ]

    return results
