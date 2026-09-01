#!/usr/bin/env python3
"""
Vast.ai GPU Market Data Collector Daemon.
Periodically fetches real GPU market data every 5 minutes (or user-defined interval)
and stores raw offers + summary metrics into a local SQLite database (gpu_history.db).
"""

import sys
import os
import time
import signal
import logging
import argparse
import datetime
import pandas as pd

from vast_client import VastAIClient, DB_PATH, GPU_PRESETS, get_env_or_secret_api_key


# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("collector.log", mode="a", encoding="utf-8"),
    ],
)
logger = logging.getLogger("GPUCollector")

running = True


def signal_handler(signum, frame):
    global running
    logger.info("Signal received. Stopping collector gracefully...")
    running = False


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


def collect_snapshot(client: VastAIClient, db_path: str = DB_PATH) -> int:
    """Fetches all preset GPUs from Vast.ai and saves complete raw + aggregated dataset."""
    start_time = time.time()
    logger.info("Fetching GPU market data from Vast.ai API...")

    try:
        raw_df = client.fetch_all_selected_offers(selected_gpus=None)
        if raw_df.empty:
            logger.warning("No offers returned from Vast.ai API.")
            return 0

        # Record raw offers + both price modes summary stats
        VastAIClient.record_full_dataset_snapshot(raw_df, db_path=db_path)

        duration = time.time() - start_time
        num_offers = len(raw_df)
        num_unique_gpus = raw_df["display_name"].nunique()

        # Quick price highlights
        logger.info(
            f"✅ Snapshot saved: {num_offers} servers across {num_unique_gpus} GPU models "
            f"in {duration:.2f}s."
        )

        # Print breakdown for top GPUs
        v100_16 = raw_df[raw_df["display_name"] == "Tesla V100 16GB"]
        rtx4090 = raw_df[raw_df["display_name"] == "RTX 4090"]
        if not v100_16.empty:
            logger.info(
                f"   • Tesla V100 16GB: {len(v100_16)} servers, "
                f"Median: ${v100_16['dph_per_gpu'].median():.4f}/hr, "
                f"Rentable: {v100_16['rentable'].sum()}/{len(v100_16)}"
            )
        if not rtx4090.empty:
            logger.info(
                f"   • RTX 4090: {len(rtx4090)} servers, "
                f"Median: ${rtx4090['dph_per_gpu'].median():.4f}/hr, "
                f"Rentable: {rtx4090['rentable'].sum()}/{len(rtx4090)}"
            )

        return num_offers

    except Exception as e:
        logger.error(f"❌ Error during data collection: {e}", exc_info=True)
        return 0


def main():
    parser = argparse.ArgumentParser(description="Vast.ai GPU Market Data Collector Daemon")
    parser.add_argument(
        "--interval",
        type=int,
        default=300,
        help="Collection interval in seconds (default: 300 = 5 minutes)",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default="",
        help="Vast.ai API Key (if omitted, reads from VAST_API_KEY environment variable or .streamlit/secrets.toml)",
    )
    parser.add_argument(
        "--db",
        type=str,
        default=DB_PATH,
        help=f"SQLite database file path (default: {DB_PATH})",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run collection once and exit immediately (useful for cron)",
    )

    args = parser.parse_args()

    api_key_to_use = args.api_key.strip() if args.api_key else get_env_or_secret_api_key()
    if not api_key_to_use:
        logger.warning("⚠️ No Vast.ai API key found in args, environment, or secrets.toml. Proceeding without authorization token.")

    client = VastAIClient(api_key=api_key_to_use)


    logger.info("=" * 60)
    logger.info("🚀 Starting Vast.ai GPU Price Collector")
    logger.info(f"   • Interval: {args.interval} seconds ({args.interval / 60:.1f} min)")
    logger.info(f"   • Database: {os.path.abspath(args.db)}")
    logger.info(f"   • Tracked models: {len(GPU_PRESETS)} presets")
    logger.info("=" * 60)

    if args.once:
        collect_snapshot(client, db_path=args.db)
        logger.info("Single snapshot completed. Exiting.")
        return

    iteration = 1
    while running:
        logger.info(f"\n--- [Iteration #{iteration}] {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---")
        collect_snapshot(client, db_path=args.db)
        iteration += 1

        # Sleep in small chunks so signal_handler can stop promptly
        sleep_until = time.time() + args.interval
        while running and time.time() < sleep_until:
            time.sleep(1)

    logger.info("Collector stopped.")


if __name__ == "__main__":
    main()
