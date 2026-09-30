from contextlib import asynccontextmanager
from fastapi import FastAPI
import app.routes.chat as routes
import app.config as config
from app.routes import chat, session, perfil
from app.config import FRONTEND_DIR
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
FRONTEND_URL = FRONTEND_DIR  / "index.html"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Cria índices do Mongo sem derrubar o boot se ele estiver fora.
    # Sem isso, o Render marcava o deploy como failed no handshake TLS.
    try:
        from app.mongo import ensure_indexes
        ensure_indexes()
    except Exception:
        pass
    yield


app = FastAPI(
    title="My FastAPI Application",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health() -> dict:
    try:
        from app.mongo import ping_mongo
        mongo_ok = ping_mongo()
    except Exception:
        mongo_ok = False
    return {"status": "ok", "mongo_ok": mongo_ok, "problema_configuração" : config.validar_config()}

app.include_router(routes.router)

app.include_router(chat.router)
app.include_router(session.router) 
app.include_router(perfil.router)

if (FRONTEND_URL).exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
else:
    @app.get("/")
    def raiz() -> dict:
        return {"message": "Frontend não encontrado. Rode o build do frontend ou configure FRONTEND_DIR corretamente."}