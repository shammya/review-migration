# csv_processor.py
"""Module for processing CSV files containing existing order IDs."""

import csv
import logging
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
    try:
        with open(EXISTING_ORDER_IDS_CSV, "r") as csvfile:
            reader = csv.DictReader(csvfile)
            if "order_id" not in reader.fieldnames:
                logger.error("CSV file does not contain 'order_id' column")
                return existing_ids

            for row in reader:
                try:
                    order_id = int(row["order_id"])
                    existing_ids.add(order_id)
                except (ValueError, KeyError) as e:
                    logger.warning(
                        f"Error parsing order_id from row: {row}. Error: {e}"
                    )
    except FileNotFoundError:
        logger.error(f"CSV file not found: {EXISTING_ORDER_IDS_CSV}")
    except Exception as e:
        logger.error(f"Error reading CSV file: {e}")

    logger.info(f"Loaded {len(existing_ids)} existing order IDs from CSV")
    return existing_ids
