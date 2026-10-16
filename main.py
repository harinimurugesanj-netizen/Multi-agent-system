import logging

from fastapi import FastAPI
from router.ai_router import ai_router


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s"
)

logger = logging.getLogger(__name__)


app = FastAPI()

app.include_router(ai_router)