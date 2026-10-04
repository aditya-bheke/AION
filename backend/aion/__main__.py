"""`python -m aion` - start the AION server."""
import logging
import os

import uvicorn

from aion.main import create_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

if __name__ == "__main__":
    uvicorn.run(create_app(), host=os.getenv("AION_HOST", "127.0.0.1"), port=int(os.getenv("AION_PORT", "8000")))
