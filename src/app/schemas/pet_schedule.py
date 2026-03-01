import re
from datetime import datetime
from typing import Annotated

from dateutil.rrule import rrulestr
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..core.enums import PetScheduleType
from ..core.schemas import PersistentDeletion, TimestampSchema

_ALLOWED_KEYS = {
    "FREQ",
    "INTERVAL",
    "WKST",
    "COUNT",
    "UNTIL",
    "BYSETPOS",
    "BYMONTH",
    "BYMONTHDAY",
    "BYYEARDAY",
    "BYWEEKNO",
    "BYDAY",
}

_ALLOWED_FREQ = {"DAILY", "WEEKLY", "MONTHLY", "YEARLY"}
_ALLOWED_DAYS = {"MO", "TU", "WE", "TH", "FR", "SA", "SU"}

_INT_RE = re.compile(r"^\d+$")
_SIGNED_INT_RE = re.compile(r"^[+-]?\d+$")
_UNTIL_RE = re.compile(r"^\d{8}T\d{6}Z?$")
_BYDAY_ITEM_RE = re.compile(r"^([+-]?\d{1,2})?(MO|TU|WE|TH|FR|SA|SU)$", re.IGNORECASE)


def _parse_rrule_kv(v: str) -> dict[str, str]:
    parts = v.split(";")
    kv: dict[str, str] = {}
    for part in parts:
        if not part or "=" not in part:
            raise ValueError("recurrence_rule must be key=value pairs separated by ';'")
        k, val = part.split("=", 1)
        k = k.strip().upper()
        val = val.strip()
        if not k or not val:
            raise ValueError("recurrence_rule must be key=value pairs separated by ';'")
        if k in kv:
            raise ValueError(f"recurrence_rule must not contain duplicate '{k}'")
        kv[k] = val
    return kv


def _parse_int_in_range(name: str, raw: str, min_v: int, max_v: int) -> int:
    if not _INT_RE.match(raw):
        raise ValueError(f"recurrence_rule {name} must be an integer")
    n = int(raw)
    if n < min_v or n > max_v:
        raise ValueError(f"recurrence_rule {name} must be between {min_v} and {max_v}")
    return n


def _parse_signed_int_in_range_excluding_zero(name: str, raw: str, min_v: int, max_v: int) -> int:
    if not _SIGNED_INT_RE.match(raw):
        raise ValueError(f"recurrence_rule {name} must be a valid integer")
    n = int(raw)
    if n == 0:
        raise ValueError(f"recurrence_rule {name} must not be 0")
    if n < min_v or n > max_v:
        raise ValueError(f"recurrence_rule {name} must be between {min_v} and {max_v} (excluding 0)")
    return n


def _require_single_value(name: str, raw: str) -> None:
    if "," in raw:
        raise ValueError(f"recurrence_rule {name} must be a single value (no commas)")


def _validate_byday(raw: str, *, allow_list: bool, allow_ordinals: bool) -> list[str]:
    parts = raw.split(",")
    if not allow_list and len(parts) != 1:
        raise ValueError("recurrence_rule BYDAY must be a single weekday for this FREQ")

    out: list[str] = []
    for p in parts:
        m = _BYDAY_ITEM_RE.match(p)
        if not m:
            raise ValueError("recurrence_rule BYDAY must be one or more of: MO, TU, WE, TH, FR, SA, SU")
        ord_str, day = m.group(1), m.group(2).upper()

        if day not in _ALLOWED_DAYS:
            raise ValueError("recurrence_rule BYDAY must be one or more of: MO, TU, WE, TH, FR, SA, SU")

        if ord_str is not None:
            if not allow_ordinals:
                raise ValueError("recurrence_rule BYDAY must not include ordinals for this FREQ")
            ord_n = int(ord_str)
            if ord_n == 0:
                raise ValueError("recurrence_rule BYDAY ordinal must not be 0")
            if ord_n < -53 or ord_n > 53:
                raise ValueError("recurrence_rule BYDAY ordinal must be between -53 and 53 (excluding 0)")
            out.append(f"{ord_n}{day}")
        else:
            out.append(day)

    if len(set(out)) != len(out):
        raise ValueError("recurrence_rule BYDAY must not contain duplicates")
    return out


