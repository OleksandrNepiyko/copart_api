from pydantic import BaseModel
from typing import Dict, Any, List

# Це модель того, що прилітає у POST запиті
class IAAIRawPayload(BaseModel):
    # Оскільки JSON може бути складної структури (з вкладеностями),
    # для початку можна прийняти просто словник
    lot_data: Dict[str, Any]
