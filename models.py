"""Pydantic models for request and response schemas."""
from pydantic import BaseModel, Field


class SensorData(BaseModel):
    """Input payload dari sensor lingkungan ruangan."""
    hum: float = Field(..., description="Humidity (%)")
    temp: float = Field(..., description="Temperature (°C)")
    noise: float = Field(..., description="Noise level (dB)")
    light_level: float = Field(..., description="Light level (lux)")
    occupancy: int = Field(..., description="Number of occupants")


class Comfort(BaseModel):
    """Hasil analisis tingkat kenyamanan."""
    pmv: float = Field(..., description="Predicted Mean Vote (-3 to +3)")
    ppd: float = Field(..., description="Predicted Percentage Dissatisfied (%)")
    score: float = Field(..., description="Comfort score (0-100)")
    state: str = Field(..., description="Comfort state (e.g., 'comfortable', 'too hot', 'too cold')")


class ACControl(BaseModel):
    """Pengaturan AC untuk mencapai kenyamanan."""
    temp: int = Field(..., description="AC temperature setting (°C) - integer value 16-30")
    mode: str = Field(..., description="AC mode: 'cool', 'fan', 'dry', 'auto', 'off'")
    fan: str = Field(..., description="Fan speed: 'low', 'medium', 'high', 'auto'")


class Recommendation(BaseModel):
    """Rekomendasi aksi berdasarkan analisis."""
    ac_control: ACControl = Field(..., description="AC control settings")
    reason: str = Field(..., description="Reason for the recommendation")


class ComfortAnalysisResponse(BaseModel):
    """Response JSON terstruktur."""
    Comfort: Comfort
    Recommendation: Recommendation
