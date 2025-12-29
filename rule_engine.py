"""Rule Engine untuk kalkulasi kenyamanan ruangan (ISO 7730 Compliant).

KONSEP UTAMA:
══════════════════════════════════════════════════════════════════════════════════
1. STATUS (dari PPD) → Kenyamanan fisiologis tubuh manusia
   - Menunjukkan seberapa banyak penghuni yang tidak nyaman
   - Dihitung dari PMV menggunakan hubungan EKSPONENSIAL (bukan linear!)
   - PPD = 100 - 95 × e^(-0.03353×PMV⁴ - 0.2179×PMV²)
   
2. SCORE (env_score) → Kualitas lingkungan non-termal
   - Pencahayaan, kebisingan, kelembapan (aspek produktivitas)
   - TIDAK mempengaruhi status, berdiri sendiri
   
3. PMV-PPD adalah hubungan NON-LINEAR:
   - PMV = 0 → PPD ≈ 5% (minimum teoritis)
   - PMV = ±0.5 → PPD ≈ 10%
   - PMV = ±1.0 → PPD ≈ 26%
   - PMV = ±2.0 → PPD ≈ 77%
   Perubahan PMV kecil di sekitar 0 tidak banyak mengubah PPD,
   tapi perubahan PMV di area ekstrem sangat signifikan.

BATASAN MODEL (Model Constraints):
══════════════════════════════════════════════════════════════════════════════════
Perhitungan PMV menggunakan ASUMSI TETAP yang sesuai untuk:
- Met = 1.2 → Aktivitas kantor ringan (duduk, mengetik)
- Clo = 0.5 → Pakaian standar indoor (kemeja, celana)
- Va = 0.1 m/s → Ventilasi normal (tanpa angin kencang)
- Tr = Ta → Mean radiant temperature sama dengan air temperature

Asumsi ini BUKAN fakta universal, melainkan kondisi referensi ISO 7730.
Hasil PMV/PPD valid untuk kondisi tersebut.

PERANAN GANDA KELEMBAPAN (Humidity Dual-Role):
══════════════════════════════════════════════════════════════════════════════════
1. Dalam PMV: Efek fisiologis → mempengaruhi penguapan keringat (evaporative heat loss)
2. Dalam env_score: Efek kualitas udara → rasa pengap, kesehatan pernapasan
Kedua peran ini BERBEDA secara konseptual, bukan double counting.
"""
import math
from dataclasses import dataclass
from models import SensorData, Comfort, ACControl


# ============================================================================
# DEFAULT ASSUMPTIONS (jika tidak ada sensor)
# ============================================================================
DEFAULT_MEAN_RADIANT_TEMP_OFFSET = 0.0  # Tr = Ta + offset
DEFAULT_AIR_VELOCITY = 0.1  # m/s (typical indoor)
DEFAULT_METABOLIC_RATE = 1.2  # Met (office work, seated)
DEFAULT_CLOTHING_INSULATION = 0.5  # Clo (typical indoor clothing)

# ============================================================================
# REFERENCE TABLE - Digunakan sebagai BOUNDARY & TARGET, bukan nilai absolut
# ============================================================================
# Format: (occ_min, occ_max, target_temp, hum_min, hum_max, lux, noise_max)
REFERENCE_TABLE = [
    (0, 0, 24.0, 50, 50, 450, 45),      # Ruangan kosong
    (1, 10, 23.5, 45, 55, 400, 45),     # Occupancy rendah
    (11, 18, 25.0, 45, 55, 420, 45),    # Occupancy sedang
    (19, 25, 26.5, 56, 65, 380, 55),    # Occupancy tinggi
    (26, 30, 27.1, 66, 70, 550, 55),    # Occupancy sangat tinggi
    (31, 999, 28.5, 71, 75, 600, 60),   # Occupancy ekstrem
]

