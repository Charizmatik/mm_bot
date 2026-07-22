from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import router
from app.config import get_settings
from app.exchanges.mexc import MexcExchange
from app.exchanges.paper import PaperExchange
from app.services.engine import MarketMakerEngine


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    def mexc_exchange() -> MexcExchange:
        return MexcExchange(
            settings.mexc_api_key,
            settings.mexc_api_secret,
            recv_window_ms=settings.mexc_recv_window_ms,
            time_sync_interval_seconds=settings.mexc_time_sync_interval_seconds,
        )

    if settings.dry_run:
        balance_source = (
            mexc_exchange()
            if settings.mexc_api_key and settings.mexc_api_secret
            else None
        )
        exchange = PaperExchange(balance_source=balance_source, maker_fee_pct=settings.paper_maker_fee_pct)
    else:
        exchange = mexc_exchange()
    app.state.engine = MarketMakerEngine(exchange, settings)
    await app.state.engine.start()
    yield
    await app.state.engine.stop()


app = FastAPI(title="Inventory Market Maker", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
