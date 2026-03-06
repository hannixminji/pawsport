def extract_changed_fields(
    before_snapshot: dict,
    after_snapshot: dict,
) -> tuple[dict, dict]:
    changed_field_keys = {
        field_key
        for field_key in after_snapshot
        if before_snapshot.get(field_key) != after_snapshot.get(field_key)
    }
    return (
        {field_key: before_snapshot[field_key] for field_key in changed_field_keys if field_key in before_snapshot},
        {field_key: after_snapshot[field_key] for field_key in changed_field_keys if field_key in after_snapshot},
    )