# ============================================================================
# STATUS MAPPING berdasarkan PPD (ISO 7730)
# ============================================================================
# PPD adalah indikator utama kenyamanan termal FISIOLOGIS manusia.
# Status ini TERPISAH dari env_score dan tidak boleh dicampuradukkan.
#
# MAKNA OPERASIONAL SETIAP STATUS:
# ═══════════════════════════════════════════════════════════════════════════════
# "Ideal"       → Tidak perlu tindakan. Kondisi optimal. Pertahankan.
# "Optimalisasi"→ Penyesuaian RINGAN dan PREVENTIF. Koreksi kecil untuk mencegah
#                 ketidaknyamanan berkembang. Tidak mendesak.
# "Peringatan"  → Ketidaknyamanan JELAS dirasakan. Koreksi AKTIF diperlukan.
#                 Penghuni mulai komplain.
# "Kritis"      → Tindakan SEGERA diperlukan. Kondisi tidak dapat ditoleransi.
#                 Risiko kesehatan jika dibiarkan.
# ═══════════════════════════════════════════════════════════════════════════════
PPD_STATUS_MAP = [
    (0, 10, "Ideal"),           # PPD ≤ 10%: Kondisi optimal, tidak perlu tindakan
    (10, 25, "Optimalisasi"),   # 10% < PPD ≤ 25%: Penyesuaian ringan, preventif
    (25, 50, "Peringatan"),     # 25% < PPD ≤ 50%: Koreksi aktif diperlukan
    (50, 100, "Kritis"),        # PPD > 50%: Tindakan segera diperlukan
]


@dataclass
class EnvIssue:
    """Masalah lingkungan non-termal yang terdeteksi."""
    factor: str          # lighting, noise, humidity
    severity: str        # minor, moderate, severe
    description: str     # Deskripsi singkat masalah
    recommendation: str  # Saran perbaikan selain AC


@dataclass
class RuleResult:
    """Hasil dari rule engine.
    
    KONSEP PENTING:
    - comfort.state (dari PPD) → Status kenyamanan FISIOLOGIS tubuh
    - env_score → Skor kualitas LINGKUNGAN (non-termal)
    - Keduanya INDEPENDEN dan tidak saling override
    """
    comfort: Comfort
    ac_control: ACControl
    # Target values berdasarkan occupancy
    target_temp: float
    target_hum_min: int
    target_hum_max: int
    target_lux: int
    target_noise_max: int
    # Environmental quality score (TERPISAH dari PMV/PPD)
    env_score: float
    env_score_breakdown: dict
    # PMV calculation inputs (untuk transparansi dan dokumentasi constraint)
    pmv_inputs: dict
    # Deviasi untuk narasi
    temp_deviation: float
    hum_deviation: float
    # Context-aware: masalah non-termal yang terdeteksi
    env_issues: list  # List of EnvIssue
    # Flag: apakah masalah utama adalah termal atau non-termal?
    primary_concern: str  # "thermal", "environmental", "both", "none"
    # Thermal severity level (untuk kontrol yang lebih nuanced)
    thermal_severity: str  # "none", "mild", "moderate", "severe"


def get_reference_for_occupancy(occupancy: int) -> tuple:
    """Ambil target values berdasarkan occupancy."""
    for ref in REFERENCE_TABLE:
        occ_min, occ_max = ref[0], ref[1]
        if occ_min <= occupancy <= occ_max:
            return ref
    return REFERENCE_TABLE[-1]  # Fallback ke occupancy tertinggi


