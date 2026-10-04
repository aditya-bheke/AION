import os
import tempfile

# Keep test logs out of the working tree.
os.environ.setdefault("SERVICE_LOG_FILE", os.path.join(tempfile.gettempdir(), "orders-service-tests.log"))
