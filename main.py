"""FastAPI untuk analisis kenyamanan ruangan dengan Rule Engine + LLM."""
from fastapi import FastAPI, HTTPException
from dotenv import load_dotenv

from models import SensorData, ComfortAnalysisResponse, Recommendation
from rule_engine import evaluate
from llm_service import LLMService

# Load environment variables
load_dotenv()

app = FastAPI(
    title="Room Comfort Analysis API",
    description="API untuk menganalisis tingkat kenyamanan ruangan dengan Rule Engine deterministik dan LLM untuk narasi",
    version="2.0.0"
)

# Initialize LLM service (hanya untuk narasi)
llm_service = LLMService()


@app.post("/analyze", response_model=ComfortAnalysisResponse)
async def analyze_comfort(sensor_data: SensorData) -> ComfortAnalysisResponse:
    """
    Analisis tingkat kenyamanan ruangan berdasarkan data sensor.
    
    Flow:
    1. Rule Engine menghitung score, status, dan AC control (DETERMINISTIK)
    2. LLM generate narasi/reason (HANYA PENJELASAN)
    
    Parameters:
    - **hum**: Humidity (%)
    - **temp**: Temperature (°C)
    - **noise**: Noise level (dB)
    - **light_level**: Light level (lux)
    - **occupancy**: Number of occupants
    
    Returns:
    - **Comfort**: PMV, PPD, score, dan state kenyamanan
    - **Recommendation**: AC control settings dan reason
    """
    try:
        # Step 1: Rule Engine - Kalkulasi deterministik
        rule_result = evaluate(sensor_data)
        
        # Step 2: LLM - Generate narasi/reason saja
        reason = llm_service.generate_reason(sensor_data, rule_result)
        
        # Step 3: Build response
        response = ComfortAnalysisResponse(
            Comfort=rule_result.comfort,
            Recommendation=Recommendation(
                ac_control=rule_result.ac_control,
                reason=reason
            )
        )
        
        return response
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error analyzing data: {str(e)}")


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
