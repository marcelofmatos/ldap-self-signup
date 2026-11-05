import logging

from . import create_app
from .config import carregar_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
app = create_app(carregar_config())