def _validate_rrule_allowed_subset(v: str) -> str:  # noqa: C901
    v_upper = v.upper()

    if any(ch.isspace() for ch in v):
        raise ValueError("recurrence_rule must not contain whitespace")
    if v_upper.startswith("RRULE:"):
        raise ValueError("recurrence_rule must not include 'RRULE:' prefix")
    if "DTSTART" in v_upper:
        raise ValueError("recurrence_rule must not include DTSTART")

    kv = _parse_rrule_kv(v)

    unknown = set(kv.keys()) - _ALLOWED_KEYS
    if unknown:
        raise ValueError(f"recurrence_rule contains unsupported keys: {', '.join(sorted(unknown))}")

    if "FREQ" not in kv:
        raise ValueError("recurrence_rule must include FREQ")
    freq = kv["FREQ"].upper()
    if freq not in _ALLOWED_FREQ:
        raise ValueError("recurrence_rule FREQ must be one of: DAILY, WEEKLY, MONTHLY, YEARLY")

    if "INTERVAL" not in kv:
        raise ValueError("recurrence_rule must include INTERVAL")
    _parse_int_in_range("INTERVAL", kv["INTERVAL"], 1, 999)

    has_count = "COUNT" in kv
    has_until = "UNTIL" in kv
    if has_count and has_until:
        raise ValueError("recurrence_rule must not include both COUNT and UNTIL")
    if has_count:
        _parse_int_in_range("COUNT", kv["COUNT"], 1, 9999)
    if has_until:
        until = kv["UNTIL"].upper()
        if not _UNTIL_RE.match(until):
            raise ValueError("recurrence_rule UNTIL must be in format YYYYMMDDTHHMMSS or YYYYMMDDTHHMMSSZ")

    if "WKST" in kv:
        wkst = kv["WKST"].upper()
        if wkst not in _ALLOWED_DAYS:
            raise ValueError("recurrence_rule WKST must be one of: MO, TU, WE, TH, FR, SA, SU")

    if "BYMONTH" in kv:
        _require_single_value("BYMONTH", kv["BYMONTH"])
        _parse_int_in_range("BYMONTH", kv["BYMONTH"], 1, 12)

    if "BYMONTHDAY" in kv:
        _require_single_value("BYMONTHDAY", kv["BYMONTHDAY"])
        _parse_signed_int_in_range_excluding_zero("BYMONTHDAY", kv["BYMONTHDAY"], -31, 31)

    if "BYYEARDAY" in kv:
        _require_single_value("BYYEARDAY", kv["BYYEARDAY"])
        _parse_signed_int_in_range_excluding_zero("BYYEARDAY", kv["BYYEARDAY"], -366, 366)

    if "BYWEEKNO" in kv:
        _require_single_value("BYWEEKNO", kv["BYWEEKNO"])
        _parse_signed_int_in_range_excluding_zero("BYWEEKNO", kv["BYWEEKNO"], -53, 53)

    if "BYSETPOS" in kv:
        _require_single_value("BYSETPOS", kv["BYSETPOS"])
        _parse_signed_int_in_range_excluding_zero("BYSETPOS", kv["BYSETPOS"], -5, 5)

    keys = set(kv.keys())
    by_keys = {"BYMONTH", "BYMONTHDAY", "BYYEARDAY", "BYWEEKNO", "BYDAY", "BYSETPOS"}
    present_by = {k for k in by_keys if k in keys}

    if freq == "DAILY":
        banned = present_by | ({"WKST"} if "WKST" in keys else set())
        if banned:
            raise ValueError("recurrence_rule for DAILY must not include WKST or any BY* rules")

    elif freq == "WEEKLY":
        if "BYDAY" not in kv:
            raise ValueError("recurrence_rule for WEEKLY must include BYDAY")
        _validate_byday(kv["BYDAY"], allow_list=True, allow_ordinals=False)

        banned = present_by - {"BYDAY"}
        if banned:
            raise ValueError(
                "recurrence_rule for WEEKLY must not include BYMONTH, BYMONTHDAY, BYYEARDAY, BYWEEKNO, or BYSETPOS"
            )

        if "WKST" in kv:
            pass

    elif freq == "MONTHLY":
        if "WKST" in kv:
            raise ValueError("recurrence_rule for MONTHLY must not include WKST")
        if "BYMONTH" in kv or "BYWEEKNO" in kv or "BYYEARDAY" in kv:
            raise ValueError("recurrence_rule for MONTHLY must not include BYMONTH, BYWEEKNO, or BYYEARDAY")

        has_bymonthday = "BYMONTHDAY" in kv
        has_byday = "BYDAY" in kv
        has_bysetpos = "BYSETPOS" in kv

        if has_bymonthday:
            if has_byday or has_bysetpos:
                raise ValueError("recurrence_rule MONTHLY must use BYMONTHDAY or (BYDAY+BYSETPOS), not both")
        else:
            if not (has_byday and has_bysetpos):
                raise ValueError("recurrence_rule MONTHLY must include BYMONTHDAY or both BYDAY and BYSETPOS")
            _validate_byday(kv["BYDAY"], allow_list=False, allow_ordinals=False)

    else:  # YEARLY
        has_bymonth = "BYMONTH" in kv
        has_byweekno = "BYWEEKNO" in kv
        has_byyearday = "BYYEARDAY" in kv

        mode_count = sum([has_bymonth, has_byweekno, has_byyearday])
        if mode_count == 0:
            raise ValueError("recurrence_rule for YEARLY must include exactly one of: BYMONTH, BYWEEKNO, BYYEARDAY")
        if mode_count > 1:
            raise ValueError("recurrence_rule for YEARLY must not mix BYMONTH/BYWEEKNO/BYYEARDAY")

        if has_byyearday:
            banned = present_by - {"BYYEARDAY"}
            if banned or "WKST" in kv:
                raise ValueError("recurrence_rule YEARLY with BYYEARDAY must not include any other BY* or WKST")

        elif has_byweekno:
            if "BYDAY" not in kv:
                raise ValueError("recurrence_rule YEARLY with BYWEEKNO must include BYDAY")
            _validate_byday(kv["BYDAY"], allow_list=False, allow_ordinals=False)

            banned = present_by - {"BYWEEKNO", "BYDAY"}
            if banned:
                raise ValueError(
                    "recurrence_rule YEARLY with BYWEEKNO must not include BYMONTH, BYMONTHDAY, BYYEARDAY, or BYSETPOS"
                )

        else:  # month-based
            if "BYWEEKNO" in kv or "BYYEARDAY" in kv:
                raise ValueError("recurrence_rule YEARLY month-based must not include BYWEEKNO or BYYEARDAY")

            has_bymonthday = "BYMONTHDAY" in kv
            has_byday = "BYDAY" in kv
            has_bysetpos = "BYSETPOS" in kv

            if has_bymonthday:
                if has_byday or has_bysetpos:
                    raise ValueError("recurrence_rule YEARLY must use BYMONTHDAY or (BYDAY+BYSETPOS), not both")
            else:
                if not (has_byday and has_bysetpos):
                    raise ValueError("recurrence_rule YEARLY must include BYMONTHDAY or both BYDAY and BYSETPOS")
                _validate_byday(kv["BYDAY"], allow_list=False, allow_ordinals=False)

            if "WKST" in kv:
                raise ValueError("recurrence_rule YEARLY month-based must not include WKST")

    return v


