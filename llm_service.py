"""LLM Service untuk generate narasi/reason (HANYA NARASI, TIDAK UNTUK KALKULASI).

Versi ISO 7730 dengan perbaikan:
- PMV/PPD sudah dihitung dengan rumus Fanger
- Status ditentukan dari PPD (kenyamanan FISIOLOGIS)
- Score terpisah untuk kualitas LINGKUNGAN
- Context-aware: soroti masalah utama (termal vs non-termal)
- Model constraints dijelaskan sebagai batasan, bukan fakta absolut
"""
import os
import json
import requests
from models import SensorData
from rule_engine import RuleResult, EnvIssue


# PMV interpretation (ISO 7730)
PMV_SCALE = {
    -3: "sangat dingin (cold)",
    -2: "dingin (cool)", 
    -1: "agak dingin (slightly cool)",
    0: "netral (neutral)",
    1: "agak hangat (slightly warm)",
    2: "hangat (warm)",
    3: "panas (hot)"
}


def get_pmv_description(pmv: float) -> str:
    """Dapatkan deskripsi sensasi termal dari PMV."""
    if pmv <= -2.5:
        return "sangat dingin"
    elif pmv <= -1.5:
        return "dingin"
    elif pmv <= -0.5:
        return "agak dingin"
    elif pmv <= 0.5:
        return "netral/nyaman"
    elif pmv <= 1.5:
        return "agak hangat"
    elif pmv <= 2.5:
        return "hangat"
    else:
        return "panas"


