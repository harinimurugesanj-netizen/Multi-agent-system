from fastapi import FastAPI
from router.ai_router import ai_router
from config.logger_config import logging

logger = logging.getLogger(__name__)
app = FastAPI()

app.include_router(ai_router)