# ============================================================================
# PMV CALCULATION - ISO 7730 (Fanger's Equation)
# ============================================================================
def calculate_pmv(
    ta: float,          # Air temperature (°C)
    tr: float,          # Mean radiant temperature (°C)
    vel: float,         # Air velocity (m/s)
    rh: float,          # Relative humidity (%)
    met: float,         # Metabolic rate (met)
    clo: float          # Clothing insulation (clo)
) -> float:
    """
    Hitung PMV menggunakan rumus Fanger (ISO 7730).
    
    PMV = (0.303 * e^(-0.036*M) + 0.028) * L
    
    di mana L adalah thermal load (ketidakseimbangan panas tubuh)
    """
    # Konversi unit
    M = met * 58.15  # Metabolic rate (W/m²)
    W = 0  # External work (W/m²), biasanya 0 untuk aktivitas kantor
    
    # Clothing insulation
    if clo <= 0.078:
        fcl = 1.0 + 1.290 * clo
    else:
        fcl = 1.05 + 0.645 * clo
    
    Icl = clo * 0.155  # Clothing insulation (m²·K/W)
    
    # Water vapor pressure (Pa)
    pa = rh * 10 * math.exp(16.6536 - 4030.183 / (ta + 235))
    
    # Heat transfer coefficient by convection
    hc_natural = 2.38 * abs(35.7 - 0.028 * (M - W) - ta) ** 0.25
    hc_forced = 12.1 * math.sqrt(vel)
    hc = max(hc_natural, hc_forced)
    
    # Iterative calculation for clothing surface temperature
    tcl = 35.7 - 0.028 * (M - W)  # Initial guess
    
    for _ in range(100):  # Max iterations
        tcl_old = tcl
        
        # Clothing surface temperature
        tcl = 35.7 - 0.028 * (M - W) - Icl * (
            3.96e-8 * fcl * ((tcl + 273) ** 4 - (tr + 273) ** 4) +
            fcl * hc * (tcl - ta)
        )
        
        if abs(tcl - tcl_old) < 0.001:
            break
    
    # Thermal load (L)
    # Heat loss from skin
    HL1 = 3.05e-3 * (5733 - 6.99 * (M - W) - pa)  # Skin diffusion
    HL2 = 0.42 * ((M - W) - 58.15) if (M - W) > 58.15 else 0  # Sweating
    HL3 = 1.7e-5 * M * (5867 - pa)  # Latent respiration
    HL4 = 0.0014 * M * (34 - ta)  # Dry respiration
    HL5 = 3.96e-8 * fcl * ((tcl + 273) ** 4 - (tr + 273) ** 4)  # Radiation
    HL6 = fcl * hc * (tcl - ta)  # Convection
    
    # Total thermal load
    L = (M - W) - HL1 - HL2 - HL3 - HL4 - HL5 - HL6
    
    # PMV
    pmv = (0.303 * math.exp(-0.036 * M) + 0.028) * L
    
    # Clamp PMV to -3 to +3
    return max(-3.0, min(3.0, round(pmv, 2)))


def calculate_ppd(pmv: float) -> float:
    """
    Hitung PPD dari PMV menggunakan rumus ISO 7730.
    
    PPD = 100 - 95 * exp(-0.03353 * PMV^4 - 0.2179 * PMV^2)
    
    Minimum PPD ≈ 5% saat PMV = 0
    """
    ppd = 100 - 95 * math.exp(-0.03353 * pmv**4 - 0.2179 * pmv**2)
    return round(max(5.0, min(100.0, ppd)), 1)


def get_status_from_ppd(ppd: float, occupancy: int) -> str:
    """
    Tentukan status berdasarkan PPD.
    
    PPD adalah indikator utama kenyamanan termal manusia.
    """
    if occupancy == 0:
        return "Boros Energi"
    
    for ppd_min, ppd_max, status in PPD_STATUS_MAP:
        if ppd_min < ppd <= ppd_max or (ppd_min == 0 and ppd <= ppd_max):
            return status
    
    return "Kritis"


