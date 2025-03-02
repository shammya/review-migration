# config.py
"""Configuration settings for the review migration process."""

import json
import os
import logging
from typing import Dict, Any

# MySQL Configuration
MYSQL_CONFIG = {
    "host": "",
    "user": "",
    "password": "",
    "database": "",
}

# PostgreSQL Configuration
POSTGRES_CONFIG = {
    "host": "",
    "user": "",
    "password": "",
    "database": "",
    "port": "5432",
}

# CSV File Path
EXISTING_ORDER_IDS_CSV = "existing_order_ids.csv"

# Batch size for processing rows
BATCH_SIZE = 1000

# Operations per second (for rate limiting)
OPERATIONS_PER_SECOND = 50

# Enable/disable rate limiting
ENABLE_RATE_LIMITING = False

# Logging configuration
LOG_FILE = "review_migration.log"
LOG_LEVEL = logging.INFO

# State file to track progress for resumption
STATE_FILE = "migration_state.json"


def save_state(offset: int, last_order_id: int) -> None:
    """
    Save the current migration state to allow resumption after interruption.

    Args:
        offset: Current offset in the review table
        last_order_id: Last processed order_id
    """
    state = {
        "offset": offset,
        "last_order_id": last_order_id,
        "timestamp": str(import_time()),
    }

    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)
    except Exception as e:
        logging.error(f"Failed to save state: {e}")


def load_state() -> Dict[str, Any]:
    """
    Load the previous migration state.

    Returns:
        Dictionary with the saved state or default values
    """
    default_state = {"offset": 0, "last_order_id": 0, "timestamp": None}

    if not os.path.exists(STATE_FILE):
        return default_state

    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        logging.error(f"Failed to load state: {e}")
        return default_state


def import_time():
    """Import datetime only when needed to avoid circular imports"""
    from datetime import datetime

    return datetime.now()
