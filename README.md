# Room Comfort Analysis API (ISO 7730 Compliant)

API untuk menganalisis tingkat kenyamanan ruangan berdasarkan data sensor lingkungan menggunakan perhitungan **ISO 7730 (Fanger's PMV/PPD)** dan Large Language Model (LLM) untuk narasi.

## 🏗️ Arsitektur

```
┌─────────────────────────────────────────────────────────────────┐
│                        FastAPI (main.py)                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   ┌─────────────┐    ┌──────────────────┐    ┌──────────────┐  │
│   │ SensorData  │───▶│   Rule Engine    │───▶│ LLM Service  │  │
│   │  (Input)    │    │  (ISO 7730 PMV)  │    │  (Narration) │  │
│   └─────────────┘    └──────────────────┘    └──────────────┘  │
│                              │                       │          │
│                              ▼                       ▼          │
│                      ┌─────────────────────────────────┐        │
│                      │     ComfortAnalysisResponse     │        │
│                      └─────────────────────────────────┘        │
└─────────────────────────────────────────────────────────────────┘
```

### Konsep Utama

| Komponen | Fungsi | Sumber |
|----------|--------|--------|
| **Status (state)** | Kenyamanan fisiologis tubuh manusia | PPD (ISO 7730) |
| **Score (env_score)** | Kualitas lingkungan non-termal | Lux, Noise, Humidity |
| **PMV** | Predicted Mean Vote (-3 to +3) | Fanger's Equation |
| **PPD** | Predicted Percentage Dissatisfied | Eksponensial dari PMV |

> ⚠️ **PENTING**: Status dan Score adalah **INDEPENDEN**. Score tinggi (91%) tidak menjamin Status "Ideal" karena keduanya mengukur aspek berbeda.

## 📂 Struktur Project

```
agenticAI/
├── main.py           # FastAPI orchestrator
├── models.py         # Pydantic schemas (SensorData, Comfort, ACControl, etc.)
├── rule_engine.py    # ISO 7730 PMV/PPD calculation (deterministic)
├── llm_service.py    # LLM narration service (context-aware)
├── requirements.txt  # Dependencies
├── .env              # Environment variables
└── README.md
```

## 🚀 Setup

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Konfigurasi Environment
Buat file `.env`:
```env
# Untuk Ollama (default)
LLM_MODE=ollama
LLM_ENDPOINT=http://localhost:11434/api/generate
LLM_MODEL=llama3.2

# Untuk OpenAI (alternatif)
# LLM_MODE=openai
# LLM_ENDPOINT=https://api.openai.com/v1/chat/completions
# LLM_API_KEY=your-api-key
# LLM_MODEL=gpt-4
```

### 3. Jalankan Ollama (jika menggunakan Ollama)
```bash
ollama serve
ollama pull llama3.2
```

### 4. Jalankan Server
```bash
uvicorn main:app --reload --port 8000
```

## 📡 API Endpoints

### POST /analyze

Analisis tingkat kenyamanan ruangan.

**Request Body:**
```json
{
  "hum": 65.0,
  "temp": 27.5,
  "noise": 40.0,
  "light_level": 420.0,
  "occupancy": 8
}
```

**Response:**
```json
{
  "Comfort": {
    "pmv": 0.73,
    "ppd": 16.2,
    "score": 91.0,
    "state": "Optimalisasi"
  },
  "Recommendation": {
    "ac_control": {
      "temp": 22,
      "mode": "cool",
      "fan": "auto"
    },
    "reason": "Kondisi termal menunjukkan sensasi agak hangat (PMV = 0.73, tingkat: mild). Sebagai langkah PREVENTIF, dilakukan penyesuaian RINGAN setpoint AC dari target 23.5°C ke 22°C (Δ1.5°C). Koreksi ini bersifat BERTAHAP untuk menurunkan PMV secara halus mendekati 0."
  }
}
```

### GET /health

Health check endpoint.

## 📊 Parameter Input

| Parameter | Deskripsi | Unit | Range Typical |
|-----------|-----------|------|---------------|
| `hum` | Kelembapan relatif | % | 30-80% |
| `temp` | Suhu udara | °C | 18-32°C |
| `noise` | Tingkat kebisingan | dB | 30-70 dB |
| `light_level` | Pencahayaan | lux | 200-800 lux |
| `occupancy` | Jumlah penghuni | orang | 0-50+ |

## 📈 Response Fields

### Comfort Object
| Field | Deskripsi | Range |
|-------|-----------|-------|
| `pmv` | Predicted Mean Vote | -3 (cold) to +3 (hot), 0 = netral |
| `ppd` | Predicted Percentage Dissatisfied | 5% (min) - 100% |
| `score` | Environmental quality score (non-termal) | 0-100 |
| `state` | Status kenyamanan fisiologis | Lihat tabel di bawah |

### Status Kenyamanan (dari PPD)

| Status | PPD Range | Makna Operasional |
|--------|-----------|-------------------|
| **Ideal** | ≤ 10% | Tidak perlu tindakan, kondisi optimal |
| **Optimalisasi** | 10-25% | Penyesuaian RINGAN dan PREVENTIF |
| **Peringatan** | 25-50% | Koreksi AKTIF diperlukan |
| **Kritis** | > 50% | Tindakan SEGERA diperlukan |
| **Boros Energi** | - | Ruangan kosong, AC off |

### AC Control Object
| Field | Deskripsi | Values |
|-------|-----------|--------|
| `temp` | Setpoint AC | 16-30°C (integer) |
| `mode` | Mode operasi | `cool`, `auto`, `dry`, `fan`, `off` |
| `fan` | Kecepatan fan | `auto`, `low`, `medium`, `high` |

## 🧮 Algoritma ISO 7730

### PMV (Fanger's Equation)
```
PMV = (0.303 × e^(-0.036×M) + 0.028) × L
```
Di mana L adalah thermal load (ketidakseimbangan panas tubuh).

### PPD (Exponential Relationship)
```
PPD = 100 - 95 × e^(-0.03353×PMV⁴ - 0.2179×PMV²)
```

> **PENTING**: Hubungan PMV-PPD adalah **EKSPONENSIAL**, bukan linear!
> - PMV = 0 → PPD ≈ 5%
> - PMV = ±0.5 → PPD ≈ 10%
> - PMV = ±1.0 → PPD ≈ 26%
> - PMV = ±2.0 → PPD ≈ 77%

### Batasan Model (Asumsi Tetap)
| Parameter | Nilai | Asumsi |
|-----------|-------|--------|
| Met | 1.2 | Aktivitas kantor ringan (duduk, mengetik) |
| Clo | 0.5 | Pakaian indoor standar (kemeja, celana) |
| Va | 0.1 m/s | Ventilasi normal (tanpa angin kencang) |
| Tr | Ta | Mean radiant temp = Air temp |

## 🌡️ Reference Table (Target per Occupancy)

| Occupancy | Target Temp | Humidity | Lux | Noise Max |
|-----------|-------------|----------|-----|-----------|
| 0 | 24.0°C | 50% | 450 | 45 dB |
| 1-10 | 23.5°C | 45-55% | 400 | 45 dB |
| 11-18 | 25.0°C | 45-55% | 420 | 45 dB |
| 19-25 | 26.5°C | 56-65% | 380 | 55 dB |
| 26-30 | 27.1°C | 66-70% | 550 | 55 dB |
| 31+ | 28.5°C | 71-75% | 600 | 60 dB |

## ⚙️ AC Control Logic

### Gradual Thermal Correction (Status-Aware)
Koreksi suhu **dibatasi berdasarkan status** untuk mencegah overcooling/overheating:

| Status | Max ΔT dari Target |
|--------|-------------------|
| Ideal | 0°C |
| Optimalisasi | ±1.5°C |
| Peringatan | ±2.5°C |
| Kritis | ±3.0°C |

### Thermal Severity Levels
| Level | PMV Range | Fan Speed |
|-------|-----------|-----------|
| none | \|PMV\| ≤ 0.5 | auto |
| mild | 0.5 < \|PMV\| ≤ 1.0 | auto/low |
| moderate | 1.0 < \|PMV\| ≤ 1.5 | medium |
| severe | \|PMV\| > 1.5 | high |

## 🔄 Dual-Role of Humidity

Kelembapan muncul di **dua tempat** dengan peran **berbeda**:

| Konteks | Peran | Efek |
|---------|-------|------|
| **PMV** | Fisiologis | Mempengaruhi evaporasi keringat dari kulit |
| **env_score** | Kualitas udara | Rasa pengap, kesehatan pernapasan |

> Ini **BUKAN** double counting, melainkan analisis dari sudut pandang berbeda.

## 🧪 Contoh Testing

### PowerShell
```powershell
Invoke-RestMethod -Uri "http://localhost:8000/analyze" `
  -Method POST `
  -ContentType "application/json" `
  -Body '{"hum": 65.0, "temp": 27.5, "noise": 40.0, "light_level": 420.0, "occupancy": 8}' | ConvertTo-Json -Depth 5
```

### cURL
```bash
curl -X POST http://localhost:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{"hum": 65.0, "temp": 27.5, "noise": 40.0, "light_level": 420.0, "occupancy": 8}'
```

### Python
```python
import requests

response = requests.post(
    "http://localhost:8000/analyze",
    json={
        "hum": 65.0,
        "temp": 27.5,
        "noise": 40.0,
        "light_level": 420.0,
        "occupancy": 8
    }
)
print(response.json())
```

## 📝 Catatan Penting

1. **Status vs Score**: Status berasal dari PPD (kenyamanan fisiologis), Score berasal dari env_score (kualitas lingkungan). Keduanya **INDEPENDEN**.

2. **Trajectory-Centric**: Koreksi AC dihitung dari **TARGET** temperature, bukan dari suhu aktual, untuk mencegah overcooling/overheating.

3. **Narrative Guardrails**: Untuk status "Optimalisasi", narasi LLM menggunakan kata "preventif", "ringan", "bertahap" (bukan "agresif" atau "signifikan").

4. **Context-Aware**: Jika masalah utama adalah non-termal (noise/lighting), narasi akan fokus pada faktor tersebut, bukan AC.

## 📜 License

MIT License

"# AgenticAI" 
