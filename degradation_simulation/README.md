# Industrial Energy Dataset – DE_KN_industrial2

Este repositório contém dados de energia elétrica de um edifício industrial pertencente a uma empresa do setor de artesanato (**crafts sector**) localizada na Alemanha.

## Estrutura do Dataset

O arquivo CSV contém séries temporais com medições de consumo, geração fotovoltaica e operação de armazenamento de energia (bateria).

### Colunas

- **`utc_timestamp`**  
  Timestamp em UTC (Tempo Universal Coordenado).

- **`cet_cest_timestamp`**  
  Timestamp no fuso horário local da Europa Central (CET/CEST).

- **`interpolated`**  
  Indicador se o valor foi interpolado (`1`) ou medido diretamente (`0`).

- **`DE_KN_industrial2_grid_import`** *(float, kWh)*  
  Energia importada da rede elétrica pública por um edifício industrial de uma empresa do setor de artesanato.

- **`DE_KN_industrial2_pv`** *(float, kWh)*  
  Energia total gerada por painéis fotovoltaicos no edifício industrial.

- **`DE_KN_industrial2_storage_charge`** *(float, kWh)*  
  Energia utilizada para o carregamento da bateria no edifício industrial.

- **`DE_KN_industrial2_storage_decharge`** *(float, kWh)*  
  Energia descarregada da bateria para suprir o consumo do edifício industrial.

## Unidade dos Dados

Todos os valores de energia estão expressos em **quilowatt-hora (kWh)**.

## Observações

- Valores interpolados devem ser tratados com cuidado em análises estatísticas.
- Dependendo do intervalo temporal (ex.: 15 min, 1 h), os valores representam energia acumulada no período.

---

**Prefixo do dataset:** `DE_KN_industrial2`  
- `DE` → Alemanha  
- `KN` → Identificador regional/local  
- `industrial2` → Segunda unidade/instalação industrial monitorada

