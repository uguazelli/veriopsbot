# Moved to app/schemas/events.py
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field

# --- Shared / Base Models ---


class Sender(BaseModel):
    id: Optional[int] = None
    name: str = "Unknown"
    email: Optional[str] = None
    phone_number: Optional[str] = None
    thumbnail: Optional[str] = None


class Conversation(BaseModel):
    id: Union[int, str]
    status: Optional[str] = None
    channel: Optional[str] = None
    created_at: Optional[int] = None  # Unix timestamp usually


class Attachment(BaseModel):
    id: Optional[int] = None
    file_type: Optional[str] = None
    data_url: Optional[str] = None
    extension: Optional[str] = None


# --- Chatwoot Webhook Event ---


class ChatwootEvent(BaseModel):
    event: str
    message_type: Optional[str] = None
    content: Optional[str] = None
    private: Optional[bool] = False

    # Nested objects
    conversation: Optional[Conversation] = None
    sender: Optional[Sender] = None
    attachments: List[Attachment] = Field(default_factory=list)

    # Meta is sometimes used in different payload versions
    meta: Optional[Dict[str, Any]] = None

    @property
    def conversation_id(self) -> str:
        if self.conversation:
            return str(self.conversation.id)
        return ""

    @property
    def is_incoming(self) -> bool:
        return self.message_type == "incoming"

    @property
    def is_valid_bot_command(self) -> bool:
        """Helper to check if this is a message we should process"""
        if self.event != "message_created":
            return False
        if not self.is_incoming:
            return False
        if self.conversation and self.conversation.status in ("snoozed", "open"):
            return False
        return True


# --- Integration / CRM Event ---


class IntegrationMeta(BaseModel):
    sender: Optional[Sender] = None


class IntegrationEvent(BaseModel):
    event: str

    # content can be dict (conversation obj) or anything depending on event
    content: Optional[Union[Dict[str, Any], Any]] = None

    # Direct sender provided at top level or in meta
    sender: Optional[Sender] = None
    meta: Optional[IntegrationMeta] = None

    @property
    def effective_sender(self) -> Optional[Sender]:
        """Unifies sender lookup logic"""
        if self.sender:
            return self.sender
        if self.meta and self.meta.sender:
            return self.meta.sender
        return None
