import math
# Removemos o lru_cache para evitar erros de "unhashable type: dict"
from typing import List, Dict, Optional, Tuple, Any
from models import Requirements, CellData, Fuse, Relay, Cable, Bms, Shunt, Configuration, Dimensions, SafetyAssessment

# --- CONSTANTES DE SEGURANÇA E FÍSICA ---
HEIGHT_MARGIN_MM = 30.0
SPACING_THICKNESS_MM = 0.2
SPACING_WIDTH_MM = 0.2
CABLE_TEMP_MAX = 100
RHO_E_COPPER = 1.68e-8
DEFAULT_CABLE_LENGTH_M = 2
THERMAL_RESISTANCE = 0.5
MIN_DELTA_T = 1.0
FUSE_CURRENT_FACTOR = 1.5
RELAY_VOLTAGE_FACTOR = 1.1
RELAY_CURRENT_FACTOR = 2.0

# --- FUNÇÕES AUXILIARES ---


def get_integer_factors(n: int) -> List[Tuple[int, int]]:
    """Retorna pares de fatores (x, y) tal que x * y = n. Otimizado."""
    factors = []
    for i in range(1, int(math.isqrt(n)) + 1):
        if n % i == 0:
            factors.append((i, n // i))
    return factors

# Helper para converter objetos Pydantic em Dicionários


def to_dict(item):
    if hasattr(item, 'model_dump'):
        return item.model_dump()  # Pydantic v2
    if hasattr(item, 'dict'):
        return item.dict()  # Pydantic v1
    return item  # Já é dict

# Removemos @lru_cache aqui pois dicts não são "hashable"


def select_component_fast(components_list: List[dict], voltage_req: float, current_req: float) -> Optional[dict]:
    """Seleciona o primeiro componente compatível (assumindo lista ordenada por preço)."""
    for c in components_list:
        # Garante que lemos como dict
        vdc = c.get('vdc_max', 0)
        a_max = c.get('a_max', 0)

        if vdc >= voltage_req and a_max >= current_req:
            return c
    return None


def select_bms_fast(bms_list: List[dict], series_cells: int, max_current: float) -> Optional[dict]:
    """Lógica específica para BMS."""
    for b in bms_list:
        max_cells = b.get('max_cells', 0)
        a_max = b.get('a_max', 0)

        if max_cells >= series_cells and a_max >= max_current:
            return b
    return None


def select_cable_fast(cables_list: List[dict], i_peak: float, v_max: float, t_amb: float) -> Optional[dict]:
    """Cálculo térmico de cabos."""
    delta_T = CABLE_TEMP_MAX - t_amb
    if delta_T <= 0:
        delta_T = MIN_DELTA_T

    A_m2 = (pow(i_peak, 2) * RHO_E_COPPER *
            pow(DEFAULT_CABLE_LENGTH_M, 2) * THERMAL_RESISTANCE) / delta_T
    A_mm2_calc = A_m2 * 1e6

    for c in cables_list:
        section = c.get('section', 0)
        vdc = c.get('vdc_max', 0)
        a_max = c.get('a_max', 0)

        # section >= A_mm2_calc and vdc >= v_max and
        if a_max >= i_peak:
            # Retorna uma cópia modificada com o preço calculado
            return {
                "brand": c.get('brand', ''),
                "model": f"{c.get('model', '')} {c.get('model_suffix', '')}".strip(),
                "section": section,
                "vdc_max": vdc,
                "a_max": a_max,
                "temp_min": c.get('temp_min', 0),
                "temp_max": c.get('temp_max', 0),
                # Preço por 2 metros
                "price": c.get('price', 0) * DEFAULT_CABLE_LENGTH_M * 2,
                "link": c.get('link', '')
            }
    return None


def config_geometry_validation_fast(cell: CellData, series: int, parallel: int, max_x: float, max_y: float) -> bool:
    """Validação geométrica rápida usando fatorização."""
    total_cells = series * parallel
    e_cell_spacing = cell.Cell_Thickness + SPACING_THICKNESS_MM
    l_cell_spacing = cell.Cell_Width + SPACING_WIDTH_MM

    factors = get_integer_factors(total_cells)
    dim_ops = [(e_cell_spacing, l_cell_spacing),
               (l_cell_spacing, e_cell_spacing)]

    for dim_x, dim_y in dim_ops:
        for nx, ny in factors:
            if (nx * dim_x <= max_x) and (ny * dim_y <= max_y):
                return (nx, ny)
            if (ny * dim_x <= max_x) and (nx * dim_y <= max_y):
                return (ny, nx)
    return False


def assess_safety(req: Requirements, cell: CellData, config_values: dict) -> SafetyAssessment:
    warnings = []
    recs = []
    score = 100
    is_safe = True

    req_current = config_values['continuous_current']

    # Capacidade total do pack em Ah
    pack_capacity_ah = (cell.Capacity / 1000) * config_values['parallel_cells']

    # C-rate efetivo
    actual_c_rate = req_current / pack_capacity_ah if pack_capacity_ah > 0 else 999
    limit_continuous = cell.MaxContinuousDischargeRate

    # 1. Verificação de Corrente
    if actual_c_rate > limit_continuous:
        warnings.append("DANGER: Current exceeds cell limits. Fire risk.")
        score = 0
        is_safe = False
    elif actual_c_rate > (limit_continuous * 0.8):
        warnings.append(
            f"Warning: High Load ({actual_c_rate:.2f}C). Cells need cooling.")
        score -= 50
        recs.append("Add spacing (min 2mm) between cells.")
    elif actual_c_rate > (limit_continuous * 0.7):
        warnings.append(
            f"Warning: High Load ({actual_c_rate:.2f}C). Cells need cooling.")
        score -= 40
        recs.append("Add spacing (min 2mm) between cells.")
    elif actual_c_rate > (limit_continuous * 0.6):
        warnings.append(
            f"Warning: High Load ({actual_c_rate:.2f}C).")
        score -= 20
        recs.append("Add spacing (min 1mm) between cells.")
    elif actual_c_rate > (limit_continuous * 0.5):
        score -= 10
        recs.append("Add spacing (min 0.5mm) between cells.")

    # 2. Verificação de Tensão
    if config_values['voltage'] > 90:
        score -= 40
        warnings.append("Very High Voltage (>90V): Severe shock risk.")
        recs.append("Use isolated connectors and protective casing.")
    elif config_values['voltage'] > 60:
        score -= 20
        warnings.append("High Voltage (>60V): Lethal shock risk.")
        recs.append("Use isolated connectors.")

    if score < 0:
        score = 0

    return SafetyAssessment(
        is_safe=is_safe,
        safety_score=score,
        warnings=warnings,
        recommendations=recs
    )

# --- MOTOR DE CÁLCULO PRINCIPAL ---


def compute_cell_configurations(req: Any, cell_catalogue: List[CellData], component_db: Dict[str, List[Any]]) -> Dict[str, Any]:
    configs: List[Configuration] = []

    # 1. SANITIZAÇÃO: Converte TUDO para dicionários simples para evitar erros de 'AttributeError'
    raw_fuses = [to_dict(x) for x in component_db.get('fuses', [])]
    raw_relays = [to_dict(x) for x in component_db.get('relays', [])]
    raw_shunts = [to_dict(x) for x in component_db.get('shunts', [])]
    raw_bms = [to_dict(x) for x in component_db.get('bms', [])]
    raw_cables = [to_dict(x) for x in component_db.get('cables', [])]

    # 2. ORDENAÇÃO: Agora seguro usar .get()
    sorted_fuses = sorted(
        raw_fuses, key=lambda x: x.get('price', float('inf')))
    sorted_relays = sorted(
        raw_relays, key=lambda x: x.get('price', float('inf')))
    sorted_shunts = sorted(
        raw_shunts, key=lambda x: x.get('price', float('inf')))
    sorted_bms = sorted(raw_bms, key=lambda x: x.get(
        'master_price', float('inf')))
    sorted_cables = sorted(
        raw_cables, key=lambda x: x.get('section', float('inf')))

    stats = {
        "totalAttempts": 0, "validConfigurations": 0
    }

    print(f"Starting calculation with {len(cell_catalogue)} cells...")

    for cell in cell_catalogue:
        # Check Altura
        if (cell.Cell_Height + HEIGHT_MARGIN_MM) > req.max_height:
            continue

        min_series = math.ceil(req.min_voltage / (cell.NominalVoltage-0.7))
        max_series = math.floor(req.max_voltage / (cell.ChargeVoltage))

        if min_series > max_series:
            continue

        for series in range(min_series, max_series + 1):
            bat_voltage = series * cell.NominalVoltage
            max_voltage = series * cell.ChargeVoltage

            # Estimativa de Parallel
            cell_power = (cell.Capacity * 1e-3 *
                          cell.MaxContinuousDischargeRate) * cell.NominalVoltage
            min_p_power = math.ceil(
                req.min_continuous_power / (series * cell_power)) if cell_power > 0 else 1
            start_p = max(min_p_power, 1)

            for parallel in range(start_p, 5):  # Limite aumentado para teste
                stats["totalAttempts"] += 1

                # --- SAFETY CHECK ---
                cont_current = req.min_continuous_power / bat_voltage
                cont_current_pack = max(cont_current, cell.Capacity * 1e-3 *
                                        cell.MaxContinuousDischargeRate*parallel)

                safety = assess_safety(req, cell, {
                    'continuous_current': cont_current,
                    'parallel_cells': parallel,
                    'voltage': bat_voltage
                })

                if not safety.is_safe:
                    continue
                # --------------------

                total_cells = series * parallel
                bat_weight = (cell.Weight * 1e-3) * total_cells

                if bat_weight > (req.max_weight*0.7):
                    continue

                layout = config_geometry_validation_fast(
                    cell, series, parallel, req.max_width, req.max_length)
                if not layout:
                    continue

                # Componentes
                peak_current = (cell.Capacity * 1e-3 *
                                cell.MaxContinuousDischargeRate) * parallel * 5

                # fuse = select_component_fast(
                #    sorted_fuses, max_voltage, cont_current_pack * FUSE_CURRENT_FACTOR)
                # if not fuse:
                #    continue

                # relay = select_component_fast(
                #    sorted_relays, max_voltage * RELAY_VOLTAGE_FACTOR, cont_current_pack * RELAY_CURRENT_FACTOR)
                # if not relay:
                #    continue

                # cable = select_cable_fast(
                #    sorted_cables, cont_current_pack, max_voltage, req.ambient_temp)
                # if not cable:
                #    continue

                # bms = select_bms_fast(sorted_bms, series, peak_current)
                # if not bms:
                #    continue

                # shunt = select_component_fast(
                #    sorted_shunts, max_voltage, peak_current)
                # if not shunt:
                #    continue

                # Preço
                cells_cost = cell.Price * total_cells
                total_price = cells_cost

                if total_price > req.max_price:
                    continue

                bat_capacity = (cell.Capacity * 1e-3) * parallel

                # Instanciar Configuration (Validando com **dict)
                config = Configuration(
                    cell=cell,
                    series_cells=series,
                    parallel_cells=parallel,
                    battery_voltage=round(bat_voltage, 1),
                    battery_capacity=round(bat_capacity, 1),
                    battery_energy=round(bat_voltage * bat_capacity),
                    battery_weight=round(bat_weight, 1),
                    battery_impedance=round(
                        ((cell.Impedance * 1e-3) * series) / parallel, 3),
                    continuous_power=round(bat_voltage * cont_current),
                    peak_power=round(bat_voltage * peak_current),
                    cell_price=round(cells_cost, 2),
                    # fuse=Fuse(**fuse),
                    # relay=Relay(**relay),
                    # cable=Cable(**cable),
                    # bms=Bms(
                    #    brand=bms.get('brand', 'Generic'),
                    #    model=bms.get('model', 'Unknown'),
                    #    max_cells=bms.get('max_cells', 0),
                    #    vdc_min=bms.get('vdc_min', 0),
                    #    vdc_max=bms.get('vdc_max', 0),
                    #    a_max=bms.get('a_max', 0),
                    # --- FIX: Adicionar defaults para temperatura ---
                    #    temp_min=bms.get('temp_min', -20),  # Default seguro
                    #    temp_max=bms.get('temp_max', 60),  # Default seguro
                    # -----------------------------------------------
                    #    master_price=bms.get('master_price', 0),
                    #    slave_price=bms.get('slave_price', 0),
                    #    link=bms.get('link', '')
                    # ),
                    # shunt=Shunt(**shunt),
                    total_price=round(total_price, 2),
                    dimensions=Dimensions(
                        length=round((cell.Cell_Width + SPACING_WIDTH_MM)
                                     * math.ceil(math.sqrt(total_cells)), 1),
                        width=round((cell.Cell_Thickness + SPACING_THICKNESS_MM)
                                    * math.ceil(math.sqrt(total_cells)), 1),
                        height=round(cell.Cell_Height, 1)
                    ),
                    safety=safety,
                    layout=layout,
                    # affiliate_link=""
                )
                configs.append(config)

    configs.sort(key=lambda x: x.total_price /
                 x.battery_energy if x.battery_energy > 0 else 0, reverse=True)

    return {
        "results": configs[:30],
        "plotResults": configs,
        "total": len(configs),
        "stats": stats if req.debug else None
    }
