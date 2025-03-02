# main.py
"""Main module for orchestrating the review migration process."""

import logging
import time
import argparse
import signal
import sys
from typing import Dict, List, Set, Tuple, Any

import config
from database import DatabaseManager
from csv_processor import load_existing_order_ids, save_processed_order_id

# Flag to indicate if the process was interrupted
interrupted = False


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
        handlers=[logging.FileHandler(config.LOG_FILE), logging.StreamHandler()],
    )
    return logging.getLogger(__name__)


def parse_args():
    """
    Parse command-line arguments.

    Returns:
        Parsed arguments
    """
    parser = argparse.ArgumentParser(
        description="Migrate reviews from PostgreSQL to MySQL"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Perform a dry run without making changes",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=config.BATCH_SIZE,
        help="Batch size for processing",
    )
    parser.add_argument(
        "--ops-per-second",
        type=float,
        default=config.OPERATIONS_PER_SECOND,
        help="Operations per second (rate limit)",
    )
    parser.add_argument(
        "--disable-rate-limit", action="store_true", help="Disable rate limiting"
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )
    parser.add_argument(
        "--resume", action="store_true", help="Resume from last saved state"
    )
    parser.add_argument(
        "--force-start",
        action="store_true",
        help="Force start from beginning (ignore saved state)",
    )
    parser.add_argument(
        "--update-existing-only",
        action="store_true",
        help="Only update existing records, don't insert new ones",
    )
    return parser.parse_args()


def signal_handler(sig, frame):
    """
    Handle interruption signals (Ctrl+C).

    This allows for a graceful shutdown where state is saved.
    """
    global interrupted
    logger = logging.getLogger(__name__)
    logger.info("Received interrupt signal. Will exit after current batch completes...")
    interrupted = True


def main():
    """Main function to orchestrate the review migration process."""
    # Register signal handler for graceful interruption
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Parse arguments
    args = parse_args()

    # Adjust configuration based on args
    config.BATCH_SIZE = args.batch_size
    config.OPERATIONS_PER_SECOND = args.ops_per_second
    log_level = getattr(logging, args.log_level)

    # Set up logging
    logger = setup_logging(log_level)

    logger.info(
        f"Starting review migration process with batch size={config.BATCH_SIZE}, "
        f"operations per second={config.OPERATIONS_PER_SECOND}"
    )

    if args.dry_run:
        logger.info("DRY RUN MODE: No changes will be made to the database")

    # Initialize database manager
    db_manager = DatabaseManager(
        dry_run=args.dry_run, enable_rate_limiting=not args.disable_rate_limit
    )

    # Connect to databases
    if not db_manager.connect_mysql():
        logger.error("Failed to connect to MySQL database. Exiting.")
        return

    if not db_manager.connect_postgres():
        logger.error("Failed to connect to PostgreSQL database. Exiting.")
        db_manager.close_connections()
        return

    try:
        # Load existing order IDs from CSV
        existing_order_ids = load_existing_order_ids()
        if not existing_order_ids:
            logger.warning(
                "No existing order IDs were loaded. All reviews will be inserted as new."
            )

        # Get total count of reviews to process
        total_reviews = db_manager.get_total_review_count()
        logger.info(f"Found {total_reviews} reviews to process")

        # Check if we should resume from a saved state
        offset = 0
        last_order_id = 0

        if args.resume and not args.force_start:
            state = config.load_state()
            if state["offset"] > 0:
                offset = state["offset"]
                last_order_id = state["last_order_id"]
                logger.info(
                    f"Resuming from offset {offset} (last order_id: {last_order_id})"
                )
            else:
                logger.info("No saved state found. Starting from the beginning.")

        # Process reviews in batches
        total_updates = 0
        total_inserts = 0
        start_time = time.time()

        while offset < total_reviews and not interrupted:
            batch_start_time = time.time()

            # Fetch a batch of reviews
            if last_order_id > 0 and offset == state.get("offset", 0):
                # If resuming, fetch based on last_order_id
                reviews, new_offset = db_manager.fetch_reviews_from_order_id(
                    last_order_id, config.BATCH_SIZE
                )
                offset = new_offset
            else:
                # Normal fetching by offset
                reviews = db_manager.fetch_reviews_batch(offset)

            if not reviews:
                logger.warning(f"No reviews fetched at offset {offset}. Breaking loop.")
                break

            # Process the batch
            if args.update_existing_only:
                # Only process records that exist in existing_order_ids
                reviews_to_process = [
                    r for r in reviews if r["order_id"] in existing_order_ids
                ]
                logger.info(
                    f"Processing {len(reviews_to_process)}/{len(reviews)} reviews (update-only mode)"
                )
                updates, _ = db_manager.process_batch_with_rate_limit(
                    reviews_to_process, existing_order_ids
                )
                total_updates += updates
                inserts = 0
            else:
                # Process all records
                updates, inserts = db_manager.process_batch_with_rate_limit(
                    reviews, existing_order_ids
                )
                total_updates += updates
                total_inserts += inserts

            # Update progress
            offset += len(reviews)
            progress = min(100, (offset / total_reviews) * 100)
            batch_time = time.time() - batch_start_time
            elapsed_time = time.time() - start_time

            # Estimate time remaining
            if offset > 0:
                avg_time_per_review = elapsed_time / offset
                est_remaining = avg_time_per_review * (total_reviews - offset)
                est_completion = time.strftime(
                    "%H:%M:%S", time.gmtime(time.time() + est_remaining)
                )
            else:
                est_remaining = "Unknown"
                est_completion = "Unknown"

            logger.info(
                f"Progress: {progress:.2f}% ({offset}/{total_reviews}). "
                + f"Batch time: {batch_time:.2f}s. "
                + f"Updates: {updates} (total: {total_updates}), "
                + f"Inserts: {inserts} (total: {total_inserts}). "
                + f"Est. completion: {est_completion}"
            )

            # Save state after each batch (already happens in fetch_reviews_batch)

    except KeyboardInterrupt:
        logger.info("Process interrupted by user")
    except Exception as e:
        logger.error(f"Unexpected error in main process: {e}", exc_info=True)
    finally:
        # Save final state
        last_order_id = db_manager.last_processed_order_id
        config.save_state(offset, last_order_id)
        logger.info(f"Saved state: offset={offset}, last_order_id={last_order_id}")

        # Close database connections
        db_manager.close_connections()

        # Log completion
        total_time = time.time() - start_time
        logger.info(
            f"Review migration {'completed' if offset >= total_reviews else 'interrupted'}. "
            + f"Total updates: {total_updates}, Total inserts: {total_inserts}"
        )
        logger.info(
            f"Total execution time: {total_time:.2f} seconds "
            + f"({time.strftime('%H:%M:%S', time.gmtime(total_time))})"
        )

        if interrupted:
            logger.info(
                "Migration was interrupted. Run with --resume to continue from this point."
            )
            sys.exit(130)  # Standard exit code for Ctrl+C


if __name__ == "__main__":
    main()
