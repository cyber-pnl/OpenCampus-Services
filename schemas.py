# schemas.py
from pydantic import BaseModel
from typing import Optional

class LoginRequest(BaseModel):
    username: str
    password: str

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    uid: str
    display_name: str
    expires_in: int

class TokenVerifyResponse(BaseModel):
    valid: bool
    uid: Optional[str] = None
    role: Optional[str] = None