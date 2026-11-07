import os
import sys

# Set directory to project path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# Bridge FastAPI (ASGI) to cPanel Passenger (WSGI)
from a2wsgi import ASGIMiddleware
from app import app as fastapi_app

# Passenger WSGI entry point
application = ASGIMiddleware(fastapi_app)