# ============================================================================
# ENVIRONMENTAL QUALITY SCORE (Terpisah dari PMV/PPD)
# ============================================================================
# PENTING: Score ini untuk aspek NON-TERMAL yang mempengaruhi produktivitas.
# Kelembapan muncul di sini DAN di PMV karena perannya BERBEDA:
# - Di PMV: Efek fisiologis (evaporasi keringat dari kulit)
# - Di env_score: Efek kualitas udara (pengap, kesehatan pernapasan)
# Ini BUKAN double counting, melainkan analisis dari sudut pandang berbeda.
# ============================================================================
def calculate_env_score(
    lux_actual: float,
    lux_target: float,
    noise_actual: float,
    noise_max: float,
    hum_actual: float,
    hum_min: float,
    hum_max: float
) -> tuple:
    """
    Hitung skor kualitas lingkungan (tidak termasuk suhu/PMV).
    
    Score ini untuk aspek non-termal:
    - Pencahayaan (lux) → produktivitas visual
    - Kebisingan (noise) → konsentrasi, stress
    - Kelembapan (humidity) → kualitas udara, kesehatan pernapasan
      (berbeda dari peran humidity di PMV yang untuk evaporasi keringat)
    
    Returns: (score, breakdown_dict, issues_list)
    """
    breakdown = {}
    issues = []
    
    # ===== Lighting score (0-100) =====
    lux_deviation = abs(lux_actual - lux_target)
    if lux_deviation <= 50:
        lux_score = 100
    elif lux_deviation <= 100:
        lux_score = 80
    elif lux_deviation <= 200:
        lux_score = 60
    else:
        lux_score = max(0, 100 - lux_deviation / 5)
    breakdown["lighting"] = round(lux_score, 1)
    
    # Detect lighting issues
    if lux_actual < lux_target - 100:
        severity = "severe" if lux_actual < lux_target - 200 else "moderate"
        issues.append(EnvIssue(
            factor="lighting",
            severity=severity,
            description=f"Pencahayaan terlalu redup ({lux_actual} lux, target {lux_target} lux)",
            recommendation="Tambah sumber cahaya atau buka tirai"
        ))
    elif lux_actual > lux_target + 200:
        severity = "severe" if lux_actual > lux_target + 400 else "moderate"
        issues.append(EnvIssue(
            factor="lighting",
            severity=severity,
            description=f"Pencahayaan berlebihan/silau ({lux_actual} lux, target {lux_target} lux)",
            recommendation="Kurangi pencahayaan atau gunakan tirai anti-silau"
        ))
    
    # ===== Noise score (0-100) =====
    if noise_actual <= noise_max:
        noise_score = 100
    elif noise_actual <= noise_max + 5:
        noise_score = 80
    elif noise_actual <= noise_max + 10:
        noise_score = 60
    else:
        noise_score = max(0, 100 - (noise_actual - noise_max) * 5)
    breakdown["noise"] = round(noise_score, 1)
    
    # Detect noise issues
    noise_over = noise_actual - noise_max
    if noise_over > 15:
        issues.append(EnvIssue(
            factor="noise",
            severity="severe",
            description=f"Kebisingan sangat tinggi ({noise_actual} dB, batas {noise_max} dB)",
            recommendation="Identifikasi dan eliminasi sumber bising, pertimbangkan peredam suara"
        ))
    elif noise_over > 5:
        issues.append(EnvIssue(
            factor="noise",
            severity="moderate",
            description=f"Kebisingan di atas batas nyaman ({noise_actual} dB, batas {noise_max} dB)",
            recommendation="Kurangi aktivitas bising atau gunakan white noise"
        ))
    
    # ===== Humidity score (0-100) =====
    # Catatan: Di sini humidity dinilai dari perspektif KUALITAS UDARA (pengap, pernapasan)
    # berbeda dengan perannya di PMV yang untuk EVAPORASI keringat
    if hum_min <= hum_actual <= hum_max:
        hum_score = 100
    else:
        if hum_actual < hum_min:
            hum_deviation = hum_min - hum_actual
        else:
            hum_deviation = hum_actual - hum_max
        
        if hum_deviation <= 5:
            hum_score = 90
        elif hum_deviation <= 10:
            hum_score = 70
        elif hum_deviation <= 15:
            hum_score = 50
        else:
            hum_score = max(0, 100 - hum_deviation * 3)
    breakdown["humidity"] = round(hum_score, 1)
    
    # Detect humidity issues (dari perspektif kualitas udara)
    if hum_actual < hum_min - 10:
        issues.append(EnvIssue(
            factor="humidity",
            severity="moderate",
            description=f"Udara terlalu kering ({hum_actual}%, target {hum_min}-{hum_max}%)",
            recommendation="Gunakan humidifier atau kurangi intensitas AC"
        ))
    elif hum_actual > hum_max + 10:
        severity = "severe" if hum_actual > hum_max + 20 else "moderate"
        issues.append(EnvIssue(
            factor="humidity",
            severity=severity,
            description=f"Udara terlalu lembap/pengap ({hum_actual}%, target {hum_min}-{hum_max}%)",
            recommendation="Tingkatkan ventilasi atau gunakan dehumidifier"
        ))
    
    # Overall environmental score (weighted average)
    # Lighting dan noise lebih penting untuk produktivitas
    total_score = (lux_score * 0.35 + noise_score * 0.35 + hum_score * 0.3)
    
    return round(total_score, 1), breakdown, issues


