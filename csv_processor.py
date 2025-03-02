# csv_processor.py
"""Module for processing CSV files containing existing order IDs."""

import csv
import logging
import os
from typing import Set

from config import EXISTING_ORDER_IDS_CSV

logger = logging.getLogger(__name__)


def load_existing_order_ids() -> Set[int]:
    """
    Load the existing order IDs from the CSV file.

    Returns:
        Set of order IDs that have already been processed
    """
    existing_ids = set()

    if not os.path.exists(EXISTING_ORDER_IDS_CSV):
        logger.warning(f"CSV file not found: {EXISTING_ORDER_IDS_CSV}")
        return existing_ids

    try:
        with open(EXISTING_ORDER_IDS_CSV, "r") as csvfile:
            reader = csv.DictReader(csvfile)

            # Validate that the CSV has the required column
            if not reader.fieldnames or "order_id" not in reader.fieldnames:
                logger.error(
                    f"CSV file does not contain 'order_id' column. Fields found: {reader.fieldnames}"
                )
                return existing_ids

            for row in reader:
                try:
                    order_id = int(row["order_id"])
                    existing_ids.add(order_id)
                except (ValueError, KeyError) as e:
                    logger.warning(
                        f"Error parsing order_id from row: {row}. Error: {e}"
                    )
    except Exception as e:
        logger.error(f"Error reading CSV file: {e}")

    logger.info(f"Loaded {len(existing_ids)} existing order IDs from CSV")
    return existing_ids


def save_processed_order_id(order_id: int) -> bool:
    """
    Append a processed order_id to the CSV file.
    This can be used to keep track of successfully processed IDs.

    Args:
        order_id: The order ID to save

    Returns:
        True if successful, False otherwise
    """
    try:
        file_exists = os.path.exists(EXISTING_ORDER_IDS_CSV)

        with open(EXISTING_ORDER_IDS_CSV, "a", newline="") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=["order_id"])

            # Write header if file is new
            if not file_exists:
                writer.writeheader()

            writer.writerow({"order_id": order_id})

        return True
    except Exception as e:
        logger.error(f"Error saving order_id to CSV: {e}")
        return False
