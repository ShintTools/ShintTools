# core/api/routes/health.py

# APIRouter nos permite crear un grupo de ventanillas
from fastapi import APIRouter

# Creamos el router (agrupador de ventanillas) para health
router = APIRouter()


# Esta ventanilla responde a GET /status
# Cuando el plugin pregunta "¿estás vivo?" esto es lo que responde
@router.get("/status")
async def get_status():
    return {
        "status": "ok",
        "version": "0.1.0",
        # TODO Sprint 4: añadir módulos reales cuando estén listos
        "modules": [],
    }
