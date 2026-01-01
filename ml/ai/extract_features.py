import albumentations as A
import numpy as np
import onnxruntime as ort

transform = A.Compose([
    A.Resize(height=384, width=384),
    A.Normalize(mean=(0.5, 0.5, 0.5), std=(0.5, 0.5, 0.5)),
])

session = ort.InferenceSession("ai/models/megadescriptorL384.onnx", providers=["CPUExecutionProvider"])
input_name = session.get_inputs()[0].name


def extract_features(images: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    processed_images = []

    for image in images.values():
        transformed = transform(image=image)["image"]
        chw_image = np.transpose(transformed, (2, 0, 1))
        processed_images.append(chw_image)

    tensors = np.stack(processed_images, axis=0).astype(np.float32)
    outputs = session.run(None, {input_name: tensors})[0]
    return dict(zip(images.keys(), outputs))
