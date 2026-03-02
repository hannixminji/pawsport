import os

ALLOWED_IMAGE_EXTENSIONS = frozenset({"jpg", "jpeg", "png"})
ALLOWED_ATTACHMENT_EXTENSIONS = frozenset({"jpg", "jpeg", "png", "pdf"})


def validate_object_key_extension(object_key: str, allowed: frozenset[str]) -> str:
    extension = os.path.splitext(object_key)[1].lower().lstrip(".")

    if not extension:
        raise ValueError("Invalid file — must have a valid extension.")

    if extension not in allowed:
        supported = ", ".join(sorted(allowed)).upper()
        raise ValueError(f"Invalid file type. Only {supported} files are allowed.")

    return object_key
