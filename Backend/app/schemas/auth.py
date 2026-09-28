import uuid

from pydantic import BaseModel, EmailStr, Field

from app.models.enums import UserRole


class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, description="At least 8 characters")
    full_name: str
    company_name: str = Field(
        default="Demo Company",
        description="If this company doesn't exist yet, it's created automatically "
        "and this user becomes its admin. If it already exists, the user joins it "
        "as a manager.",
    )


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: UserRole
    company_id: uuid.UUID

    model_config = {"from_attributes": True}


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"