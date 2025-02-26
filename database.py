# database.py
"""Module for managing database connections and operations."""

import time
import logging
from typing import Dict, List, Set, Tuple, Any, Optional

import mysql.connector
import psycopg2
from psycopg2.extras import DictCursor

import config
from rate_limiter import RateLimiter

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Manages database connections and operations for review migration."""

    def __init__(self, dry_run: bool = False):
        """
        Initialize the DatabaseManager.

        Args:
            dry_run: If True, no actual changes will be made to databases
        """
        self.mysql_conn = None
        self.postgres_conn = None
        self.dry_run = dry_run
        self.rate_limiter = RateLimiter(
            operations_per_second=config.OPERATIONS_PER_SECOND
        )

    def connect_mysql(self) -> bool:
        """
        Establish connection to MySQL database.

        Returns:
            True if connection successful, False otherwise
        """
        try:
            self.mysql_conn = mysql.connector.connect(**config.MYSQL_CONFIG)
            logger.info("Connected to MySQL database successfully")
            return True
        except mysql.connector.Error as err:
            logger.error(f"Error connecting to MySQL database: {err}")
            return False

    def connect_postgres(self) -> bool:
        """
        Establish connection to PostgreSQL database.

        Returns:
            True if connection successful, False otherwise
        """
        try:
            self.postgres_conn = psycopg2.connect(**config.POSTGRES_CONFIG)
            logger.info("Connected to PostgreSQL database successfully")
            return True
        except psycopg2.Error as err:
            logger.error(f"Error connecting to PostgreSQL database: {err}")
            return False

    def close_connections(self) -> None:
        """Close all database connections."""
        if self.mysql_conn and self.mysql_conn.is_connected():
            self.mysql_conn.close()
            logger.info("MySQL connection closed")

        if self.postgres_conn and not self.postgres_conn.closed:
            self.postgres_conn.close()
            logger.info("PostgreSQL connection closed")

    def get_total_review_count(self) -> int:
        """
        Get the total number of records in the review table.

        Returns:
            Total count of reviews in PostgreSQL
        """
        try:
            with self.postgres_conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM review")
                count = cursor.fetchone()[0]
                return count
        except psycopg2.Error as err:
            logger.error(f"Error counting reviews in PostgreSQL: {err}")
            return 0

    def fetch_reviews_batch(self, offset: int) -> List[Dict[str, Any]]:
        """
        Fetch a batch of reviews from PostgreSQL.

        Args:
            offset: Starting point for the batch

        Returns:
            List of review records as dictionaries
        """
        try:
            with self.postgres_conn.cursor(cursor_factory=DictCursor) as cursor:
                query = """
                    SELECT 
                        order_id, order_number, company_id, rating, review, 
                        review_time, driver_rating, carrier_id, carrier_name, order_type
                    FROM review
                    ORDER BY order_id
                    LIMIT %s OFFSET %s
                """
                cursor.execute(query, (config.BATCH_SIZE, offset))
                records = [dict(record) for record in cursor.fetchall()]
                return records
        except psycopg2.Error as err:
            logger.error(f"Error fetching reviews from PostgreSQL: {err}")
            return []

    def update_review_time(
        self, order_id: int, order_type: str, review_time: Any
    ) -> bool:
        """
        Update the review_time in the MySQL review_analysis table.

        Args:
            order_id: The order ID to update
            order_type: The type of order
            review_time: The new review time (datetime object)

        Returns:
            True if successful, False otherwise
        """
        if self.dry_run:
            logger.info(f"DRY RUN: Would update review_time for order_id {order_id}")
            return True

        try:
            with self.mysql_conn.cursor() as cursor:
                # Convert timestamp to Unix timestamp
                review_time_unix = int(time.mktime(review_time.timetuple()))
                if config.TIMESTAMP_IN_MS:
                    review_time_unix *= 1000  # Convert to milliseconds

                query = """
                    UPDATE review_analysis
                    SET review_time = %s
                    WHERE order_id = %s AND order_type = %s
                """
                cursor.execute(query, (review_time_unix, order_id, order_type))
                self.mysql_conn.commit()
                affected_rows = cursor.rowcount

                if affected_rows > 0:
                    logger.debug(f"Updated review_time for order_id {order_id}")
                    return True
                else:
                    logger.warning(f"No rows updated for order_id {order_id}")
                    return False
        except mysql.connector.Error as err:
            logger.error(f"Error updating review_time in MySQL: {err}")
            self.mysql_conn.rollback()
            return False

    def insert_review(self, review_data: Dict[str, Any]) -> bool:
        """
        Insert a new review into the MySQL review_analysis table.

        Args:
            review_data: Dictionary containing the review data

        Returns:
            True if successful, False otherwise
        """
        if self.dry_run:
            logger.info(
                f"DRY RUN: Would insert new review for order_id {review_data['order_id']}"
            )
            return True

        try:
            with self.mysql_conn.cursor() as cursor:
                # Prepare the review time as a UNIX timestamp
                review_time_unix = int(
                    time.mktime(review_data["review_time"].timetuple())
                )
                if config.TIMESTAMP_IN_MS:
                    review_time_unix *= 1000  # Convert to milliseconds

                # Set up the query - note we're only inserting non-generated columns
                query = """
                    INSERT INTO review_analysis (
                        company_id, order_id, carrier_id, order_number,
                        driver_name, order_type, food_rating, driver_rating,
                        review_time, review_text
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                """

                # Map the PostgreSQL review data to MySQL columns
                values = (
                    review_data["company_id"],
                    review_data["order_id"],
                    review_data["carrier_id"],
                    review_data["order_number"],
                    review_data["carrier_name"],  # Using carrier_name as driver_name
                    review_data["order_type"],
                    review_data["rating"],  # Using rating as food_rating
                    review_data["driver_rating"],
                    review_time_unix,
                    review_data["review"],
                )

                cursor.execute(query, values)
                self.mysql_conn.commit()

                logger.debug(
                    f"Inserted new review for order_id {review_data['order_id']}"
                )
                return True
        except mysql.connector.Error as err:
            logger.error(f"Error inserting review in MySQL: {err}")
            self.mysql_conn.rollback()
            return False

    def process_batch_with_rate_limit(
        self, reviews: List[Dict[str, Any]], existing_order_ids: Set[int]
    ) -> Tuple[int, int]:
        """
        Process a batch of reviews with rate limiting.

        Args:
            reviews: List of review records
            existing_order_ids: Set of existing order IDs

        Returns:
            Tuple of (updates count, inserts count)
        """
        updates = 0
        inserts = 0

        for review in reviews:
            # Apply rate limiting before each database operation
            self.rate_limiter.wait()

            if review["order_id"] in existing_order_ids:
                # Update existing record
                if self.update_review_time(
                    review["order_id"], review["order_type"], review["review_time"]
                ):
                    updates += 1
            else:
                # Insert new record
                if self.insert_review(review):
                    inserts += 1

        return updates, inserts
