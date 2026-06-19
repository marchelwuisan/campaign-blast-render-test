from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from Pipeline.database.db import init_db
from Pipeline.api.routes import customers, blast, analytics, messaging, dataset, templates, promos, blast_logs


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="WA-Blast API",
    description="WhatsApp blast service for customer retention",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:8501",
        "http://localhost:5173",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(customers.router, prefix="/customers", tags=["Customers"])
app.include_router(blast.router, prefix="/blast", tags=["Blast"])
app.include_router(analytics.router, prefix="/analytics", tags=["Analytics"])
app.include_router(messaging.router, prefix="/messaging", tags=["Messaging"])
app.include_router(dataset.router, prefix="/dataset", tags=["Dataset"])
app.include_router(templates.router, prefix="/templates", tags=["Templates"])
app.include_router(promos.router, prefix="/promo-codes", tags=["Promo codes"])
app.include_router(blast_logs.router, prefix="/blasts", tags=["Dispatch logs"])
