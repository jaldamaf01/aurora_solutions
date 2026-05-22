# webapp/backend/app/models.py
from typing import Optional, Any, Dict
from pydantic import BaseModel, ConfigDict, Field


class TrackEvent(BaseModel):
    """
    Evento client-side enviado por el front a POST /track.
    Permitimos extra fields para extensibilidad.
    """
    model_config = ConfigDict(extra="allow")

    # Identidad / tiempo / sesión
    student_id: Optional[str] = Field(default=None)
    timestamp: Optional[str] = Field(default=None)  # ISO8601
    dt: Optional[str] = Field(default=None)         # YYYY-MM-DD
    session_id: Optional[str] = Field(default=None)

    # Semántica
    event_type: Optional[str] = Field(default=None)  # page_view, click, begin_checkout, purchase...
    source: Optional[str] = Field(default="client")  # client
    page: Optional[str] = Field(default=None)        # pathname

    # Campos típicos de tracking
    action: Optional[str] = None
    element_id: Optional[str] = None
    event_id: Optional[int] = None
    utm_campaign: Optional[str] = None
    referrer: Optional[str] = None
    amount: Optional[float] = None

    # Para compatibilidad: si llegan extras, quedan en el dict del modelo
    def to_event_dict(self) -> Dict[str, Any]:
        return self.model_dump()