# ============================================================================
# AC CONTROL - GRADUAL THERMAL CORRECTION (Status-Aware)
# ============================================================================
# PRINSIP KOREKSI BERTAHAP (Gradual Thermal Correction):
# ════════════════════════════════════════════════════════════════════════════
# PMV berubah sekitar 0.3-0.5 per 1°C perubahan suhu udara.
# Koreksi terlalu agresif menyebabkan overcooling/overheating.
#
# STRATEGI STATUS-AWARE:
# - "Ideal"       → Tidak ada koreksi, pertahankan target
# - "Optimalisasi"→ Koreksi RINGAN, max ±1.5°C dari target (BUKAN dari suhu aktual!)
# - "Peringatan"  → Koreksi MODERATE, max ±2.5°C dari target
# - "Kritis"      → Koreksi AKTIF, max ±3°C dari target
#
# TRAJECTORY-CENTRIC (bukan target-centric):
# Koreksi dihitung dari TARGET, bukan melompat langsung ke suhu akhir.
# Ini mencegah overcooling/overheating yang tidak nyaman.
# ============================================================================

# Batas koreksi maksimum berdasarkan status (dari target, bukan suhu aktual)
STATUS_MAX_CORRECTION = {
    "Ideal": 0.0,           # Tidak ada koreksi
    "Optimalisasi": 1.5,    # Penyesuaian ringan & preventif
    "Peringatan": 2.5,      # Koreksi aktif
    "Kritis": 3.0,          # Koreksi maksimum
    "Boros Energi": 0.0,    # AC off
}


def get_thermal_severity(pmv: float) -> str:
    """
    Tentukan tingkat keparahan masalah termal berdasarkan PMV.
    
    Levels:
    - none: PMV dalam zona netral (-0.5 to +0.5)
    - mild: Sedikit tidak nyaman (0.5 < |PMV| ≤ 1.0)
    - moderate: Tidak nyaman (1.0 < |PMV| ≤ 1.5)
    - severe: Sangat tidak nyaman (|PMV| > 1.5)
    """
    abs_pmv = abs(pmv)
    if abs_pmv <= 0.5:
        return "none"
    elif abs_pmv <= 1.0:
        return "mild"
    elif abs_pmv <= 1.5:
        return "moderate"
    else:
        return "severe"


