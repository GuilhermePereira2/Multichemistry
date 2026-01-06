# python run_all.py

import subprocess
import sys
import time

# Caminhos para os scripts
backend_script = "main.py"
ui_script = "ui.py"

# Comando para correr backend
backend_cmd = [sys.executable, backend_script]

# Comando para correr Streamlit UI
ui_cmd = [sys.executable, "-m", "streamlit", "run", ui_script]

# Iniciar backend
print("🔹 Starting backend...")
backend_proc = subprocess.Popen(backend_cmd)

# Dar um pequeno delay para o backend iniciar antes do UI
time.sleep(2)

# Iniciar UI
print("🔹 Starting Streamlit UI...")
ui_proc = subprocess.Popen(ui_cmd)

try:
    # Espera pelos dois processos
    backend_proc.wait()
    ui_proc.wait()
except KeyboardInterrupt:
    print("\n🔹 Interrompendo ambos os processos...")
    backend_proc.terminate()
    ui_proc.terminate()