class PetScheduleBase(BaseModel):
    title: Annotated[str, Field(min_length=3, max_length=255, examples=["Vet checkup"])]
    schedule_type: Annotated[PetScheduleType, Field(examples=[PetScheduleType.VET_VISIT])]
    scheduled_at: Annotated[datetime, Field(examples=["2026-01-20T10:00:00+08:00"])]
    recurrence_rule: Annotated[
        str | None,
        Field(
            min_length=1,
            max_length=1024,
            examples=["FREQ=WEEKLY;INTERVAL=1"],
            default=None,
        ),
    ]
    is_recurring: Annotated[bool, Field(examples=[True, False], default=False)]
    description: Annotated[str | None, Field(max_length=500, examples=["Annual checkup"], default=None)]

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("schedule_type", mode="before")
    @classmethod
    def normalize_type(cls, v):
        if isinstance(v, str):
            return v.strip().lower()
        return v

    @field_validator("scheduled_at")
    @classmethod
    def validate_scheduled_at_timezone(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.utcoffset() is None:
            raise ValueError("scheduled_at must include a timezone offset")
        return v

    @field_validator("recurrence_rule", "description", mode="before")
    @classmethod
    def normalize_optional_text_fields(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("recurrence_rule")
    @classmethod
    def validate_recurrence_rule(cls, v: str | None) -> str | None:
        if v is None:
            return None
        try:
            rrulestr(v)
        except Exception:
            raise ValueError("recurrence_rule must be a valid RFC 5545 RRULE")
        return v

    @field_validator("recurrence_rule")
    @classmethod
    def validate_recurrence_rule_allowed_subset(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return _validate_rrule_allowed_subset(v)

    @model_validator(mode="after")
    def validate_recurrence_fields(self):
        if self.is_recurring is True and self.recurrence_rule is None:
            raise ValueError("recurrence_rule is required when is_recurring is true")
        if self.is_recurring is False and self.recurrence_rule is not None:
            raise ValueError("recurrence_rule must be null when is_recurring is false")
        return self


class PetSchedule(TimestampSchema, PetScheduleBase, PersistentDeletion):
    pet_id: int


class PetScheduleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    pet_id: int
    title: str
    schedule_type: PetScheduleType
    scheduled_at: datetime
    is_recurring: bool
    created_at: datetime
    recurrence_rule: str | None
    description: str | None


class PetScheduleCreate(PetScheduleBase):
    model_config = ConfigDict(extra="forbid")


class PetScheduleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Annotated[str | None, Field(min_length=3, max_length=255, examples=["Updated checkup"], default=None)]
    schedule_type: Annotated[PetScheduleType | None, Field(examples=[PetScheduleType.VET_VISIT], default=None)]
    scheduled_at: Annotated[datetime | None, Field(examples=["2026-01-20T10:00:00+08:00"], default=None)]
    recurrence_rule: Annotated[
        str | None,
        Field(
            min_length=1,
            max_length=1024,
            examples=["FREQ=WEEKLY;INTERVAL=2"],
            default=None,
        ),
    ]
    is_recurring: Annotated[bool | None, Field(examples=[True], default=None)]
    description: Annotated[str | None, Field(max_length=500, examples=["Updated description"], default=None)]

    @field_validator("title", "description", "recurrence_rule", mode="before")
    @classmethod
    def normalize_text_fields(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("schedule_type", mode="before")
    @classmethod
    def normalize_type(cls, v):
        if isinstance(v, str):
            return v.strip().lower()
        return v

    @field_validator("scheduled_at")
    @classmethod
    def validate_scheduled_at_timezone(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return None
        if v.tzinfo is None or v.utcoffset() is None:
            raise ValueError("scheduled_at must include a timezone offset")
        return v

    @field_validator("recurrence_rule")
    @classmethod
    def validate_recurrence_rule(cls, v: str | None) -> str | None:
        if v is None:
            return None
        try:
            rrulestr(v)
        except Exception:
            raise ValueError("recurrence_rule must be a valid RFC 5545 RRULE")
        return v

    @field_validator("recurrence_rule")
    @classmethod
    def validate_recurrence_rule_allowed_subset(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return _validate_rrule_allowed_subset(v)

    @model_validator(mode="after")
    def validate_recurrence_fields_partial(self):
        fields = self.model_fields_set
        if "is_recurring" in fields:
            if self.is_recurring is True and self.recurrence_rule is None:
                raise ValueError("recurrence_rule is required when is_recurring is true")
            if self.is_recurring is False and self.recurrence_rule is not None:
                raise ValueError("recurrence_rule must be null when is_recurring is false")
        return self