def determine_ac_control(
    pmv: float,
    ppd: float,
    current_temp: float,
    target_temp: float,
    occupancy: int,
    status: str
) -> ACControl:
    """
    Tentukan pengaturan AC dengan prinsip:
    1. Status-Aware: Koreksi dibatasi sesuai status
    2. Trajectory-Centric: Koreksi dari TARGET, bukan melompat ke suhu akhir
    3. Gradual: PMV kecil → koreksi kecil
    
    ATURAN PENTING:
    - Untuk "Optimalisasi": Max ΔT = ±1.5°C dari target
    - Koreksi = target_temp ± adjustment (bukan dari current_temp)
    """
    
    # Occupancy 0: Matikan AC untuk efisiensi energi
    if occupancy == 0:
        return ACControl(temp=24, mode="off", fan="auto")
    
    abs_pmv = abs(pmv)
    thermal_severity = get_thermal_severity(pmv)
    
    # ===== ZONA NETRAL: PMV -0.5 sampai +0.5 =====
    # Tidak perlu koreksi, pertahankan target
    if thermal_severity == "none":
        return ACControl(
            temp=int(round(target_temp)),
            mode="auto",
            fan="auto"
        )
    
    # ===== HITUNG KOREKSI BERDASARKAN THERMAL SEVERITY =====
    # Koreksi proporsional dengan severity
    if thermal_severity == "mild":
        # PMV 0.5-1.0: Koreksi ringan
        base_adjustment = 0.5 + (abs_pmv - 0.5) * 1.5  # 0.5 - 1.25°C
    elif thermal_severity == "moderate":
        # PMV 1.0-1.5: Koreksi moderate
        base_adjustment = 1.25 + (abs_pmv - 1.0) * 1.5  # 1.25 - 2.0°C
    else:  # severe
        # PMV > 1.5: Koreksi aktif
        base_adjustment = 2.0 + (abs_pmv - 1.5) * 0.67  # 2.0 - 3.0°C
    
    # ===== TERAPKAN BATAS MAKSIMUM BERDASARKAN STATUS =====
    # INI KUNCI: Optimalisasi tidak boleh koreksi lebih dari 1.5°C!
    max_correction = STATUS_MAX_CORRECTION.get(status, 1.5)
    temp_adjustment = min(base_adjustment, max_correction)
    
    # ===== TENTUKAN FAN SPEED BERDASARKAN SEVERITY DAN STATUS =====
    # Untuk mild thermal issue: fan auto (minimal intervensi sensorik)
    # Untuk moderate: fan low-medium
    # Untuk severe: fan medium-high
    if thermal_severity == "mild":
        # PMV 0.5-0.8 → auto, PMV 0.8-1.0 → low
        if abs_pmv <= 0.8:
            fan_speed = "auto"  # Minimal intervensi, preventif
        else:
            fan_speed = "low"
    elif thermal_severity == "moderate":
        fan_speed = "medium"
    else:  # severe
        fan_speed = "high"
    
    # ===== TERAPKAN KOREKSI (TRAJECTORY-CENTRIC) =====
    # Koreksi dihitung dari TARGET, bukan dari current_temp
    if pmv > 0:
        # Hangat/panas → turunkan setpoint dari target
        ac_temp = int(round(target_temp - temp_adjustment))
        mode = "cool"
    else:
        # Dingin → naikkan setpoint dari target
        ac_temp = int(round(target_temp + temp_adjustment))
        # Mode tergantung seberapa dingin
        if thermal_severity == "severe":
            mode = "fan"  # Matikan kompresor
        elif thermal_severity == "moderate":
            mode = "dry"  # Dry mode untuk transisi
        else:
            mode = "auto"  # Biarkan AC menyesuaikan
    
    # Clamp suhu ke range operasional AC Central (16-30°C)
    ac_temp = max(16, min(30, ac_temp))
    
    return ACControl(temp=ac_temp, mode=mode, fan=fan_speed)


