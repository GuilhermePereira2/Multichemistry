from pydantic import BaseModel
from typing import List, Optional, Tuple, Any

# --- Component Models ---


class Fuse(BaseModel):
    brand: str = ""
    model: str = ""
    vdc_max: float = 0
    a_max: float = 0
    temp_min: float = 0
    temp_max: float = 0
    price: float = 0
    link: str = ""


class Relay(BaseModel):
    brand: str = ""
    model: str = ""
    vdc_max: float = 0
    a_max: float = 0
    temp_min: float = 0
    temp_max: float = 0
    price: float = 0
    link: str = ""


class Cable(BaseModel):
    brand: str = ""
    model: str = ""
    section: float = 0
    vdc_max: float = 0
    a_max: float = 0
    temp_min: float = 0
    temp_max: float = 0
    price: float = 0
    link: str = ""


class Bms(BaseModel):
    brand: str = ""
    model: str = ""
    max_cells: int = 0
    vdc_min: float = 0
    vdc_max: float = 0
    a_max: float = 0
    temp_min: float = 0
    temp_max: float = 0
    master_price: float = 0
    slave_price: float = 0
    link: str = ""


class Shunt(BaseModel):
    brand: str = ""
    model: str = ""
    vdc_max: float = 0
    a_max: float = 0
    temp_min: float = 0
    temp_max: float = 0
    price: float = 0
    link: str = ""

# --- Cell Data ---


class CellData(BaseModel):
    Brand: str
    CellModelNo: str
    Composition: str
    Cell_Stack: str
    MaxContinuousDischargeRate: float
    MaxContinuousChargeRate: float
    NominalVoltage: float
    ChargeVoltage: float
    Capacity: float
    # Opcional pois nem todas as DBs têm
    PeakDischargeRate: Optional[float] = 0.0
    Impedance: float
    Weight: float
    Cell_Thickness: float
    Cell_Width: float
    Cell_Height: float
    TabsThickness: float
    TabsWidth: float
    TabsLength: float
    DistanceBetweenTwoTabs: float
    VolumeEnergyDensity: Optional[float] = 0
    PowerEnergyDensity: Optional[float] = 0
    Cycles: int
    Price: float
    OriginCountry: str
    Connection: str

# --- Inputs ---


class Requirements(BaseModel):
    min_voltage: float = 48.0
    max_voltage: float = 52.0
    min_energy: float = 5000.0
    min_continuous_power: float = 2000.0
    max_weight: float = 100.0
    max_price: float = 10000.0
    max_width: float = 500.0
    max_length: float = 1000.0
    max_height: float = 300.0
    ambient_temp: float = 25.0
    target_price: float = 0.0
    debug: bool = False


class Dimensions(BaseModel):
    length: float
    width: float
    height: float


class SafetyAssessment(BaseModel):
    is_safe: bool
    safety_score: int
    warnings: List[str]
    recommendations: List[str]

# --- Output Structures ---

# 1. Configuration (Subpack): Representa um bloco de uma única química


class Configuration(BaseModel):
    cell: CellData
    series_cells: int
    parallel_cells: int
    battery_voltage: float
    battery_capacity: float
    battery_energy: float
    battery_weight: float
    battery_impedance: float
    continuous_power: float
    peak_power: float
    cell_price: float
    total_price: float
    safety: SafetyAssessment

    # Componentes Opcionais (caso a lógica os preencha no futuro)
    fuse: Optional[Fuse] = None
    relay: Optional[Relay] = None
    cable: Optional[Cable] = None
    bms: Optional[Bms] = None
    shunt: Optional[Shunt] = None
    dimensions: Optional[Dimensions] = None

# 2. BatteryDesign (Top Level): O resultado final que combina subpacks


class BatteryDesign(BaseModel):
    # Lista de tuplas [Modelo, %Energia, %Potencia]
    multiChemistry: List[Tuple[str, float, float]]
    battery_energy: float
    continuous_power: float
    total_price: float
    battery_weight: float
    safety_score: float
    durability_score: float
    subpacks: List[Configuration]  # Aqui está a lista hierárquica
    financial_KPIs: Optional[dict] = None

# 3. DesignResponse: A resposta final da API


class DesignResponse(BaseModel):
    # Agora usa a estrutura nova BatteryDesign
    results: List[BatteryDesign]
    plotResults: List[BatteryDesign]  # Mesma coisa
    total: int
    stats: Optional[dict] = None
