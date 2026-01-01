import cv2
import numpy as np
from google.cloud import storage

storage_client = storage.Client()


def load_images(bucket_name: str, blob_names: dict[int, str]) -> dict[int, np.ndarray]:
    bucket = storage_client.bucket(bucket_name)
    images = {}

    for image_id, blob_name in blob_names.items():
        try:
            blob = bucket.blob(blob_name)
            content = blob.download_as_bytes()
            np_arr = np.frombuffer(content, np.uint8)
            img_bgr = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if img_bgr is not None:
                img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
                images[image_id] = img_rgb
        except Exception:
            pass

    return images
