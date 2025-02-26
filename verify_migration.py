# verify_migration.py
"""Module for verifying the success of the review migration process."""

import logging
import time
import argparse
import random

import mysql.connector
import psycopg2
from psycopg2.extras import DictCursor

import config
from database import DatabaseManager


def setup_logging(log_level=None):
    """
    Set up logging configuration.

    Args:
        log_level: Optional override for log level

    Returns:
        Configured logger
    """
    level = log_level if log_level else config.LOG_LEVEL
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.FileHandler("verify_migration.log"), logging.StreamHandler()],
    )
    return logging.getLogger(__name__)


def parse_args():
    """
    Parse command-line arguments.

    Returns:
        Parsed arguments
    """
    parser = argparse.ArgumentParser(description="Verify review migration")
    parser.add_argument(
        "--samples", type=int, default=10, help="Number of random samples to check"
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )
    return parser.parse_args()


def verify_migration():
    """Main function to verify the migration success."""
    # Parse arguments
    args = parse_args()
    log_level = getattr(logging, args.log_level)

    # Set up logging
    logger = setup_logging(log_level)
    logger.info("Starting migration verification")

    # Initialize database manager
    db_manager = DatabaseManager()

    # Connect to databases
    if not db_manager.connect_mysql():
        logger.error("Failed to connect to MySQL database. Exiting.")
        return

    if not db_manager.connect_postgres():
        logger.error("Failed to connect to PostgreSQL database. Exiting.")
        db_manager.close_connections()
        return

    try:
        # Count records in PostgreSQL
        pg_count = db_manager.get_total_review_count()

        # Count records in MySQL
        mysql_cursor = db_manager.mysql_conn.cursor()
        mysql_cursor.execute("SELECT COUNT(*) FROM review_analysis")
        mysql_count = mysql_cursor.fetchone()[0]
        mysql_cursor.close()

        logger.info(f"PostgreSQL review count: {pg_count}")
        logger.info(f"MySQL review_analysis count: {mysql_count}")
        logger.info(
            f"Coverage: {(mysql_count / pg_count * 100) if pg_count > 0 else 0:.2f}%"
        )

        # Sample check: compare a few random records
        pg_cursor = db_manager.postgres_conn.cursor(cursor_factory=DictCursor)
        query = f"""
            SELECT order_id, order_number, order_type, review_time 
            FROM review 
            ORDER BY random() 
            LIMIT {args.samples}
        """
        pg_cursor.execute(query)
        sample_records = pg_cursor.fetchall()
        pg_cursor.close()

        logger.info(f"Checking {len(sample_records)} sample records:")
        matches = 0
        mismatches = 0
        missing = 0

        for record in sample_records:
            mysql_cursor = db_manager.mysql_conn.cursor()
            query = """
                SELECT id, order_id, order_number, review_time 
                FROM review_analysis 
                WHERE order_id = %s AND order_type = %s
            """
            mysql_cursor.execute(query, (record["order_id"], record["order_type"]))
            mysql_record = mysql_cursor.fetchone()
            mysql_cursor.close()

            if mysql_record:
                # Convert postgres timestamp to unix timestamp for comparison
                pg_time = int(time.mktime(record["review_time"].timetuple()))
                if config.TIMESTAMP_IN_MS:
                    pg_time *= 1000  # Convert to milliseconds

                if pg_time == mysql_record[3]:
                    matches += 1
                    logger.info(f"✓ Order ID {record['order_id']}: Match")
                else:
                    mismatches += 1
                    logger.warning(
                        f"✗ Order ID {record['order_id']}: Mismatch - "
                        f"PostgreSQL time={pg_time}, MySQL time={mysql_record[3]}"
                    )
            else:
                missing += 1
                logger.warning(f"! Order ID {record['order_id']}: Not found in MySQL")

        # Print summary
        logger.info("Verification summary:")
        logger.info(f"  Matches: {matches}")
        logger.info(f"  Mismatches: {mismatches}")
        logger.info(f"  Missing: {missing}")
        logger.info(f"  Success rate: {(matches / args.samples * 100):.2f}%")

    except Exception as e:
        logger.error(f"Error during verification: {e}", exc_info=True)
    finally:
        db_manager.close_connections()
        logger.info("Verification completed")


if __name__ == "__main__":
    verify_migration()
