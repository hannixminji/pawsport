import cv2
import numpy as np
import onnxruntime as ort

session = ort.InferenceSession("ai/models/yolov8sbboxcat640.onnx", providers=["CPUExecutionProvider"])
input_name = session.get_inputs()[0].name


def detect(images: dict[str, np.ndarray],
           conf_threshold: float = 0.50,
           iou_threshold: float = 0.45,
           input_size: tuple[int, int] = (640, 640)) -> dict[str, dict[str, np.ndarray]]:
    results = {}
    for image_id, img in images.items():
        img_height, img_width = img.shape[:2]
        input_tensor, scale, pad_w, pad_h = preprocess_image(img, input_size)
        outputs = session.run(None, {input_name: input_tensor})[0]
        detections = postprocess_boxes(
            outputs, img_width, img_height, scale, pad_w, pad_h,
            conf_threshold, iou_threshold
        )
        results[image_id] = detections
    return results


def preprocess_image(img: np.ndarray, input_size: tuple[int, int]) -> tuple[np.ndarray, float, int, int]:
    img_height, img_width = img.shape[:2]
    target_w, target_h = input_size
    scale = min(target_w / img_width, target_h / img_height)
    new_w = int(img_width * scale)
    new_h = int(img_height * scale)
    resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    pad_w = (target_w - new_w) // 2
    pad_h = (target_h - new_h) // 2
    padded = np.full((target_h, target_w, 3), 114, dtype=np.uint8)
    padded[pad_h:pad_h + new_h, pad_w:pad_w + new_w] = resized
    input_tensor = padded.transpose(2, 0, 1).astype(np.float32) / 255.0
    input_tensor = np.expand_dims(input_tensor, axis=0)
    return input_tensor, scale, pad_w, pad_h


def postprocess_boxes(outputs: np.ndarray,
                      img_width: int,
                      img_height: int,
                      scale: float,
                      pad_w: int,
                      pad_h: int,
                      conf_threshold: float,
                      iou_threshold: float) -> dict:
    preds = outputs
    if preds.ndim == 3:
        preds = preds[0]
    if preds.shape[0] == 5:
        preds = preds.transpose(1, 0)
    boxes = preds[:, :4]
    scores = preds[:, 4]
    mask = scores > conf_threshold
    boxes = boxes[mask]
    scores = scores[mask]
    if len(boxes) == 0:
        return {'boxes': np.array([]), 'scores': np.array([])}
    boxes_xyxy = np.column_stack([
        boxes[:, 0] - boxes[:, 2] / 2,
        boxes[:, 1] - boxes[:, 3] / 2,
        boxes[:, 0] + boxes[:, 2] / 2,
        boxes[:, 1] + boxes[:, 3] / 2
    ])
    keep_indices = nms(boxes_xyxy, scores, iou_threshold)
    boxes_xyxy = boxes_xyxy[keep_indices]
    scores = scores[keep_indices]
    boxes_xyxy[:, [0, 2]] = (boxes_xyxy[:, [0, 2]] - pad_w) / scale
    boxes_xyxy[:, [1, 3]] = (boxes_xyxy[:, [1, 3]] - pad_h) / scale
    boxes_xyxy[:, [0, 2]] = np.clip(boxes_xyxy[:, [0, 2]], 0, img_width)
    boxes_xyxy[:, [1, 3]] = np.clip(boxes_xyxy[:, [1, 3]], 0, img_height)
    return {'boxes': boxes_xyxy, 'scores': scores}


def nms(boxes: np.ndarray, scores: np.ndarray, iou_threshold: float) -> list[int]:
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = (x2 - x1) * (y2 - y1)
    order = scores.argsort()[::-1]
    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(i)
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        w = np.maximum(0.0, xx2 - xx1)
        h = np.maximum(0.0, yy2 - yy1)
        inter = w * h
        iou = inter / (areas[i] + areas[order[1:]] - inter)
        inds = np.nonzero(iou <= iou_threshold)[0]
        order = order[inds + 1]
    return keep


def crop_objects(image: np.ndarray, boxes: np.ndarray) -> list[np.ndarray]:
    cropped = []
    for box in boxes:
        x1, y1, x2, y2 = map(int, box)
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(image.shape[1], x2), min(image.shape[0], y2)
        crop = image[y1:y2, x1:x2]
        if crop.size > 0:
            cropped.append(crop)
    return cropped
