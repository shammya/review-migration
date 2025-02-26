# config.py
"""Configuration settings for the review migration process."""

import logging

# MySQL Configuration
MYSQL_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "mysqlMAC79",
    "database": "local_questtag",
}

# PostgreSQL Configuration
POSTGRES_CONFIG = {
    "host": "localhost",
    "user": "myuser",
    "password": "mypassword",
    "database": "default_db",
    "port": "5432",
}

# CSV File Path
EXISTING_ORDER_IDS_CSV = "existing_order_ids.csv"

# Batch size for processing rows
BATCH_SIZE = 1000

# Operations per second (for rate limiting)
OPERATIONS_PER_SECOND = 10

# Logging configuration
LOG_FILE = "review_migration.log"
LOG_LEVEL = logging.INFO

# If True, store timestamps as milliseconds since epoch, otherwise seconds
TIMESTAMP_IN_MS = False
