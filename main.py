import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List

# Importar Modelos (Inputs/Outputs)
from models import Requirements, Configuration, DesignResponse

# Importar Lógica de Cálculo
from logic import compute_cell_configurations

# --- A GRANDE MUDANÇA ESTÁ AQUI ---
# Em vez de importar listas, importamos a nossa "Base de Dados" viva
from database import db

app = FastAPI(title="BatteryApp Calculator API")

# Configuração CORS (Essencial para o React funcionar)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Permite pedidos do localhost:5173
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def read_root():
    """Endpoint de saúde para verificar se os dados carregaram bem."""
    return {
        "status": "Operational 🚀",
        "database_stats": {
            "cells": len(db.cells),
            "fuses": len(db.components.get("fuses", [])),
            "relays": len(db.components.get("relays", [])),
            "cables": len(db.components.get("cables", []))
        }
    }


@app.post("/calculate", response_model=DesignResponse)
def calculate_endpoint(req: Requirements):
    try:
        res = compute_cell_configurations(
            req,
            db.cells,
            db.components
        )

        return res

    except Exception as e:
        import traceback
        print("❌ Erro crítico no cálculo:")
        traceback.print_exc()   # <---- ATIVAR LOGGING AQUI
        raise HTTPException(status_code=500, detail=str(e))


# --- Endpoint Bónus: Recarregar Dados sem desligar o servidor ---


@app.post("/admin/reload-data")
def reload_data():
    """
    Útil para quando editares o ficheiro .json e quiseres atualizar
    os dados sem ter de parar e arrancar o python.
    """
    try:
        db.reload()
        return {"message": "Base de dados recarregada com sucesso!", "stats": len(db.cells)}
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Erro ao recarregar: {str(e)}")


if __name__ == "__main__":
    # Corre o servidor na porta 8000
    uvicorn.run(app, host="0.0.0.0", port=8000)


#
# python main.py
#
# python -m streamlit run ui.py