# ============================================================================
# MAIN EVALUATION FUNCTION
# ============================================================================
def evaluate(sensor_data: SensorData) -> RuleResult:
    """
    Evaluasi data sensor menggunakan perhitungan ISO 7730.
    
    Flow:
    1. Ambil target values berdasarkan occupancy
    2. Hitung PMV menggunakan rumus Fanger
    3. Hitung PPD dari PMV (hubungan EKSPONENSIAL!)
    4. Tentukan status dari PPD (status = kenyamanan FISIOLOGIS)
    5. Hitung environmental score terpisah (env_score = kualitas LINGKUNGAN)
    6. Identifikasi masalah non-termal untuk context-aware recommendation
    7. Tentukan AC control dengan gradual correction
    
    KONSEP PENTING:
    - Status berasal dari PPD → kenyamanan fisiologis tubuh
    - Score berasal dari env_score → kualitas lingkungan non-termal
    - Keduanya INDEPENDEN dan tidak saling mempengaruhi
    """
    
    # 1. Ambil reference values
    ref = get_reference_for_occupancy(sensor_data.occupancy)
    occ_min, occ_max, target_temp, hum_min, hum_max, target_lux, noise_max = ref
    
    # 2. Siapkan input untuk PMV calculation
    # CONSTRAINT MODEL: Asumsi ini untuk aktivitas kantor ringan, pakaian indoor standar
    ta = sensor_data.temp  # Air temperature
    tr = ta + DEFAULT_MEAN_RADIANT_TEMP_OFFSET  # Mean radiant temp (assumed = air temp)
    vel = DEFAULT_AIR_VELOCITY  # Air velocity (0.1 m/s, ventilasi normal)
    rh = sensor_data.hum  # Relative humidity
    met = DEFAULT_METABOLIC_RATE  # Metabolic rate (1.2 met, aktivitas kantor)
    clo = DEFAULT_CLOTHING_INSULATION  # Clothing insulation (0.5 clo, pakaian indoor)
    
    pmv_inputs = {
        "ta": ta,
        "tr": tr,
        "vel": vel,
        "rh": rh,
        "met": met,
        "clo": clo,
        # Dokumentasi constraint untuk transparansi
        "_constraint_note": "Asumsi: aktivitas kantor ringan (met=1.2), pakaian indoor (clo=0.5), ventilasi normal (vel=0.1)"
    }
    
    # 3. Hitung PMV dan PPD (ISO 7730)
    # PENTING: Hubungan PMV-PPD adalah EKSPONENSIAL, bukan linear!
    # PPD = 100 - 95 × e^(-0.03353×PMV⁴ - 0.2179×PMV²)
    pmv = calculate_pmv(ta, tr, vel, rh, met, clo)
    ppd = calculate_ppd(pmv)
    
    # 4. Tentukan status dari PPD
    # Status mencerminkan kenyamanan FISIOLOGIS tubuh manusia
    status = get_status_from_ppd(ppd, sensor_data.occupancy)
    
    # 5. Hitung environmental score (TERPISAH dari PMV/PPD)
    # env_score mencerminkan kualitas LINGKUNGAN (pencahayaan, kebisingan, kelembapan udara)
    env_score, env_breakdown, env_issues = calculate_env_score(
        sensor_data.light_level, target_lux,
        sensor_data.noise, noise_max,
        sensor_data.hum, hum_min, hum_max
    )
    
    # 6. Tentukan primary concern dan thermal severity
    thermal_severity = get_thermal_severity(pmv)
    thermal_problem = thermal_severity != "none"  # Ada masalah termal jika bukan "none"
    env_problem = len([i for i in env_issues if i.severity in ("moderate", "severe")]) > 0
    
    if thermal_problem and env_problem:
        primary_concern = "both"
    elif thermal_problem:
        primary_concern = "thermal"
    elif env_problem:
        primary_concern = "environmental"
    else:
        primary_concern = "none"
    
    # 7. Tentukan AC control dengan gradual correction
    ac_control = determine_ac_control(
        pmv, ppd, sensor_data.temp, target_temp,
        sensor_data.occupancy, status
    )
    
    # 8. Hitung deviasi untuk narasi
    temp_deviation = round(sensor_data.temp - target_temp, 1)
    
    if sensor_data.hum < hum_min:
        hum_deviation = round(sensor_data.hum - hum_min, 1)
    elif sensor_data.hum > hum_max:
        hum_deviation = round(sensor_data.hum - hum_max, 1)
    else:
        hum_deviation = 0.0
    
    # 9. Build comfort object
    # score di Comfort adalah env_score (untuk backward compatibility)
    # CATATAN: state dari PPD, score dari env_score - keduanya INDEPENDEN
    comfort = Comfort(
        pmv=pmv,
        ppd=ppd,
        score=env_score,  # Environmental score (BUKAN determinan status)
        state=status       # Status dari PPD (BUKAN dari score)
    )
    
    return RuleResult(
        comfort=comfort,
        ac_control=ac_control,
        target_temp=target_temp,
        target_hum_min=hum_min,
        target_hum_max=hum_max,
        target_lux=target_lux,
        target_noise_max=noise_max,
        env_score=env_score,
        env_score_breakdown=env_breakdown,
        pmv_inputs=pmv_inputs,
        temp_deviation=temp_deviation,
        hum_deviation=hum_deviation,
        env_issues=env_issues,
        primary_concern=primary_concern,
        thermal_severity=thermal_severity
    )
