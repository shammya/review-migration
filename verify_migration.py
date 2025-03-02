# verify_migration.py
"""Module for verifying the success of the review migration process."""

import logging
import time
import argparse
import json
import random
import datetime
from typing import Dict, Any, List, Tuple, Union
from venv import logger

import mysql.connector
import psycopg2
from psycopg2.extras import DictCursor
from mysql.connector.cursor import MySQLCursor

import config
from config import load_state
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
        "--samples", type=int, default=10, help="Number of entries to check"
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )
    parser.add_argument(
        "--detailed", action="store_true", help="Show detailed field comparison"
    )
    parser.add_argument(
        "--verify-specific",
        type=int,
        nargs="+",
        help="Verify specific order_ids instead of recently migrated entries",
    )
    parser.add_argument(
        "--random",
        action="store_true",
        help="Select random samples instead of recently migrated entries",
    )
    return parser.parse_args()


def convert_pg_time_to_unix(pg_timestamp) -> int:
    """
    Convert PostgreSQL timestamp to Unix timestamp.

    Args:
        pg_timestamp: PostgreSQL timestamp

    Returns:
        Unix timestamp in seconds
    """
    return int(time.mktime(pg_timestamp.timetuple()))


def get_mysql_record(
    mysql_cursor: MySQLCursor, order_id: int, order_type: str
) -> Dict[str, Any]:
    """
    Get a record from MySQL based on order_id and order_type.

    Args:
        mysql_cursor: MySQL cursor
        order_id: Order ID to search for
        order_type: Order type to search for

    Returns:
        Dictionary with MySQL record or None if not found
    """
    query = """
        SELECT * FROM review_analysis 
        WHERE order_id = %s AND order_type = %s
    """
    mysql_cursor.execute(query, (order_id, order_type))
    columns = [col[0] for col in mysql_cursor.description]
    record = mysql_cursor.fetchone()

    if not record:
        return None

    return dict(zip(columns, record))


def compare_records(
    pg_record: Dict[str, Any],
    mysql_record: Dict[str, Any],
    logger: logging.Logger,
    detailed: bool = False,
) -> Tuple[bool, Dict[str, bool]]:
    """
    Compare PostgreSQL and MySQL records for equality.

    Args:
        pg_record: PostgreSQL record
        mysql_record: MySQL record
        logger: Logger instance
        detailed: Whether to log detailed field comparisons

    Returns:
        Tuple of (overall match, field_matches dictionary)
    """
    field_mappings = {
        # PostgreSQL field -> MySQL field
        "order_id": "order_id",
        "order_number": "order_number",
        "company_id": "company_id",
        "rating": "food_rating",
        "review": "review_text",
        "driver_rating": "driver_rating",
        "carrier_id": "carrier_id",
        "carrier_name": "driver_name",
        "order_type": "order_type",
        "sentiment": "review_analysis",
        "review_time": "review_time",
    }

    field_matches = {}
    all_fields_match = True

    for pg_field, mysql_field in field_mappings.items():
        # Skip fields that don't exist in either record
        if pg_field not in pg_record or mysql_field not in mysql_record:
            if detailed:
                logger.warning(
                    f"Field missing - PG: {pg_field in pg_record}, MySQL: {mysql_field in mysql_record}"
                )
            continue

        pg_value = pg_record[pg_field]
        mysql_value = mysql_record[mysql_field]

        # Special case for timestamps
        if pg_field == "review_time":
            pg_unix = convert_pg_time_to_unix(pg_value)

            # Check if MySQL value is in milliseconds or seconds
            mysql_timestamp = mysql_value

            # If the MySQL timestamp is significantly larger than the PostgreSQL one,
            # it's likely in milliseconds and we need to convert
            if mysql_timestamp > 10000000000:  # Timestamps in ms are typically > 10^10
                mysql_timestamp = mysql_timestamp // 1000

            match = abs(pg_unix - mysql_timestamp) <= 1  # Allow 1 second tolerance

            if not match and detailed:
                logger.warning(
                    f"  Timestamp comparison: PG Unix={pg_unix}, MySQL={mysql_timestamp}"
                )
                logger.warning(f"  Original values: PG={pg_value}, MySQL={mysql_value}")

        # Special case for sentiment/review_analysis JSON comparison
        elif pg_field == "sentiment":
            if isinstance(pg_value, str):
                pg_json = json.loads(pg_value)
            else:
                pg_json = pg_value

            if isinstance(mysql_value, str):
                mysql_json = json.loads(mysql_value)
            else:
                mysql_json = mysql_value

            # Compare JSON structures (simplified)
            # In a real scenario, you might want a more sophisticated comparison
            try:
                match = (
                    pg_json.get("sentiment") == mysql_json.get("sentiment")
                    and pg_json.get("food", {}).get("sentiment")
                    == mysql_json.get("food", {}).get("sentiment")
                    and pg_json.get("delivery_process", {}).get("sentiment")
                    == mysql_json.get("delivery_process", {}).get("sentiment")
                )
            except (AttributeError, TypeError):
                match = False

        # Default case: direct comparison
        else:
            match = pg_value == mysql_value

        field_matches[f"{pg_field} -> {mysql_field}"] = match

        if not match and detailed:
            logger.warning(f"Mismatch for {pg_field} -> {mysql_field}:")
            logger.warning(f"  PostgreSQL: {pg_value}")
            logger.warning(f"  MySQL: {mysql_value}")

        all_fields_match = all_fields_match and match

    return all_fields_match, field_matches


