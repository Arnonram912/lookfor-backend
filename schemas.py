from pydantic import BaseModel


class SendMessageSchema(BaseModel):
    recipient_id: int
    subject: str
    content: str


class ReplySchema(BaseModel):
    thread_id: int
    content: str


class BulkSendMessageSchema(BaseModel):
    recipient_ids: list[int]
    content: str
