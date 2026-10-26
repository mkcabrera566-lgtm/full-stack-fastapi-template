import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import EmailStr, field_validator
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, Relationship, SQLModel


def get_datetime_utc() -> datetime:
    return datetime.now(UTC)


# Shared properties
class UserBase(SQLModel):
    email: EmailStr = Field(unique=True, index=True, max_length=255)
    is_active: bool = True
    is_superuser: bool = False
    full_name: str | None = Field(default=None, max_length=255)


# Properties to receive via API on creation
class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)


class UserRegister(SQLModel):
    email: EmailStr = Field(max_length=255)
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)


# Properties to receive via API on update, all are optional
class UserUpdate(SQLModel):
    email: EmailStr | None = Field(default=None, max_length=255)
    is_active: bool | None = None
    is_superuser: bool | None = None
    full_name: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, min_length=8, max_length=128)


class UserUpdateMe(SQLModel):
    full_name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = Field(default=None, max_length=255)


class UpdatePassword(SQLModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


# Database model, database table inferred from class name
class User(UserBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    hashed_password: str
    created_at: datetime | None = Field(default_factory=get_datetime_utc)
    items: list[Item] = Relationship(back_populates="owner", cascade_delete=True)
    tickets: list[Ticket] = Relationship(back_populates="owner", cascade_delete=True)


# Properties to return via API, id is always required
class UserPublic(UserBase):
    id: uuid.UUID
    created_at: datetime | None = None


class UsersPublic(SQLModel):
    data: list[UserPublic]
    count: int


# Shared properties
class ItemBase(SQLModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=255)


# Properties to receive on item creation
class ItemCreate(ItemBase):
    pass


# Properties to receive on item update
class ItemUpdate(SQLModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=255)


# Database model, database table inferred from class name
class Item(ItemBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = Field(default_factory=get_datetime_utc)
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    owner: User | None = Relationship(back_populates="items")


# Properties to return via API, id is always required
class ItemPublic(ItemBase):
    id: uuid.UUID
    owner_id: uuid.UUID
    created_at: datetime | None = None


class ItemsPublic(SQLModel):
    data: list[ItemPublic]
    count: int


class TicketStatus(StrEnum):
    open = "open"
    in_progress = "in_progress"
    resolved = "resolved"
    closed = "closed"


class TicketPriority(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"
    urgent = "urgent"


class TicketBase(SQLModel):
    model_config = SQLModel.model_config.copy()
    model_config["str_strip_whitespace"] = True

    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1, max_length=10000)
    priority: TicketPriority = Field(default=TicketPriority.medium)


class TicketCreate(TicketBase):
    model_config = TicketBase.model_config.copy()
    model_config["extra"] = "forbid"


class TicketUpdate(SQLModel):
    model_config = SQLModel.model_config.copy()
    model_config["extra"] = "forbid"
    model_config["str_strip_whitespace"] = True

    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, min_length=1, max_length=10000)
    status: TicketStatus | None = None
    priority: TicketPriority | None = None

    @field_validator("title", "description", "status", "priority", mode="before")
    @classmethod
    def reject_explicit_null(cls, value: object) -> object:
        # Missing PATCH fields keep their defaults; explicit null would violate NOT NULL.
        if value is None:
            raise ValueError("Field may be omitted, but must not be null")
        return value


class Ticket(TicketBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    status: TicketStatus = Field(
        default=TicketStatus.open,
        sa_type=SAEnum(
            TicketStatus,
            name="ticket_status",
            native_enum=False,
            create_constraint=True,
        ),
    )
    priority: TicketPriority = Field(
        default=TicketPriority.medium,
        sa_type=SAEnum(
            TicketPriority,
            name="ticket_priority",
            native_enum=False,
            create_constraint=True,
        ),
    )
    created_at: datetime = Field(default_factory=get_datetime_utc)
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE", index=True
    )
    owner: User | None = Relationship(back_populates="tickets")


class TicketPublic(TicketBase):
    id: uuid.UUID
    status: TicketStatus
    created_at: datetime
    owner_id: uuid.UUID


class TicketsPublic(SQLModel):
    data: list[TicketPublic]
    count: int


# Generic message
class Message(SQLModel):
    message: str


# JSON payload containing access token
class Token(SQLModel):
    access_token: str
    token_type: str = "bearer"


# Contents of JWT token
class TokenPayload(SQLModel):
    sub: str | None = None


class NewPassword(SQLModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)
