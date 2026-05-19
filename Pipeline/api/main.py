from fastapi import FastAPI
from contextlib import asynccontextmanager
from Pipeline.database.db import init_db
from Pipeline.api.routes import customers, blast, promo_codes, analytics


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

app.include_router(customers.router, prefix="/customers", tags=["Customers"])
app.include_router(blast.router, prefix="/blast", tags=["Blast"])
app.include_router(promo_codes.router, prefix="/promo-codes", tags=["Promo Codes"])
app.include_router(analytics.router, prefix="/analytics", tags=["Analytics"])