class LLMService:
    """Service untuk berkomunikasi dengan LLM - HANYA UNTUK NARASI."""
    
    def __init__(self):
        self.mode = os.getenv("LLM_MODE", "ollama").lower()
        self.endpoint = os.getenv("LLM_ENDPOINT", "http://localhost:11434/api/generate")
        self.api_key = os.getenv("LLM_API_KEY")
        self.model = os.getenv("LLM_MODEL", "llama3.2")

    def generate_reason(self, sensor_data: SensorData, rule_result: RuleResult) -> str:
        """Generate narasi/reason berdasarkan data sensor dan hasil rule engine."""
        prompt = self._build_prompt(sensor_data, rule_result)
        
        try:
            response_text = self._generate(prompt)
            return self._parse_reason(response_text)
        except Exception as e:
            # Fallback reason jika LLM gagal
            return self._generate_fallback_reason(sensor_data, rule_result)

    def _build_prompt(self, data: SensorData, result: RuleResult) -> str:
        """Buat prompt untuk LLM dengan informasi ISO 7730 dan context-aware guidance."""
        
        pmv_desc = get_pmv_description(result.comfort.pmv)
        
        # Format environmental issues jika ada
        env_issues_text = ""
        if result.env_issues:
            issues_list = []
            for issue in result.env_issues:
                issues_list.append(f"  - [{issue.severity.upper()}] {issue.description}")
                issues_list.append(f"    → Saran: {issue.recommendation}")
            env_issues_text = "\n".join(issues_list)
        else:
            env_issues_text = "  Tidak ada masalah lingkungan signifikan."
        
        # Tentukan fokus narasi berdasarkan primary concern
        focus_guidance = ""
        if result.primary_concern == "environmental":
            focus_guidance = """FOKUS NARASI: Masalah UTAMA adalah LINGKUNGAN (bukan termal).
- Soroti masalah non-termal (noise/lighting/humidity) sebagai penyebab utama ketidaknyamanan
- AC tetap disebutkan tapi bukan fokus utama
- Berikan saran untuk faktor non-termal"""
        elif result.primary_concern == "both":
            focus_guidance = """FOKUS NARASI: Ada masalah GANDA (termal DAN lingkungan).
- Jelaskan kedua aspek secara seimbang
- Prioritaskan yang lebih parah
- Berikan rekomendasi komprehensif"""
        elif result.primary_concern == "thermal":
            focus_guidance = """FOKUS NARASI: Masalah UTAMA adalah TERMAL.
- Fokus pada PMV dan koreksi AC
- Lingkungan non-termal dalam kondisi baik"""
        else:
            focus_guidance = """FOKUS NARASI: Kondisi OPTIMAL.
- Jelaskan mengapa kondisi sudah ideal
- Sarankan untuk mempertahankan pengaturan"""
        
        # ===== NARRATIVE GUARDRAILS berdasarkan status =====
        narrative_guardrails = ""
        if result.comfort.state == "Optimalisasi":
            narrative_guardrails = """GUARDRAIL NARASI (WAJIB untuk status Optimalisasi):
══════════════════════════════════════════════════════════════════
⚠️ KATA YANG DILARANG (jangan gunakan!):
  ✘ "koreksi signifikan"
  ✘ "penyesuaian agresif" 
  ✘ "drastis"
  ✘ "perubahan besar"

✅ KATA YANG WAJIB digunakan:
  ✔ "preventif"
  ✔ "ringan"
  ✔ "bertahap"
  ✔ "halus"
  ✔ "penyesuaian kecil"
══════════════════════════════════════════════════════════════════"""
        elif result.comfort.state == "Ideal":
            narrative_guardrails = """GUARDRAIL NARASI (untuk status Ideal):
══════════════════════════════════════════════════════════════════
Tekankan bahwa kondisi sudah OPTIMAL dan tidak perlu tindakan.
Gunakan kata: "pertahankan", "optimal", "nyaman", "seimbang"
══════════════════════════════════════════════════════════════════"""
        
        # ===== MANDATORY: Penjelasan Score vs Status jika berbeda persepsi =====
        score_status_explanation = ""
        if result.env_score >= 80 and result.comfort.state in ("Optimalisasi", "Peringatan"):
            score_status_explanation = f"""KALIMAT WAJIB DALAM NARASI:
══════════════════════════════════════════════════════════════════
Karena env_score ({result.env_score}%) tinggi tapi status "{result.comfort.state}",
TAMBAHKAN kalimat edukatif seperti:
"Meskipun kualitas lingkungan non-termal sangat baik (skor {result.env_score}%), 
status ditentukan oleh kenyamanan fisiologis tubuh (PPD), bukan oleh skor lingkungan."
══════════════════════════════════════════════════════════════════"""
        
        # Thermal severity description
        thermal_severity = getattr(result, 'thermal_severity', 'none')
        severity_desc = {
            "none": "dalam zona netral",
            "mild": "sedikit di luar zona nyaman (mild)",
            "moderate": "tidak nyaman (moderate)", 
            "severe": "sangat tidak nyaman (severe)"
        }.get(thermal_severity, "unknown")
        
        return f"""Kamu adalah asisten analisis kenyamanan ruangan berbasis standar ISO 7730.

══════════════════════════════════════════════════════════════════
DATA SENSOR AKTUAL:
══════════════════════════════════════════════════════════════════
• Suhu udara (Ta): {data.temp}°C
• Kelembapan (RH): {data.hum}%
• Kebisingan: {data.noise} dB
• Pencahayaan: {data.light_level} lux
• Jumlah penghuni: {data.occupancy} orang

══════════════════════════════════════════════════════════════════
HASIL ANALISIS KENYAMANAN TERMAL (ISO 7730):
══════════════════════════════════════════════════════════════════
• PMV (Predicted Mean Vote): {result.comfort.pmv}
  → Sensasi termal: {pmv_desc}
  → Tingkat keparahan: {severity_desc}

• PPD (Predicted Percentage Dissatisfied): {result.comfort.ppd}%
  → Artinya: {result.comfort.ppd}% penghuni diperkirakan tidak nyaman
  → Hubungan PMV-PPD adalah EKSPONENSIAL (bukan linear!)

• Status Kenyamanan Fisiologis: {result.comfort.state}
  → Target temp: {result.target_temp}°C

══════════════════════════════════════════════════════════════════
KUALITAS LINGKUNGAN (NON-TERMAL):
══════════════════════════════════════════════════════════════════
• Skor Lingkungan: {result.env_score}/100
• Detail: Pencahayaan {result.env_score_breakdown.get('lighting', 0)}/100, 
         Kebisingan {result.env_score_breakdown.get('noise', 0)}/100,
         Kelembapan {result.env_score_breakdown.get('humidity', 0)}/100

• Masalah Lingkungan Terdeteksi:
{env_issues_text}

══════════════════════════════════════════════════════════════════
KEPUTUSAN KONTROL AC:
══════════════════════════════════════════════════════════════════
• Setpoint: {result.ac_control.temp}°C (dari target {result.target_temp}°C)
• Mode: {result.ac_control.mode}
• Fan: {result.ac_control.fan}
• Koreksi: trajectory-centric (dari target, bukan dari suhu aktual)

══════════════════════════════════════════════════════════════════
{focus_guidance}
══════════════════════════════════════════════════════════════════

{narrative_guardrails}

{score_status_explanation}

TUGAS: Buat narasi 3-5 kalimat yang:
1. Menjelaskan kondisi dengan alur sebab-akibat
2. Mengikuti GUARDRAIL NARASI di atas
3. Menyertakan kalimat WAJIB jika ada
4. Konsisten dengan status "{result.comfort.state}"

FORMAT OUTPUT (JSON):
{{"reason": "<narasi 3-5 kalimat>"}}"""

    def _generate(self, prompt: str, max_tokens: int = 400, temperature: float = 0.3) -> str:
        """Generate response dari LLM."""
        if self.mode == "openai":
            return self._openai_generate(prompt, max_tokens, temperature)
        return self._ollama_generate(prompt, max_tokens, temperature)

    def _ollama_generate(self, prompt: str, max_tokens: int, temperature: float) -> str:
        """Generate menggunakan Ollama."""
        headers = {"Content-Type": "application/json"}
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens
            }
        }
        
        resp = requests.post(self.endpoint, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        
        if isinstance(data, dict) and "response" in data:
            return data["response"]
        return json.dumps(data)

    def _openai_generate(self, prompt: str, max_tokens: int, temperature: float) -> str:
        """Generate menggunakan OpenAI API."""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature
        }
        
        resp = requests.post(self.endpoint, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        
        if "choices" in data and len(data["choices"]) > 0:
            return data["choices"][0].get("message", {}).get("content", "")
        return json.dumps(data)

    def _parse_reason(self, response_text: str) -> str:
        """Parse response LLM untuk mendapatkan reason."""
        text = response_text.strip()
        
        try:
            # Cari JSON block
            if "```json" in text:
                start = text.find("```json") + 7
                end = text.find("```", start)
                text = text[start:end].strip()
            elif "```" in text:
                start = text.find("```") + 3
                end = text.find("```", start)
                text = text[start:end].strip()
            
            # Cari JSON object
            start_idx = text.find("{")
            end_idx = text.rfind("}") + 1
            if start_idx != -1 and end_idx > start_idx:
                text = text[start_idx:end_idx]
            
            data = json.loads(text)
            if "reason" in data:
                return data["reason"]
        except (json.JSONDecodeError, ValueError):
            pass
        
        # Fallback: bersihkan text
        text = response_text.strip()
        text = text.replace("```json", "").replace("```", "")
        text = text.replace('{"reason":', "").replace('"}', "").replace('"', "")
        return text.strip()

    def _generate_fallback_reason(self, data: SensorData, result: RuleResult) -> str:
        """Generate reason fallback dengan ISO 7730, status-aware language, dan score vs status explanation."""
        pmv = result.comfort.pmv
        ppd = result.comfort.ppd
        status = result.comfort.state
        pmv_desc = get_pmv_description(pmv)
        primary_concern = result.primary_concern
        thermal_severity = getattr(result, 'thermal_severity', 'none')
        
        # ===== Score vs Status explanation (wajib jika score tinggi tapi status bukan Ideal) =====
        score_explanation = ""
        if result.env_score >= 80 and status in ("Optimalisasi", "Peringatan"):
            score_explanation = (
                f" Meskipun kualitas lingkungan non-termal sangat baik (skor {result.env_score}%), "
                f"status ditentukan oleh kenyamanan fisiologis tubuh (PPD), bukan oleh skor lingkungan."
            )
        
        # ===== Status Boros Energi (ruangan kosong) =====
        if status == "Boros Energi":
            return (
                f"Ruangan kosong (occupancy: 0) sehingga tidak ada kebutuhan kenyamanan termal. "
                f"AC dimatikan (mode: off) untuk efisiensi energi. "
                f"Sistem akan aktif kembali saat terdeteksi penghuni."
            )
        
        # ===== Context-Aware: Masalah ENVIRONMENTAL sebagai fokus utama =====
        if primary_concern == "environmental" and result.env_issues:
            main_issue = result.env_issues[0]
            return (
                f"Kondisi termal dalam zona {pmv_desc} (PMV = {pmv}, PPD = {ppd}%). "
                f"Namun, masalah utama adalah {main_issue.factor}: {main_issue.description}. "
                f"Saran: {main_issue.recommendation}. "
                f"AC tetap pada {result.ac_control.temp}°C mode {result.ac_control.mode} "
                f"untuk mempertahankan kenyamanan termal."
            )
        
        # ===== Context-Aware: Masalah GANDA (termal + environmental) =====
        if primary_concern == "both" and result.env_issues:
            main_issue = result.env_issues[0]
            thermal_action = "diturunkan" if pmv > 0 else "dinaikkan"
            return (
                f"Terdeteksi masalah ganda: (1) Sensasi {pmv_desc} (PMV = {pmv}) dengan {ppd}% penghuni tidak nyaman, "
                f"dan (2) {main_issue.description}. "
                f"Untuk aspek termal, AC disetel ke {result.ac_control.temp}°C mode {result.ac_control.mode}. "
                f"Untuk {main_issue.factor}, disarankan: {main_issue.recommendation}."
            )
        
        # ===== Status Ideal (kondisi optimal) =====
        if status == "Ideal":
            return (
                f"Kondisi ruangan optimal dengan PMV = {pmv} (sensasi {pmv_desc}). "
                f"Hanya {ppd}% penghuni diperkirakan tidak nyaman berdasarkan standar ISO 7730. "
                f"AC dipertahankan pada {result.ac_control.temp}°C mode {result.ac_control.mode} "
                f"untuk menjaga keseimbangan termal."
            )
        
        # ===== Status Optimalisasi (WAJIB gunakan bahasa preventif/ringan) =====
        if status == "Optimalisasi":
            # GUARDRAIL: Gunakan kata "preventif", "ringan", "bertahap", "halus"
            delta_temp = abs(result.ac_control.temp - result.target_temp)
            direction = "menurunkan" if pmv > 0 else "menaikkan"
            return (
                f"Kondisi termal menunjukkan sensasi {pmv_desc} (PMV = {pmv}, tingkat: {thermal_severity}). "
                f"Sebagai langkah PREVENTIF, dilakukan penyesuaian RINGAN setpoint AC "
                f"dari target {result.target_temp}°C ke {result.ac_control.temp}°C (Δ{delta_temp}°C). "
                f"Koreksi ini bersifat BERTAHAP untuk {direction} PMV secara halus mendekati 0.{score_explanation}"
            )
        
        # ===== Status Peringatan (koreksi aktif) =====
        if status == "Peringatan":
            return (
                f"Kondisi termal menunjukkan sensasi {pmv_desc} dengan PMV = {pmv} (tingkat: {thermal_severity}). "
                f"Berdasarkan ISO 7730, {ppd}% penghuni diperkirakan tidak nyaman. "
                f"Status '{status}' memerlukan koreksi aktif. "
                f"AC disetel ke {result.ac_control.temp}°C mode {result.ac_control.mode} fan {result.ac_control.fan} "
                f"untuk mengembalikan PMV ke zona netral.{score_explanation}"
            )
        
        # ===== Status Kritis (tindakan segera) =====
        if status == "Kritis":
            return (
                f"PERHATIAN: Kondisi termal kritis dengan PMV = {pmv} (sensasi {pmv_desc}). "
                f"Sebanyak {ppd}% penghuni diperkirakan tidak nyaman, melampaui ambang toleransi. "
                f"Tindakan segera diperlukan. AC disetel ke {result.ac_control.temp}°C "
                f"mode {result.ac_control.mode} fan {result.ac_control.fan} untuk koreksi maksimum."
            )
        
        # ===== PMV Positif (Hangat/Panas) - generic =====
        if pmv > 0:
            correction_style = "ringan dan bertahap" if thermal_severity == "mild" else "aktif"
            return (
                f"Kondisi termal menunjukkan sensasi {pmv_desc} dengan PMV = {pmv}. "
                f"Berdasarkan perhitungan ISO 7730, {ppd}% penghuni diperkirakan tidak nyaman. "
                f"AC disetel secara {correction_style} ke {result.ac_control.temp}°C "
                f"mode {result.ac_control.mode} fan {result.ac_control.fan}.{score_explanation}"
            )
        
        # ===== PMV Negatif (Dingin) - generic =====
        if pmv < 0:
            correction_style = "ringan" if thermal_severity == "mild" else "signifikan"
            return (
                f"Kondisi termal menunjukkan sensasi {pmv_desc} dengan PMV = {pmv}. "
                f"Berdasarkan ISO 7730, {ppd}% penghuni diperkirakan tidak nyaman. "
                f"AC disetel ke {result.ac_control.temp}°C mode {result.ac_control.mode} fan {result.ac_control.fan} "
                f"untuk mengurangi pendinginan secara {correction_style}.{score_explanation}"
            )
        
        # ===== Default =====
        return (
            f"Kondisi termal netral (PMV = {pmv}) dengan {ppd}% penghuni tidak nyaman. "
            f"Skor kualitas lingkungan {result.env_score}/100. "
            f"AC disetel ke {result.ac_control.temp}°C mode {result.ac_control.mode} "
            f"untuk mempertahankan kenyamanan termal."
        )