def get_specific_pg_records(pg_cursor, order_ids: List[int]) -> List[Dict[str, Any]]:
    """
    Get specific PostgreSQL records by order_id.

    Args:
        pg_cursor: PostgreSQL cursor
        order_ids: List of order IDs to retrieve

    Returns:
        List of PostgreSQL records
    """
    records = []
    for order_id in order_ids:
        query = "SELECT * FROM review WHERE order_id = %s"
        pg_cursor.execute(query, (order_id,))
        row = pg_cursor.fetchone()
        if row:
            records.append(dict(row))
        else:
            logger.warning(f"Order ID {order_id} not found in PostgreSQL")

    return records


def get_random_migrated_records(
    pg_cursor, last_order_id: int, limit: int
) -> List[Dict[str, Any]]:
    """
    Get randomly selected records that have already been migrated (order_id <= last_order_id).

    Args:
        pg_cursor: PostgreSQL cursor
        last_order_id: The last order_id that was processed
        limit: Maximum number of records to retrieve

    Returns:
        List of PostgreSQL records randomly selected from migrated entries
    """
    # Fetch records that have already been migrated (order_id <= last_order_id)
    # but in random order to get a good sample across the entire migrated set

    query = """
        SELECT * FROM review 
        WHERE order_id <= %s
        ORDER BY random()
        LIMIT %s
    """
    pg_cursor.execute(query, (last_order_id, limit))
    records = pg_cursor.fetchall()

    migrated_records = [dict(record) for record in records]

    logger.info(
        f"Retrieved {len(migrated_records)} randomly selected migrated records "
        f"(order_id <= {last_order_id})"
    )

    return migrated_records


