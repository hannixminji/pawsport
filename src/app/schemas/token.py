from pydantic import BaseModel

from .mobile_user import MobileUserRead


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    user_id: int


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str
    user: MobileUserRead
    firebase_token: str | None = None
