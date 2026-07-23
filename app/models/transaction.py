from datetime import datetime

from pydantic import BaseModel


class TransactionOut(BaseModel):
    id: str
    type: str
    direction: str
    amount_points: float
    amount_usd: float | None = None
    related_subscription_id: str | None = None
    related_track_id: str | None = None
    status: str
    created_at: datetime

    @classmethod
    def from_mongo(cls, doc: dict) -> "TransactionOut":
        return cls(
            id=str(doc["_id"]),
            type=doc["type"],
            direction=doc["direction"],
            amount_points=doc["amount_points"],
            amount_usd=doc.get("amount_usd"),
            related_subscription_id=str(doc["related_subscription_id"]) if doc.get("related_subscription_id") else None,
            related_track_id=doc.get("related_track_id"),
            status=doc["status"],
            created_at=doc["created_at"],
        )
