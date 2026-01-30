"""Pydantic models for request and response schemas."""
from typing import Literal
from pydantic import BaseModel, Field, field_validator


class SensorData(BaseModel):
    """Input payload dari sensor lingkungan ruangan."""
    hum: float = Field(..., description="Humidity (%)")
    temp: float = Field(..., description="Temperature (°C)")
    noise: float = Field(..., description="Noise level (dB)")
    light_level: float = Field(..., description="Light level (lux)")
    occupancy: int = Field(..., description="Number of occupants")


class InputSensor(BaseModel):
    """Data sensor yang digunakan untuk menghasilkan output."""
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


# Definisi tipe yang diizinkan untuk AC Control
ACMode = Literal["cool", "fan", "dry", "heat"]
ACFanSpeed = Literal["low", "medium", "high", "auto", "quiet"]


class ACControl(BaseModel):
    """Pengaturan AC untuk mencapai kenyamanan."""
    temp: int = Field(..., ge=10, le=32, description="AC temperature setting (°C) - integer value 10-32")
    mode: ACMode = Field(..., description="AC mode: 'cool', 'fan', 'dry', 'heat'")
    fan: ACFanSpeed = Field(..., description="Fan speed: 'low', 'medium', 'high', 'auto', 'quiet'")
    
    @field_validator('temp')
    @classmethod
    def validate_temp(cls, v: int) -> int:
        """Pastikan temperature dalam range yang valid."""
        if v < 10:
            return 10
        if v > 32:
            return 32
        return v


class Recommendation(BaseModel):
    """Rekomendasi aksi berdasarkan analisis."""
    reason: str = Field(..., description="Reason for the recommendation")


class ComfortAnalysisResponse(BaseModel):
    """Response JSON terstruktur."""
    Comfort: Comfort
    Recommendation: Recommendation
    Input_sensor: InputSensor


class HistoryEntry(BaseModel):
    """Entry untuk menyimpan history eksekusi LLM sebelumnya."""
    timestamp: str = Field(..., description="Timestamp eksekusi (ISO format)")
    sensor_data: SensorData = Field(..., description="Data sensor saat eksekusi")
    ac_control: ACControl = Field(..., description="Pengaturan AC yang direkomendasikan")
    comfort_state: str = Field(..., description="Status kenyamanan")
    pmv: float = Field(..., description="PMV value")
    ppd: float = Field(..., description="PPD value")
