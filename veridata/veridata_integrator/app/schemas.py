from pydantic import BaseModel, Field
from typing import Optional

class LeadCreateSchema(BaseModel):
    firstName: str
    lastName: str
    status: str
    source: Optional[str] = "Call"
    opportunityAmount: Optional[float] = 0
    opportunityAmountCurrency: Optional[str] = "USD"
    emailAddress: Optional[str] = None
    phoneNumber: str
