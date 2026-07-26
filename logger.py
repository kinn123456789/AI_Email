import logging
import os
from logging.handlers import RotatingFileHandler

# Kept as a local file (not just stdout) so this isn't dependent on
# whichever host happens to be capturing stdout right now — portable to
# any future hosting setup. RotatingFileHandler caps it at 5MB x 3 backup
# files instead of the plain FileHandler this replaced, which had no size
# limit and would have grown forever between deploys.
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[
        RotatingFileHandler(f"{LOG_DIR}/app.log", maxBytes=5_000_000, backupCount=3),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger("ai_email")