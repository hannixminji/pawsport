import cv2
import numpy as np
import onnxruntime as ort

_CAT_POSE_MODEL = "ai/models/yolov8sposecat640.onnx"
_DOG_POSE_MODEL = "ai/models/yolov8sposedog640.onnx"

_CAT_POSE_SESSION = ort.InferenceSession(_CAT_POSE_MODEL, providers=["CPUExecutionProvider"])
_DOG_POSE_SESSION = ort.InferenceSession(_DOG_POSE_MODEL, providers=["CPUExecutionProvider"])

_CAT_POSE_INPUT = _CAT_POSE_SESSION.get_inputs()[0].name
_DOG_POSE_INPUT = _DOG_POSE_SESSION.get_inputs()[0].name


def preprocess_image(img: np.ndarray, input_size: tuple[int, int]) -> tuple[np.ndarray, float, int, int]:
    h, w = img.shape[:2]
    tw, th = input_size
    scale = min(tw / w, th / h)
    nw, nh = int(w * scale), int(h * scale)
    resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
    pad_w = (tw - nw) // 2
    pad_h = (th - nh) // 2
    padded = np.full((th, tw, 3), 114, dtype=np.uint8)
    padded[pad_h:pad_h + nh, pad_w:pad_w + nw] = resized
    tensor = padded.transpose(2, 0, 1).astype(np.float32) / 255.0
    tensor = np.expand_dims(tensor, axis=0)
    return tensor, scale, pad_w, pad_h


def postprocess_keypoints(
    outputs: list[np.ndarray],
    img_w: int,
    img_h: int,
    scale: float,
    pad_w: int,
    pad_h: int,
    conf_threshold: float = 0.25,
) -> np.ndarray:
    preds = outputs[0]
    if preds.ndim == 3:
        preds = preds[0]
    if preds.shape[0] < preds.shape[1]:
        preds = preds.transpose(1, 0)

    confs = preds[:, 4]
    mask = confs > conf_threshold
    preds = preds[mask]

    if preds.shape[0] == 0:
        return np.empty((0, 3))

    best = preds[np.argmax(preds[:, 4])]
    kpts = best[5:].reshape(5, 3)

    kpts[:, 0] = (kpts[:, 0] - pad_w) / scale
    kpts[:, 1] = (kpts[:, 1] - pad_h) / scale

    kpts[:, 0] = np.clip(kpts[:, 0], 0, img_w - 1)
    kpts[:, 1] = np.clip(kpts[:, 1], 0, img_h - 1)

    return kpts


def detect_pose(
    images: dict[str, np.ndarray],
    species: str = "cat",
    conf_threshold: float = 0.25,
    input_size: tuple[int, int] = (640, 640),
) -> dict[str, np.ndarray]:
    species = species.lower().strip()
    if species not in {"cat", "dog"}:
        raise ValueError("species must be 'cat' or 'dog'")

    session = _CAT_POSE_SESSION if species == "cat" else _DOG_POSE_SESSION
    input_name = _CAT_POSE_INPUT if species == "cat" else _DOG_POSE_INPUT

    results: dict[str, np.ndarray] = {}
    for image_id, img in images.items():
        h, w = img.shape[:2]
        tensor, scale, pad_w, pad_h = preprocess_image(img, input_size)
        outputs = session.run(None, {input_name: tensor})
        keypoints = postprocess_keypoints(outputs, w, h, scale, pad_w, pad_h, conf_threshold)
        results[image_id] = keypoints
    return results


def align_eyes(img: np.ndarray, keypoints: np.ndarray, species: str = "cat") -> np.ndarray:
    if keypoints.shape[0] < 2:
        return img

    species = species.lower().strip()

    if species == "dog":
        left_eye = keypoints[0, :2]
        right_eye = keypoints[1, :2]
        left_c = keypoints[0, 2]
        right_c = keypoints[1, 2]
    else:
        right_eye = keypoints[0, :2]
        left_eye = keypoints[1, :2]
        right_c = keypoints[0, 2]
        left_c = keypoints[1, 2]

    if left_c < 0.5 or right_c < 0.5:
        return img

    dx = left_eye[0] - right_eye[0]
    dy = left_eye[1] - right_eye[1]
    angle = np.degrees(np.arctan2(dy, dx))
    eye_center = ((right_eye[0] + left_eye[0]) / 2, (right_eye[1] + left_eye[1]) / 2)

    h, w = img.shape[:2]
    rotation_matrix = cv2.getRotationMatrix2D(eye_center, angle, 1.0)

    corners = np.array([[0, 0], [w, 0], [w, h], [0, h]], dtype=np.float32)
    corners = np.hstack([corners, np.ones((4, 1), dtype=np.float32)])
    rotated_corners = rotation_matrix @ corners.T
    x_coords, y_coords = rotated_corners[0, :], rotated_corners[1, :]

    x_min, x_max = np.min(x_coords), np.max(x_coords)
    y_min, y_max = np.min(y_coords), np.max(y_coords)

    pad_left, pad_top = int(max(0, -x_min)), int(max(0, -y_min))
    pad_right, pad_bottom = int(max(0, x_max - w)), int(max(0, y_max - h))

    img_padded = cv2.copyMakeBorder(
        img, pad_top, pad_bottom, pad_left, pad_right,
        borderType=cv2.BORDER_CONSTANT, value=(114, 114, 114)
    )

    eye_center = (eye_center[0] + pad_left, eye_center[1] + pad_top)
    rotation_matrix = cv2.getRotationMatrix2D(eye_center, angle, 1.0)
    rotated = cv2.warpAffine(
        img_padded, rotation_matrix,
        (img_padded.shape[1], img_padded.shape[0]),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT, borderValue=(114, 114, 114)
    )
    return rotated
