from datetime import date, datetime
from decimal import Decimal
from typing import Annotated
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, computed_field, field_validator

from ..core.enums import PetSex, PetSpecies
from ..core.schemas import PersistentDeletion, TimestampSchema, UUIDSchema
from .pet_allergy import PetAllergyRead
from .pet_medical_condition import PetMedicalConditionRead
from .pet_photo import PetPhotoCreate, PetPhotoRead, PetPhotoUpdate
from .pet_qr_default import PetQRDefaultRead
from .pet_qr_preference import PetQRPreferenceCreate, PetQRPreferenceRead, PetQRPreferenceUpdate
from .pet_vaccination_record import PetVaccinationRecordRead


class PetBase(BaseModel):
    name: Annotated[str, Field(min_length=2, max_length=25, examples=["Max"])]
    species: Annotated[PetSpecies, Field(examples=[PetSpecies.DOG])]
    breed: Annotated[str, Field(min_length=3, max_length=30, examples=["Golden Retriever"])]
    sex: Annotated[PetSex, Field(examples=[PetSex.MALE])]
    date_of_birth: Annotated[date, Field(examples=["2020-06-15"])]
    color: Annotated[str | None, Field(min_length=1, max_length=30, examples=["black-white"], default=None)]
    markings: Annotated[str | None, Field(max_length=255, examples=["White patch on chest"], default=None)]
    weight_kg: Annotated[Decimal | None, Field(gt=0, le=120, decimal_places=2, examples=[4.25], default=None)]
    is_sterilized: Annotated[bool, Field(examples=[True, False])]

    @field_validator("name", "breed", mode="before")
    @classmethod
    def normalize_required_text_fields(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("species", "sex", mode="before")
    @classmethod
    def normalize_enum_fields(cls, v):
        if isinstance(v, str):
            return v.strip().lower()
        return v

    @field_validator("date_of_birth")
    @classmethod
    def validate_date_of_birth(cls, v: date) -> date:
        if v > date.today():
            raise ValueError("date_of_birth must not be in the future")
        return v

    @field_validator("color", "markings", mode="before")
    @classmethod
    def normalize_optional_text_fields(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("color", "markings")
    @classmethod
    def validate_printable_optional_text(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if any(ch for ch in v if not ch.isprintable()):
            raise ValueError("text fields must not contain control characters")
        return v

    @field_validator("weight_kg", mode="before")
    @classmethod
    def validate_weight_kg(cls, v):
        if v is None:
            return None
        try:
            d = Decimal(str(v)) if not isinstance(v, Decimal) else v
        except (TypeError, ValueError, ArithmeticError):
            raise ValueError("weight_kg must be a valid decimal number")

        if d.as_tuple().exponent < -2:
            raise ValueError("weight_kg must have at most 2 decimal places")

        return d


class Pet(TimestampSchema, PetBase, UUIDSchema, PersistentDeletion):
    owner_id: int
    is_missing: bool = False
    qr_code_object_key: str | None = None


class PetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int
    name: str
    species: str
    breed: str
    sex: str
    date_of_birth: date
    is_sterilized: bool
    uuid: UUID
    photos: list[PetPhotoRead]
    created_at: datetime
    color: str | None
    markings: str | None
    weight_kg: Decimal | None
    qr_preference: PetQRPreferenceRead | None
    qr_code_url: str | None


class PetReadWithPrimaryProfile(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int
    name: str
    species: str
    breed: str
    sex: str
    date_of_birth: date
    created_at: datetime
    weight_kg: Decimal | None
    color: str | None
    markings: str | None
    qr_preference: PetQRPreferenceRead | None
    qr_code_url: str | None
    primary_photo_url: str | None


class OwnerQR(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    first_name: str | None
    last_name: str | None
    email: str | None
    is_email_verified: bool
    phone_number: str | None
    street_address_1: str | None
    street_address_2: str | None
    city: str | None
    state_province_region: str | None
    postal_code: str | None
    country: str | None


class PetReadByQR(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    owner: OwnerQR = Field(exclude=True)
    name: str
    species: str
    breed: str
    sex: str
    is_sterilized: bool
    date_of_birth: date
    is_missing: bool
    photos: list[PetPhotoRead]
    allergies: list[PetAllergyRead]
    medical_conditions: list[PetMedicalConditionRead]
    vaccination_records: list[PetVaccinationRecordRead]
    weight_kg: Decimal | None
    color: str | None
    markings: str | None
    qr_code_url: str | None

    # Public Information
    _qr_show_owner_name: bool = PrivateAttr(False)
    _qr_show_email: bool = PrivateAttr(False)
    _qr_show_phone_number: bool = PrivateAttr(False)
    _qr_show_address: bool = PrivateAttr(False)

    # Pet Details
    _qr_show_pet_name: bool = PrivateAttr(True)
    _qr_show_pet_breed: bool = PrivateAttr(True)
    _qr_show_pet_age: bool = PrivateAttr(True)
    _qr_show_pet_sex: bool = PrivateAttr(True)
    _qr_show_pet_weight: bool = PrivateAttr(True)
    _qr_show_pet_color: bool = PrivateAttr(True)
    _qr_show_pet_markings: bool = PrivateAttr(True)
    _qr_show_pet_sterilized: bool = PrivateAttr(True)

    # Health Records
    _qr_show_medications: bool = PrivateAttr(False)
    _qr_show_vaccines: bool = PrivateAttr(False)
    _qr_show_allergies: bool = PrivateAttr(False)

    @classmethod
    def from_data(
        cls,
        *,
        owner: OwnerQR,
        name: str,
        species: str,
        breed: str,
        sex: str,
        is_sterilized: bool,
        date_of_birth: date,
        is_missing: bool,
        photos: list[PetPhotoRead],
        allergies: list[PetAllergyRead],
        medical_conditions: list[PetMedicalConditionRead],
        vaccination_records: list[PetVaccinationRecordRead],
        weight_kg: Decimal | None,
        color: str | None,
        markings: str | None,
        qr_code_url: str | None,
        defaults: PetQRDefaultRead | None = None,
        preference: PetQRPreferenceRead | None = None,
    ):
        obj = cls(
            owner=owner,
            name=name,
            species=species,
            breed=breed,
            sex=sex,
            is_sterilized=is_sterilized,
            date_of_birth=date_of_birth,
            is_missing=is_missing,
            photos=photos,
            allergies=allergies,
            medical_conditions=medical_conditions,
            vaccination_records=vaccination_records,
            weight_kg=weight_kg,
            color=color,
            markings=markings,
            qr_code_url=qr_code_url,
        )

        if preference is not None and getattr(preference, "override_defaults", False) is True:
            obj._qr_show_owner_name = preference.show_owner_name
            obj._qr_show_email = preference.show_email
            obj._qr_show_phone_number = preference.show_phone_number
            obj._qr_show_address = preference.show_address
            obj._qr_show_pet_name = preference.show_pet_name
            obj._qr_show_pet_breed = preference.show_pet_breed
            obj._qr_show_pet_age = preference.show_pet_age
            obj._qr_show_pet_sex = preference.show_pet_sex
            obj._qr_show_pet_weight = preference.show_pet_weight
            obj._qr_show_pet_color = preference.show_pet_color
            obj._qr_show_pet_markings = preference.show_pet_markings
            obj._qr_show_pet_sterilized = preference.show_pet_sterilized
            obj._qr_show_medications = preference.show_medications
            obj._qr_show_vaccines = preference.show_vaccines
            obj._qr_show_allergies = preference.show_allergies
        else:
            obj._qr_show_owner_name = defaults.show_owner_name if defaults else False
            obj._qr_show_email = defaults.show_email if defaults else False
            obj._qr_show_phone_number = defaults.show_phone_number if defaults else False
            obj._qr_show_address = defaults.show_address if defaults else False
            obj._qr_show_pet_name = defaults.show_pet_name if defaults else True
            obj._qr_show_pet_breed = defaults.show_pet_breed if defaults else True
            obj._qr_show_pet_age = defaults.show_pet_age if defaults else True
            obj._qr_show_pet_sex = defaults.show_pet_sex if defaults else True
            obj._qr_show_pet_weight = defaults.show_pet_weight if defaults else True
            obj._qr_show_pet_color = defaults.show_pet_color if defaults else True
            obj._qr_show_pet_markings = defaults.show_pet_markings if defaults else True
            obj._qr_show_pet_sterilized = defaults.show_pet_sterilized if defaults else True
            obj._qr_show_medications = defaults.show_medications if defaults else False
            obj._qr_show_vaccines = defaults.show_vaccines if defaults else False
            obj._qr_show_allergies = defaults.show_allergies if defaults else False

        return obj

    @computed_field(return_type=str | None)
    @property
    def owner_name(self) -> str | None:
        if not self._qr_show_owner_name:
            return None
        first = (self.owner.first_name or "").strip()
        last = (self.owner.last_name or "").strip()
        full = f"{first} {last}".strip()
        return full or None

    @computed_field(return_type=str | None)
    @property
    def owner_email(self) -> str | None:
        if not self._qr_show_email:
            return None
        if not self.owner.is_email_verified:
            return "Not verified"
        return (self.owner.email or "").strip() or None

    @computed_field(return_type=str | None)
    @property
    def owner_phone_number(self) -> str | None:
        if not self._qr_show_phone_number:
            return None
        raw = (self.owner.phone_number or "").strip()
        if not raw:
            return None
        if raw.lower().startswith("tel:"):
            raw = raw[4:].strip()
        else:
            parsed = urlparse(raw)
            if parsed.scheme.lower() == "tel":
                raw = parsed.path.strip()
        return raw or None

    @computed_field(return_type=str | None)
    @property
    def owner_address(self) -> str | None:
        if not self._qr_show_address:
            return None
        parts: list[str] = []
        for val in (
            self.owner.street_address_1,
            self.owner.street_address_2,
            self.owner.city,
            self.owner.state_province_region,
            self.owner.postal_code,
            self.owner.country,
        ):
            if isinstance(val, str):
                val = val.strip()
            if val:
                parts.append(val)
        return ", ".join(parts) if parts else None

    @computed_field(return_type=str | None)
    @property
    def age(self) -> str | None:
        dob = self.date_of_birth
        if not dob:
            return None
        today = date.today()
        if dob > today:
            return None
        years = today.year - dob.year
        months = today.month - dob.month
        if today.day < dob.day:
            months -= 1
        if months < 0:
            years -= 1
            months += 12
        if years <= 0:
            return f"{months} month{'s' if months != 1 else ''}" if months else "0 months"
        if months == 0:
            return f"{years} year{'s' if years != 1 else ''}"
        return f"{years} year{'s' if years != 1 else ''} {months} month{'s' if months != 1 else ''}"

    @computed_field(return_type=bool)
    @property
    def show_pet_name(self) -> bool:
        return self._qr_show_pet_name

    @computed_field(return_type=bool)
    @property
    def show_pet_breed(self) -> bool:
        return self._qr_show_pet_breed

    @computed_field(return_type=bool)
    @property
    def show_pet_age(self) -> bool:
        return self._qr_show_pet_age

    @computed_field(return_type=bool)
    @property
    def show_pet_sex(self) -> bool:
        return self._qr_show_pet_sex

    @computed_field(return_type=bool)
    @property
    def show_pet_weight(self) -> bool:
        return self._qr_show_pet_weight

    @computed_field(return_type=bool)
    @property
    def show_pet_color(self) -> bool:
        return self._qr_show_pet_color

    @computed_field(return_type=bool)
    @property
    def show_pet_markings(self) -> bool:
        return self._qr_show_pet_markings

    @computed_field(return_type=bool)
    @property
    def show_pet_sterilized(self) -> bool:
        return self._qr_show_pet_sterilized

    @computed_field(return_type=bool)
    @property
    def show_medications(self) -> bool:
        return self._qr_show_medications

    @computed_field(return_type=bool)
    @property
    def show_vaccines(self) -> bool:
        return self._qr_show_vaccines

    @computed_field(return_type=bool)
    @property
    def show_allergies(self) -> bool:
        return self._qr_show_allergies


class PetSearch(PetRead):
    score: float


class PetCreate(PetBase):
    model_config = ConfigDict(extra="forbid")

    qr_preference: PetQRPreferenceCreate


class PetCreateWithPhotos(PetCreate):
    photos: Annotated[list[PetPhotoCreate], Field(..., min_length=1, max_length=5)]

    @field_validator("photos", mode="after")
    @classmethod
    def validate_photos(cls, photos):
        if not photos:
            return photos

        object_keys = [photo.object_key for photo in photos]
        if len(object_keys) != len(set(object_keys)):
            raise ValueError("photo object_key must be unique")

        sort_orders = [photo.sort_order for photo in photos]
        if len(sort_orders) != len(set(sort_orders)):
            raise ValueError("photo sort_order must be unique")

        return photos


class PetUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str | None, Field(min_length=2, max_length=25, examples=["Max"], default=None)]
    breed: Annotated[str | None, Field(min_length=3, max_length=30, examples=["Golden Retriever"], default=None)]
    sex: Annotated[PetSex | None, Field(examples=[PetSex.MALE], default=None)]
    date_of_birth: Annotated[date | None, Field(examples=["2020-06-15"], default=None)]
    color: Annotated[str | None, Field(min_length=1, max_length=30, examples=["black-white"], default=None)]
    markings: Annotated[str | None, Field(max_length=255, examples=["White patch on chest"], default=None)]
    weight_kg: Annotated[Decimal | None, Field(gt=0, le=120, decimal_places=2, examples=[4.25], default=None)]
    is_sterilized: Annotated[bool | None, Field(examples=[True], default=None)]
    qr_preference: Annotated[PetQRPreferenceUpdate | None, Field(default=None)]

    @field_validator("name", "breed", "color", "markings", mode="before")
    @classmethod
    def normalize_text_fields(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("name", "breed", "color", "markings")
    @classmethod
    def validate_printable_text(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if any(ch for ch in v if not ch.isprintable()):
            raise ValueError("text fields must not contain control characters")
        return v

    @field_validator("sex", mode="before")
    @classmethod
    def normalize_sex(cls, v):
        if isinstance(v, str):
            return v.strip().lower()
        return v

    @field_validator("date_of_birth")
    @classmethod
    def validate_date_of_birth(cls, v: date | None) -> date | None:
        if v is not None and v > date.today():
            raise ValueError("date_of_birth must not be in the future")
        return v

    @field_validator("weight_kg", mode="before")
    @classmethod
    def validate_weight_kg(cls, v):
        if v is None:
            return None
        try:
            d = Decimal(str(v)) if not isinstance(v, Decimal) else v
        except (TypeError, ValueError, ArithmeticError):
            raise ValueError("weight_kg must be a valid decimal number")

        if d.as_tuple().exponent < -2:
            raise ValueError("weight_kg must have at most 2 decimal places")

        return d


class PetUpdateWithPhotos(PetUpdate):
    photos: Annotated[list[PetPhotoUpdate] | None, Field(default=None, min_length=1, max_length=5)]

    @field_validator("photos", mode="after")
    @classmethod
    def validate_photos(cls, photos):
        if photos is None:
            return photos

        if not photos:
            return photos

        photo_ids = [photo.id for photo in photos if photo.id is not None]
        if len(photo_ids) != len(set(photo_ids)):
            raise ValueError("duplicate photo ids are not allowed")

        object_keys = [photo.object_key for photo in photos if photo.object_key is not None]
        if len(object_keys) != len(set(object_keys)):
            raise ValueError("duplicate object keys are not allowed")

        sort_orders = [photo.sort_order for photo in photos]
        if len(sort_orders) != len(set(sort_orders)):
            raise ValueError("photo sort_order must be unique")

        return photos