def verify_migration():
    """Main function to verify the migration success."""
    # Parse arguments
    args = parse_args()
    log_level = getattr(logging, args.log_level)

    # Set up logging
    logger = setup_logging(log_level)
    logger.info("Starting comprehensive migration verification")
    logger.info(f"Current time: {datetime.datetime.now()}")

    # Log verification mode
    if args.verify_specific:
        logger.info(f"Verification mode: Specific order IDs provided by user")
    elif args.random:
        logger.info(f"Verification mode: Random sampling across all records")
    else:
        logger.info(f"Verification mode: Random sampling of migrated records only")

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
        # Statistics counters
        total_matches = 0
        total_mismatches = 0
        missing_records = 0
        field_match_stats = {}

        # Get samples from PostgreSQL
        pg_cursor = db_manager.postgres_conn.cursor(cursor_factory=DictCursor)
        mysql_cursor = db_manager.mysql_conn.cursor()

        # Determine which records to check
        if args.verify_specific:
            # Verify specific order IDs provided by the user
            logger.info(f"Verifying specific order IDs: {args.verify_specific}")
            pg_samples = get_specific_pg_records(pg_cursor, args.verify_specific)
            sample_count = len(args.verify_specific)  # For percentage calculations
        elif args.random:
            # Use completely random sampling across all records
            logger.info(f"Selecting {args.samples} random samples from all records")
            query = f"""
                SELECT * FROM review 
                ORDER BY random() 
                LIMIT {args.samples}
            """
            pg_cursor.execute(query)
            pg_samples = pg_cursor.fetchall()
            sample_count = args.samples
        else:
            # Default: Use random sampling from already migrated entries
            migration_state = load_state()
            last_order_id = migration_state.get("last_order_id", 0)

            if last_order_id > 0:
                logger.info(
                    f"Selecting {args.samples} random samples from migrated records (order_id <= {last_order_id})"
                )
                pg_samples = get_random_migrated_records(
                    pg_cursor, last_order_id, args.samples
                )
                sample_count = args.samples
            else:
                logger.warning(
                    "No migration state found. Falling back to random sampling across all records."
                )
                query = f"""
                    SELECT * FROM review 
                    ORDER BY random() 
                    LIMIT {args.samples}
                """
                pg_cursor.execute(query)
                pg_samples = pg_cursor.fetchall()
                sample_count = args.samples

        logger.info(f"Fetched {len(pg_samples)} records for verification")

        # Compare each sample with its MySQL counterpart
        for i, pg_record in enumerate(pg_samples, 1):
            order_id = pg_record["order_id"]
            order_type = pg_record["order_type"]

            logger.info(f"\nSample {i}: Order ID {order_id} ({order_type})")

            # Get corresponding MySQL record
            mysql_record = get_mysql_record(mysql_cursor, order_id, order_type)

            if not mysql_record:
                logger.warning(
                    f"Record not found in MySQL for order_id={order_id}, order_type={order_type}"
                )
                missing_records += 1
                continue

            # Compare records
            record_matches, field_matches = compare_records(
                dict(pg_record), mysql_record, logger, args.detailed
            )

            # Update field statistics
            for field, matches in field_matches.items():
                if field not in field_match_stats:
                    field_match_stats[field] = {"matches": 0, "mismatches": 0}

                if matches:
                    field_match_stats[field]["matches"] += 1
                else:
                    field_match_stats[field]["mismatches"] += 1

            # Update overall statistics
            if record_matches:
                total_matches += 1
                logger.info("✓ Records match completely")
            else:
                total_mismatches += 1
                logger.warning("✗ Records have differences")

                # Print field match summary if not in detailed mode
                if not args.detailed:
                    for field, matches in field_matches.items():
                        status = "✓" if matches else "✗"
                        logger.info(f"  {status} {field}")

        # Close cursors
        pg_cursor.close()
        mysql_cursor.close()

        # Print summary statistics
        logger.info("\n" + "=" * 50)
        logger.info("VERIFICATION SUMMARY")
        logger.info("=" * 50)
        logger.info(f"Total records checked: {len(pg_samples)}")

        if pg_samples:
            match_percentage = total_matches / len(pg_samples) * 100
            mismatch_percentage = total_mismatches / len(pg_samples) * 100
            missing_percentage = missing_records / sample_count * 100

            logger.info(f"Complete matches: {total_matches} ({match_percentage:.2f}%)")
            logger.info(
                f"Records with differences: {total_mismatches} ({mismatch_percentage:.2f}%)"
            )
            logger.info(
                f"Missing records: {missing_records} ({missing_percentage:.2f}%)"
            )

            # Field match statistics
            if field_match_stats:
                logger.info("\nField match statistics:")
                for field, stats in field_match_stats.items():
                    total = stats["matches"] + stats["mismatches"]
                    if total > 0:
                        match_percentage = stats["matches"] / total * 100
                        logger.info(
                            f"  {field}: {stats['matches']}/{total} ({match_percentage:.2f}%)"
                        )

            # Final assessment
            if total_matches == len(pg_samples):
                logger.info(
                    "\n✓ MIGRATION VERIFIED SUCCESSFULLY: All sampled records match perfectly"
                )
            elif total_matches + missing_records == sample_count:
                logger.warning(
                    "\n! MIGRATION INCOMPLETE: Some records are missing from MySQL"
                )
            else:
                logger.error(
                    "\n✗ MIGRATION HAS DISCREPANCIES: Some records were migrated incorrectly"
                )
        else:
            logger.warning("No records were processed for verification")

    except Exception as e:
        logger.error(f"Error during verification: {e}", exc_info=True)
    finally:
        db_manager.close_connections()
        logger.info("Verification completed")


if __name__ == "__main__":
    verify_migration()
