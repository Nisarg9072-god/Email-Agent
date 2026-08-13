"""Alternative entry point: python run_agent.py

Runs the agent in continuous mode — polls inbox, replies, then repeats until Ctrl+C.
"""

from app.config import get_settings
from app.db.database import Database
from app.main import run_continuous, setup_logging


if __name__ == "__main__":
    settings = get_settings()
    setup_logging(settings.log_level)
    db = Database(settings.database_url)
    run_continuous(settings, db)
