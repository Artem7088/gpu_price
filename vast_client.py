"""
Vast.ai API Client for GPU Price & Availability Monitoring.
Fetches 100% REAL data from Vast.ai API without synthetic or fabricated data.
Includes exponential backoff retry logic, multi-model querying, and real SQLite history logging.
"""

import os

import time
import logging
import json
import sqlite3
import datetime
import requests
import pandas as pd
import numpy as np
from typing import List, Dict, Any, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

VAST_API_BASE_URL = "https://console.vast.ai/api/v0"
DB_PATH = "gpu_history.db"

GPU_PRESETS = [
    # Top & Popular
    "RTX 4090",
    "RTX 3090",
    "RTX 5090",
    "Tesla V100 16GB",
    "Tesla V100 32GB",
    "A100 (All variants)",
    "A100 80GB",
    "A100 40GB",
    "H100 (All variants)",
    "H100 SXM",
    "H100 PCIE",
    "H100 NVL",
    "H200",
    "H200 NVL",
    "RTX A6000",
    "RTX 6000Ada",
    "L40S",
    "L40",
    "L4",
    "RTX 4080",
    "RTX 4080 Super",
    "RTX 3080",
    "RTX 3080 Ti",
    "RTX 3070",
    "RTX 3070 Ti",
    "RTX 4070",
    "RTX 4070 Ti",
    "RTX 4070 Super",
    "RTX 4070 Ti Super",
    "RTX 5080",
    "RTX 5070",
    "RTX 5070 Ti",
    "Tesla T4",
    "Tesla P100",
    "Tesla P40",
    "Tesla P4",
    "RTX 2080 Ti",
    "RTX 2080 Super",
    "RTX 2080",
    "RTX 2070",
    "RTX 2070 Super",
    "RTX 2060",
    "RTX 2060 Super",
    "GTX 1080 Ti",
    "GTX 1080",
    "GTX 1070",
    "GTX 1660 Ti",
    "GTX 1660 Super",
    "TITAN RTX",
    "TITAN V",
    "TITAN Xp",
    "RTX A5000",
    "RTX A4500",
    "RTX A4000",
    "RTX A2000",
    "RTX 5000Ada",
    "RTX 4500Ada",
    "RTX 4000Ada",
    "RTX 2000Ada",
    "RTX PRO 6000 WS",
    "RTX PRO 6000 S",
    "RTX PRO 6000 Max-Q",
    "Q RTX 6000",
    "Quadro RTX 8000",
    "Quadro RTX 6000",
    "Quadro RTX 5000",
    "Quadro RTX 4000",
    "Quadro P6000",
    "Quadro P5000",
    "Quadro GV100",
    "A800",
    "A40",
    "A30",
    "A16",
    "A10",
    "A10G",
    "A2",
    "B200",
    "B100",
    "AMD MI300X",
    "AMD MI250X",
    "AMD MI250",
    "AMD MI210",
    "AMD MI100",
    "AMD MI50",
    "Radeon RX 7900 XTX",
    "Radeon RX 7900 XT",
    "Radeon RX 7900 GRE",
    "Radeon RX 7800 XT",
    "Radeon RX 6900 XT",
    "Radeon RX 6800 XT",
    "Radeon RX 6700 XT",
    "Radeon Pro VII",
    "Radeon VII",
    "Intel Data Center GPU Max 1550",
    "Intel Data Center GPU Max 1100",
    "Intel Arc A770",
    "Intel Arc A750",
    "Intel Arc Pro A60",
]

GPU_API_NAME_MAP = {
    "RTX 4090": ["RTX 4090", "RTX 4090D"],
    "RTX 4090D": ["RTX 4090D"],
    "RTX 3090": ["RTX 3090", "RTX 3090 Ti"],
    "RTX 3090 Ti": ["RTX 3090 Ti"],
    "RTX 5090": ["RTX 5090"],
    "RTX 5080": ["RTX 5080"],
    "RTX 5070": ["RTX 5070"],
    "RTX 5070 Ti": ["RTX 5070 Ti"],
    "Tesla V100 16GB": ["Tesla V100"],
    "Tesla V100 32GB": ["Tesla V100"],
    "A100 (All variants)": ["A100 PCIE", "A100 SXM4", "A100"],
    "A100 80GB": ["A100 PCIE", "A100 SXM4", "A100"],
    "A100 40GB": ["A100 PCIE", "A100 SXM4", "A100"],
    "H100 (All variants)": ["H100 SXM", "H100 PCIE", "H100 NVL", "H100"],
    "H100 SXM": ["H100 SXM"],
    "H100 PCIE": ["H100 PCIE"],
    "H100 NVL": ["H100 NVL"],
    "H200": ["H200", "H200 NVL"],
    "H200 NVL": ["H200 NVL"],
    "H800": ["H800"],
    "B200": ["B200"],
    "B100": ["B100"],
    "RTX A6000": ["RTX A6000", "RTX 6000Ada", "RTX PRO 6000 S", "RTX PRO 6000 WS", "RTX PRO 6000 Max-Q", "Q RTX 6000"],
    "RTX 6000Ada": ["RTX 6000Ada"],
    "RTX 5000Ada": ["RTX 5000Ada"],
    "RTX 4500Ada": ["RTX 4500Ada"],
    "RTX 4000Ada": ["RTX 4000Ada"],
    "RTX 2000Ada": ["RTX 2000Ada"],
    "RTX A5000": ["RTX A5000"],
    "RTX A4500": ["RTX A4500"],
    "RTX A4000": ["RTX A4000"],
    "RTX A2000": ["RTX A2000"],
    "RTX PRO 6000 WS": ["RTX PRO 6000 WS"],
    "RTX PRO 6000 S": ["RTX PRO 6000 S"],
    "RTX PRO 6000 Max-Q": ["RTX PRO 6000 Max-Q"],
    "Q RTX 6000": ["Q RTX 6000"],
    "Quadro RTX 8000": ["Quadro RTX 8000"],
    "Quadro RTX 6000": ["Quadro RTX 6000"],
    "Quadro RTX 5000": ["Quadro RTX 5000"],
    "Quadro RTX 4000": ["Quadro RTX 4000"],
    "Quadro P6000": ["Quadro P6000"],
    "Quadro P5000": ["Quadro P5000"],
    "Quadro GV100": ["Quadro GV100"],
    "L40S": ["L40S"],
    "L40": ["L40"],
    "L4": ["L4"],
    "L20": ["L20"],
    "A800": ["A800"],
    "A40": ["A40"],
    "A30": ["A30"],
    "A16": ["A16"],
    "A10": ["A10"],
    "A10G": ["A10G"],
    "A2": ["A2"],
    "RTX 4080": ["RTX 4080", "RTX 4080S", "RTX 4080 Super"],
    "RTX 4080 Super": ["RTX 4080S", "RTX 4080 Super"],
    "RTX 4070 Ti": ["RTX 4070 Ti", "RTX 4070Ti"],
    "RTX 4070 Ti Super": ["RTX 4070 Ti Super", "RTX 4070Ti Super"],
    "RTX 4070": ["RTX 4070", "RTX 4070S", "RTX 4070 Super"],
    "RTX 4070 Super": ["RTX 4070S", "RTX 4070 Super"],
    "RTX 4060 Ti": ["RTX 4060 Ti", "RTX 4060Ti"],
    "RTX 4060": ["RTX 4060"],
    "RTX 3080": ["RTX 3080", "RTX 3080 Ti"],
    "RTX 3080 Ti": ["RTX 3080 Ti", "RTX 3080Ti"],
    "RTX 3070": ["RTX 3070"],
    "RTX 3070 Ti": ["RTX 3070 Ti", "RTX 3070Ti"],
    "RTX 3060": ["RTX 3060"],
    "RTX 3060 Ti": ["RTX 3060 Ti", "RTX 3060Ti"],
    "RTX 2080 Ti": ["RTX 2080 Ti", "RTX 2080Ti"],
    "RTX 2080 Super": ["RTX 2080 Super", "RTX 2080S"],
    "RTX 2080": ["RTX 2080", "RTX 2080 Super", "RTX 2080S"],
    "RTX 2070": ["RTX 2070", "RTX 2070S", "RTX 2070 Super"],
    "RTX 2070 Super": ["RTX 2070S", "RTX 2070 Super"],
    "RTX 2060": ["RTX 2060"],
    "RTX 2060 Super": ["RTX 2060S", "RTX 2060 Super"],
    "GTX 1080 Ti": ["GTX 1080 Ti", "GTX 1080Ti"],
    "GTX 1080": ["GTX 1080"],
    "GTX 1070": ["GTX 1070"],
    "GTX 1660 Ti": ["GTX 1660 Ti", "GTX 1660Ti"],
    "GTX 1660 Super": ["GTX 1660 Super", "GTX 1660S"],
    "TITAN RTX": ["TITAN RTX"],
    "TITAN V": ["TITAN V"],
    "TITAN Xp": ["TITAN Xp"],
    "Tesla T4": ["Tesla T4", "T4"],
    "Tesla P100": ["Tesla P100", "P100"],
    "Tesla P40": ["Tesla P40"],
    "Tesla P4": ["Tesla P4"],
    "Tesla K80": ["Tesla K80"],
    "Tesla M40": ["Tesla M40"],
    "AMD MI300X": ["AMD MI300X", "MI300X"],
    "AMD MI250X": ["AMD MI250X", "MI250X"],
    "AMD MI250": ["AMD MI250", "MI250"],
    "AMD MI210": ["AMD MI210", "MI210"],
    "AMD MI100": ["AMD MI100", "MI100"],
    "AMD MI50": ["AMD Radeon Instinct MI50", "AMD MI50", "MI50"],
    "Radeon RX 7900 XTX": ["Radeon RX 7900 XTX", "RX 7900 XTX"],
    "Radeon RX 7900 XT": ["Radeon RX 7900 XT", "RX 7900 XT"],
    "Radeon RX 7900 GRE": ["Radeon RX 7900 GRE", "RX 7900 GRE"],
    "Radeon RX 7800 XT": ["Radeon RX 7800 XT", "RX 7800 XT"],
    "Radeon RX 6900 XT": ["Radeon RX 6900 XT", "RX 6900 XT"],
    "Radeon RX 6800 XT": ["Radeon RX 6800 XT", "RX 6800 XT"],
    "Radeon RX 6700 XT": ["Radeon RX 6700 XT", "RX 6700 XT"],
    "Radeon Pro VII": ["Radeon Pro VII"],
    "Radeon VII": ["Radeon VII"],
    "Intel Data Center GPU Max 1550": ["Intel Data Center GPU Max 1550", "Data Center GPU Max 1550"],
    "Intel Data Center GPU Max 1100": ["Intel Data Center GPU Max 1100", "Data Center GPU Max 1100"],
    "Intel Arc A770": ["Intel Arc A770", "Arc A770"],
    "Intel Arc A750": ["Intel Arc A750", "Arc A750"],
    "Intel Arc Pro A60": ["Intel Arc Pro A60", "Arc Pro A60"],
}


class VastAPIError(Exception):
    pass


class VastAuthError(VastAPIError):
    pass


class VastRateLimitError(VastAPIError):
    pass


class VastConnectionError(VastAPIError):
    pass


PREFERENCES_FILE = "user_preferences.json"

DEFAULT_PREFERENCES = {
    "selected_gpus": ["RTX 4090", "RTX 3090", "Tesla V100 16GB", "Tesla V100 32GB", "A100 (All variants)"],
    "selected_configs": [1, 2, 4, 8],
    "price_mode": "per_gpu",
    "preset_period": "7 днів",
    "auto_refresh": False,
}


def load_preferences(file_path: str = PREFERENCES_FILE) -> Dict[str, Any]:
    """Loads saved user preferences (selected GPUs, configs, price mode, etc.)."""
    import os
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                merged = DEFAULT_PREFERENCES.copy()
                merged.update(data)
                # Ensure valid GPUs
                valid_gpus = [g for g in merged.get("selected_gpus", []) if g in GPU_PRESETS]
                if valid_gpus:
                    merged["selected_gpus"] = valid_gpus
                return merged
        except Exception as e:
            logger.error(f"Error loading preferences: {e}")
    return DEFAULT_PREFERENCES.copy()


def save_preferences(prefs: Dict[str, Any], file_path: str = PREFERENCES_FILE):
    """Saves user preferences to JSON file."""
    try:
        current = load_preferences(file_path)
        current.update(prefs)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(current, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error saving preferences: {e}")


def init_history_db(db_path: str = DB_PATH):
    """Initializes SQLite tables for raw offer snapshots and aggregated analytics."""
    try:
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        
        # Table 1: Aggregated statistics snapshots
        c.execute("""
            CREATE TABLE IF NOT EXISTS snapshot_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME,
                gpu_name TEXT,
                min_price REAL,
                p10_price REAL,
                median_price REAL,
                mean_price REAL,
                p90_price REAL,
                max_price REAL,
                utilization_pct REAL,
                rentable_count INTEGER,
                total_count INTEGER,
                price_mode TEXT
            )
        """)

        # Table 2: Complete raw server dataset snapshots
        c.execute("""
            CREATE TABLE IF NOT EXISTS raw_offers_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_time DATETIME,
                bundle_id INTEGER,
                machine_id INTEGER,
                raw_gpu_name TEXT,
                display_name TEXT,
                num_gpus INTEGER,
                gpu_ram_gb REAL,
                dph_total REAL,
                dph_per_gpu REAL,
                dph_base REAL,
                rentable INTEGER,
                rented INTEGER,
                is_bid INTEGER,
                reliability_pct REAL,
                dlperf REAL,
                inet_down_mbps REAL,
                inet_up_mbps REAL,
                geolocation TEXT
            )
        """)

        # Indexes for fast querying
        c.execute("CREATE INDEX IF NOT EXISTS idx_stats_time_gpu ON snapshot_stats(timestamp, gpu_name)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_raw_time_gpu ON raw_offers_history(snapshot_time, display_name)")

        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Error initializing DB: {e}")

def get_env_or_secret_api_key() -> str:
    """Safely retrieves Vast.ai API key from environment, Streamlit secrets, or secrets.toml without hardcoding."""
    # 1. Environment variable
    env_key = os.environ.get("VAST_API_KEY")
    if env_key and env_key.strip():
        return env_key.strip()

    # 2. Streamlit Cloud secrets
    try:
        import streamlit as st
        if hasattr(st, "secrets") and "VAST_API_KEY" in st.secrets:
            return str(st.secrets["VAST_API_KEY"]).strip()
    except Exception:
        pass

    # 3. Local secrets.toml file
    try:
        cur_dir = os.path.dirname(os.path.abspath(__file__))
        secrets_path = os.path.join(cur_dir, ".streamlit", "secrets.toml")
        if os.path.exists(secrets_path):
            with open(secrets_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("VAST_API_KEY"):
                        parts = line.split("=", 1)
                        if len(parts) == 2:
                            return parts[1].strip().strip('"').strip("'")
    except Exception:
        pass

    return ""


class VastAIClient:
    """Client for querying and processing GPU metrics from Vast.ai API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = VAST_API_BASE_URL,
    ):
        if not api_key:
            api_key = get_env_or_secret_api_key()
        self.api_key = str(api_key).strip() if api_key else ""
        self.base_url = base_url.rstrip("/")
        init_history_db()



    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "VastGPUPriceMonitor/1.0",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _request_with_retry(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        max_retries: int = 3,
        backoff_delays: Tuple[float, ...] = (1.0, 2.0, 4.0),
    ) -> Dict[str, Any]:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        headers = self._get_headers()
        last_exception = None

        for attempt in range(max_retries + 1):
            try:
                response = requests.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    json=json_data,
                    timeout=15,
                )

                if response.status_code == 200:
                    try:
                        return response.json()
                    except ValueError as e:
                        raise VastAPIError(f"Неможливо розпарсити відповідь API: {e}")

                elif response.status_code in (401, 403):
                    error_msg = response.text
                    try:
                        err_json = response.json()
                        error_msg = err_json.get("msg", err_json.get("error", response.text))
                    except Exception:
                        pass
                    raise VastAuthError(
                        f"Помилка авторизації (HTTP {response.status_code}): {error_msg}. Перевірте ваш API-ключ."
                    )

                elif response.status_code == 429:
                    if attempt < max_retries:
                        delay = backoff_delays[attempt] if attempt < len(backoff_delays) else 4.0
                        logger.warning(f"Отримано 429 Rate Limit. Повтор через {delay}s...")
                        time.sleep(delay)
                        continue
                    raise VastRateLimitError("Перевищено ліміт запитів до Vast.ai API (HTTP 429).")

                elif response.status_code >= 500:
                    if attempt < max_retries:
                        delay = backoff_delays[attempt] if attempt < len(backoff_delays) else 4.0
                        logger.warning(f"Сервер повернув {response.status_code}. Повтор через {delay}s...")
                        time.sleep(delay)
                        continue
                    raise VastAPIError(f"Помилка сервера Vast.ai (HTTP {response.status_code}): {response.text}")

                else:
                    raise VastAPIError(f"Помилка API (HTTP {response.status_code}): {response.text}")

            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
                last_exception = exc
                if attempt < max_retries:
                    delay = backoff_delays[attempt] if attempt < len(backoff_delays) else 4.0
                    time.sleep(delay)
                    continue
                raise VastConnectionError(
                    f"Не вдалося з'єднатися з Vast.ai API після {max_retries} спроб."
                ) from exc

        raise VastAPIError(f"Неочікувана помилка запиту: {last_exception}")

    def fetch_offers_for_raw_name(self, raw_gpu_name: str) -> List[Dict[str, Any]]:
        """Queries all offers for a specific GPU raw name, ensuring no truncation."""
        query_params = {
            "gpu_name": {"eq": raw_gpu_name},
            "verified": {"in": [True, False]},
            "external": {"in": [True, False]},
            "rentable": {"in": [True, False]},
            "order": [["dph_total", "asc"]],
            "limit": 2000,
        }
        params = {"q": json.dumps(query_params)}
        try:
            data = self._request_with_retry("GET", "bundles/", params=params)
            return data.get("offers", [])
        except Exception as e:
            logger.error(f"Error fetching offers for {raw_gpu_name}: {e}")
            return []

    @staticmethod
    def classify_gpu_display_name(raw_name: str, gpu_ram_mb: float) -> str:
        """Classifies raw GPU names into user-friendly names."""
        name = str(raw_name).strip()
        ram_gb = round(gpu_ram_mb / 1024) if gpu_ram_mb else 0

        # Special V100 distinction
        if "V100" in name:
            if ram_gb >= 24 or (gpu_ram_mb and gpu_ram_mb > 20000):
                return "Tesla V100 32GB"
            return "Tesla V100 16GB"

        # Special A100 distinction
        if "A100" in name:
            if ram_gb >= 60 or (gpu_ram_mb and gpu_ram_mb > 50000):
                return "A100 80GB"
            return "A100 40GB"

        # Check in GPU_API_NAME_MAP
        for preset, raw_list in GPU_API_NAME_MAP.items():
            for raw_pattern in raw_list:
                if name.lower() == raw_pattern.lower():
                    return preset

        if "5090" in name:
            return "RTX 5090"
        if "5080" in name:
            return "RTX 5080"
        if "5070 Ti" in name:
            return "RTX 5070 Ti"
        if "5070" in name:
            return "RTX 5070"
        if "4090" in name:
            return "RTX 4090"
        if "4080" in name:
            return "RTX 4080 Super" if "Super" in name or "4080S" in name else "RTX 4080"
        if "4070 Ti" in name:
            return "RTX 4070 Ti Super" if "Super" in name else "RTX 4070 Ti"
        if "4070" in name:
            return "RTX 4070 Super" if "Super" in name or "4070S" in name else "RTX 4070"
        if "4060 Ti" in name:
            return "RTX 4060 Ti"
        if "4060" in name:
            return "RTX 4060"
        if "3090" in name:
            return "RTX 3090 Ti" if "Ti" in name else "RTX 3090"
        if "3080" in name:
            return "RTX 3080 Ti" if "Ti" in name else "RTX 3080"
        if "3070" in name:
            return "RTX 3070 Ti" if "Ti" in name else "RTX 3070"
        if "3060" in name:
            return "RTX 3060 Ti" if "Ti" in name else "RTX 3060"
        if "2080" in name:
            return "RTX 2080 Ti" if "Ti" in name else "RTX 2080 Super" if "Super" in name or "2080S" in name else "RTX 2080"
        if "2070" in name:
            return "RTX 2070 Super" if "Super" in name or "2070S" in name else "RTX 2070"
        if "2060" in name:
            return "RTX 2060 Super" if "Super" in name or "2060S" in name else "RTX 2060"
        if "H200" in name:
            return "H200 NVL" if "NVL" in name else "H200"
        if "H100" in name:
            if "NVL" in name:
                return "H100 NVL"
            if "PCIE" in name:
                return "H100 PCIE"
            return "H100 SXM"
        if "L40S" in name:
            return "L40S"
        if "L40" in name:
            return "L40"
        if "L4" in name:
            return "L4"
        if "6000Ada" in name:
            return "RTX 6000Ada"
        if "A6000" in name or "PRO 6000" in name or "Q RTX 6000" in name:
            return "RTX A6000"
        if "T4" in name:
            return "Tesla T4"
        if "P100" in name:
            return "Tesla P100"
        if "MI300" in name:
            return "AMD MI300X"
        if "MI50" in name or "mi50" in name or "Instinct" in name:
            return "AMD MI50"
        if "7900 XTX" in name:
            return "Radeon RX 7900 XTX"
        if "7900 XT" in name:
            return "Radeon RX 7900 XT"

        return name

    def get_offers_dataframe(self, selected_gpus: Optional[List[str]] = None) -> pd.DataFrame:
        """Alias for fetch_all_selected_offers."""
        return self.fetch_all_selected_offers(selected_gpus=selected_gpus)

    def fetch_all_selected_offers(self, selected_gpus: Optional[List[str]] = None) -> pd.DataFrame:
        """
        Fetches ALL offers for selected GPU models without hitting the global 512 cap.
        Uses parallel querying per GPU family.
        """
        from concurrent.futures import as_completed

        raw_names_to_fetch = set()
        if selected_gpus:
            for tag in selected_gpus:
                if tag in GPU_API_NAME_MAP:
                    raw_names_to_fetch.update(GPU_API_NAME_MAP[tag])
                else:
                    raw_names_to_fetch.add(tag)
        else:
            for names in GPU_API_NAME_MAP.values():
                raw_names_to_fetch.update(names)

        all_offers = []
        with ThreadPoolExecutor(max_workers=min(10, len(raw_names_to_fetch))) as executor:
            future_to_gpu = {
                executor.submit(self.fetch_offers_for_raw_name, raw_name): raw_name
                for raw_name in raw_names_to_fetch
            }
            for future in as_completed(future_to_gpu):
                offers = future.result()
                if offers:
                    all_offers.extend(offers)

        # Remove potential duplicates by offer ID
        seen_ids = set()
        unique_offers = []
        for o in all_offers:
            oid = o.get("id") or o.get("bundle_id")
            if oid and oid in seen_ids:
                continue
            if oid:
                seen_ids.add(oid)
            unique_offers.append(o)

        if not unique_offers:
            return pd.DataFrame()

        records = []
        for o in unique_offers:
            raw_gpu_name = o.get("gpu_name", "Unknown")
            gpu_ram = float(o.get("gpu_ram") or 0.0)
            gpu_ram_gb = round(gpu_ram / 1024, 1)
            num_gpus = int(o.get("num_gpus") or 1)
            dph_total = float(o.get("dph_total") or 0.0)
            dph_base = float(o.get("dph_base") or dph_total)
            dph_per_gpu = round(dph_total / num_gpus, 4) if num_gpus > 0 else dph_total

            display_name = self.classify_gpu_display_name(raw_gpu_name, gpu_ram)

            rentable = bool(o.get("rentable", False))
            rented = bool(o.get("rented", False))
            is_bid = bool(o.get("is_bid", False))
            reliability = float(o.get("reliability2") or o.get("reliability") or 0.0) * 100
            dlperf = float(o.get("dlperf") or 0.0)
            inet_down = float(o.get("inet_down") or 0.0)
            inet_up = float(o.get("inet_up") or 0.0)
            geolocation = str(o.get("geolocation") or o.get("geolocode") or "Unknown")
            machine_id = o.get("machine_id", "")
            bundle_id = o.get("bundle_id") or o.get("id")

            records.append({
                "bundle_id": bundle_id,
                "machine_id": machine_id,
                "raw_gpu_name": raw_gpu_name,
                "display_name": display_name,
                "gpu_ram_gb": gpu_ram_gb,
                "num_gpus": num_gpus,
                "dph_total": dph_total,
                "dph_per_gpu": dph_per_gpu,
                "dph_base": dph_base,
                "rentable": rentable,
                "rented": rented,
                "is_bid": is_bid,
                "reliability_pct": round(reliability, 1),
                "dlperf": round(dlperf, 2),
                "inet_down_mbps": round(inet_down, 1),
                "inet_up_mbps": round(inet_up, 1),
                "geolocation": geolocation,
            })

        return pd.DataFrame(records)


    @staticmethod
    def filter_offers(
        df: pd.DataFrame,
        selected_gpus: Optional[List[str]] = None,
        selected_configs: Optional[List[int]] = None,
    ) -> pd.DataFrame:
        """Filters DataFrame by chosen GPU models and number of GPU configurations."""
        if df.empty:
            return df

        filtered = df.copy()

        if selected_gpus:
            matched_indices = []
            for idx, row in filtered.iterrows():
                disp = str(row["display_name"])
                raw = str(row["raw_gpu_name"])
                for target in selected_gpus:
                    if target == "A100 (All variants)" and ("A100" in disp or "A100" in raw):
                        matched_indices.append(idx)
                        break
                    elif target == "H100 (All variants)" and ("H100" in disp or "H100" in raw):
                        matched_indices.append(idx)
                        break
                    elif target == disp or target == raw:
                        matched_indices.append(idx)
                        break
                    elif target in disp or disp in target:
                        matched_indices.append(idx)
                        break

            filtered = filtered.loc[matched_indices].drop_duplicates()

        if selected_configs:
            filtered = filtered[filtered["num_gpus"].isin(selected_configs)]

        return filtered

    @staticmethod
    def calculate_summary_stats(df: pd.DataFrame, price_mode: str = "per_gpu") -> pd.DataFrame:
        """Calculates 100% REAL summary metrics for each GPU model."""
        if df.empty:
            return pd.DataFrame()

        price_col = "dph_per_gpu" if price_mode == "per_gpu" else "dph_total"
        summary_rows = []

        grouped = df.groupby("display_name")
        for gpu_name, group in grouped:
            prices = group[price_col].dropna()
            if prices.empty:
                continue

            min_p = float(prices.min())
            max_p = float(prices.max())
            mean_p = float(prices.mean())
            median_p = float(prices.median())
            p10_p = float(np.percentile(prices, 10))
            p90_p = float(np.percentile(prices, 90))

            total_count = len(group)
            rentable_count = int(group["rentable"].sum())

            if total_count > 0:
                utilization_pct = max(0.0, min(100.0, ((total_count - rentable_count) / total_count) * 100.0))
            else:
                utilization_pct = 0.0

            summary_rows.append({
                "Карта": gpu_name,
                "Мін. ціна ($/год)": round(min_p, 4),
                "P10 ($/год)": round(p10_p, 4),
                "Медіана ($/год)": round(median_p, 4),
                "Сер. ціна ($/год)": round(mean_p, 4),
                "P90 ($/год)": round(p90_p, 4),
                "Макс. ціна ($/год)": round(max_p, 4),
                "Утилізація (%)": round(utilization_pct, 1),
                "Доступно (шт)": rentable_count,
                "Всього серверів (шт)": total_count,
            })

        result_df = pd.DataFrame(summary_rows)
        if not result_df.empty:
            result_df = result_df.sort_values(by="Всього серверів (шт)", ascending=False).reset_index(drop=True)
        return result_df

    @staticmethod
    def calculate_summary_stats_by_config(df: pd.DataFrame, price_mode: str = "per_gpu") -> pd.DataFrame:
        """Calculates 100% REAL summary metrics broken down by GPU model and number of cards (1x, 2x, 4x, 8x)."""
        if df.empty:
            return pd.DataFrame()

        price_col = "dph_per_gpu" if price_mode == "per_gpu" else "dph_total"
        summary_rows = []

        grouped = df.groupby(["display_name", "num_gpus"])
        for (gpu_name, num_gpus), group in grouped:
            prices = group[price_col].dropna()
            if prices.empty:
                continue

            min_p = float(prices.min())
            max_p = float(prices.max())
            mean_p = float(prices.mean())
            median_p = float(prices.median())
            p10_p = float(np.percentile(prices, 10))
            p90_p = float(np.percentile(prices, 90))

            total_count = len(group)
            rentable_count = int(group["rentable"].sum())

            if total_count > 0:
                utilization_pct = max(0.0, min(100.0, ((total_count - rentable_count) / total_count) * 100.0))
            else:
                utilization_pct = 0.0

            summary_rows.append({
                "Карта": gpu_name,
                "К-сть GPU": int(num_gpus),
                "Конфігурація": f"{gpu_name} [{num_gpus}x GPU]",
                "Мін. ціна ($/год)": round(min_p, 4),
                "P10 ($/год)": round(p10_p, 4),
                "Медіана ($/год)": round(median_p, 4),
                "Сер. ціна ($/год)": round(mean_p, 4),
                "P90 ($/год)": round(p90_p, 4),
                "Макс. ціна ($/год)": round(max_p, 4),
                "Утилізація (%)": round(utilization_pct, 1),
                "Доступно (шт)": rentable_count,
                "Всього серверів (шт)": total_count,
            })

        result_df = pd.DataFrame(summary_rows)
        if not result_df.empty:
            result_df = result_df.sort_values(by=["Карта", "К-сть GPU"]).reset_index(drop=True)
        return result_df

    @staticmethod
    def record_raw_offers_snapshot(raw_df: pd.DataFrame, snapshot_time: Optional[str] = None, db_path: str = DB_PATH):
        """Records complete raw offers dataset into SQLite database."""
        if raw_df.empty:
            return

        if snapshot_time is None:
            snapshot_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        try:
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            records_to_insert = []
            for _, row in raw_df.iterrows():
                records_to_insert.append((
                    snapshot_time,
                    int(row.get("bundle_id") or 0) if pd.notnull(row.get("bundle_id")) else None,
                    int(row.get("machine_id") or 0) if pd.notnull(row.get("machine_id")) else None,
                    str(row.get("raw_gpu_name", "")),
                    str(row.get("display_name", "")),
                    int(row.get("num_gpus") or 1),
                    float(row.get("gpu_ram_gb") or 0.0),
                    float(row.get("dph_total") or 0.0),
                    float(row.get("dph_per_gpu") or 0.0),
                    float(row.get("dph_base") or 0.0),
                    1 if bool(row.get("rentable")) else 0,
                    1 if bool(row.get("rented")) else 0,
                    1 if bool(row.get("is_bid")) else 0,
                    float(row.get("reliability_pct") or 0.0),
                    float(row.get("dlperf") or 0.0),
                    float(row.get("inet_down_mbps") or 0.0),
                    float(row.get("inet_up_mbps") or 0.0),
                    str(row.get("geolocation", "Unknown")),
                ))

            c.executemany("""
                INSERT INTO raw_offers_history (
                    snapshot_time, bundle_id, machine_id, raw_gpu_name, display_name,
                    num_gpus, gpu_ram_gb, dph_total, dph_per_gpu, dph_base,
                    rentable, rented, is_bid, reliability_pct, dlperf,
                    inet_down_mbps, inet_up_mbps, geolocation
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, records_to_insert)

            conn.commit()
            conn.close()
            logger.info(f"Successfully stored {len(records_to_insert)} raw server records to DB at {snapshot_time}.")
        except Exception as e:
            logger.error(f"Error saving raw offers snapshot to DB: {e}")

    @classmethod
    def record_full_dataset_snapshot(cls, raw_df: pd.DataFrame, db_path: str = DB_PATH):
        """
        Saves the entire raw offers dataset and both per_gpu & per_instance summary analytics.
        Also automatically prunes old raw records (>14 days) to keep DB lightweight and fast.
        """
        if raw_df.empty:
            return

        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # 1. Save raw offers
        cls.record_raw_offers_snapshot(raw_df, snapshot_time=now, db_path=db_path)

        # 2. Compute and save per_gpu summary
        summary_per_gpu = cls.calculate_summary_stats(raw_df, price_mode="per_gpu")
        cls.record_real_snapshot(summary_per_gpu, price_mode="per_gpu", db_path=db_path)

        # 3. Compute and save per_instance summary
        summary_per_instance = cls.calculate_summary_stats(raw_df, price_mode="per_instance")
        cls.record_real_snapshot(summary_per_instance, price_mode="per_instance", db_path=db_path)

        # 4. Auto-prune old records (keep recent 30 raw snapshots, >180 days for aggregate stats)
        try:
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            # Keep only latest 30 snapshots in raw offers to keep DB compact for Git and Cloud
            c.execute("SELECT DISTINCT snapshot_time FROM raw_offers_history ORDER BY snapshot_time DESC")
            times = [r[0] for r in c.fetchall()]
            if len(times) > 30:
                keep_times = set(times[:30])
                c.execute("DELETE FROM raw_offers_history WHERE snapshot_time NOT IN (" + ",".join("?" * len(keep_times)) + ")", list(keep_times))

            cutoff_stats = (datetime.datetime.now() - datetime.timedelta(days=180)).strftime("%Y-%m-%d %H:%M:%S")
            c.execute("DELETE FROM snapshot_stats WHERE timestamp < ?", (cutoff_stats,))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"Failed to prune old DB records: {e}")



    @staticmethod
    def get_raw_dataset_history(selected_gpus: Optional[List[str]] = None, days_back: int = 7, db_path: str = DB_PATH) -> pd.DataFrame:
        """Retrieves raw server dataset history from SQLite database."""
        try:
            conn = sqlite3.connect(db_path)
            since_time = (datetime.datetime.now() - datetime.timedelta(days=days_back)).strftime("%Y-%m-%d %H:%M:%S")
            query = "SELECT * FROM raw_offers_history WHERE snapshot_time >= ?"
            params = [since_time]

            df = pd.read_sql_query(query, conn, params=params)
            conn.close()

            if df.empty:
                return pd.DataFrame()

            df["snapshot_time"] = pd.to_datetime(df["snapshot_time"])
            if selected_gpus:
                df = df[df["display_name"].isin(selected_gpus)]

            return df.sort_values(by="snapshot_time", ascending=False).reset_index(drop=True)
        except Exception as e:
            logger.error(f"Error reading raw history from DB: {e}")
            return pd.DataFrame()

    @staticmethod
    def get_db_stats_info(db_path: str = DB_PATH) -> Dict[str, Any]:
        """Returns metadata and statistics about the SQLite database."""
        import os
        info = {
            "db_size_mb": 0.0,
            "total_raw_rows": 0,
            "total_snapshots": 0,
            "first_snapshot": None,
            "last_snapshot": None,
        }
        try:
            if not os.path.exists(db_path):
                return info

            info["db_size_mb"] = round(os.path.getsize(db_path) / (1024 * 1024), 2)
            conn = sqlite3.connect(db_path)
            c = conn.cursor()

            # Check raw_offers_history
            c.execute("SELECT COUNT(*), MIN(snapshot_time), MAX(snapshot_time) FROM raw_offers_history")
            raw_res = c.fetchone()
            if raw_res and raw_res[0]:
                info["total_raw_rows"] = raw_res[0]
                info["first_snapshot"] = raw_res[1]
                info["last_snapshot"] = raw_res[2]

            # Check snapshot_stats
            c.execute("SELECT COUNT(DISTINCT timestamp), MIN(timestamp), MAX(timestamp) FROM snapshot_stats")
            stats_res = c.fetchone()
            if stats_res and stats_res[0]:
                info["total_snapshots"] = max(stats_res[0], info["total_snapshots"])
                if not info["first_snapshot"] and stats_res[1]:
                    info["first_snapshot"] = stats_res[1]
                if not info["last_snapshot"] and stats_res[2]:
                    info["last_snapshot"] = stats_res[2]

            conn.close()
        except Exception as e:
            logger.error(f"Error getting DB stats: {e}")
        return info

    @staticmethod
    def record_real_snapshot(summary_df: pd.DataFrame, price_mode: str = "per_gpu", db_path: str = DB_PATH):
        """Records the current real market snapshot into SQLite database."""
        if summary_df.empty:
            return

        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            for _, row in summary_df.iterrows():
                c.execute("""
                    INSERT INTO snapshot_stats (
                        timestamp, gpu_name, min_price, p10_price, median_price,
                        mean_price, p90_price, max_price, utilization_pct,
                        rentable_count, total_count, price_mode
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    now,
                    row["Карта"],
                    row["Мін. ціна ($/год)"],
                    row["P10 ($/год)"],
                    row["Медіана ($/год)"],
                    row["Сер. ціна ($/год)"],
                    row["P90 ($/год)"],
                    row["Макс. ціна ($/год)"],
                    row["Утилізація (%)"],
                    int(row["Доступно (шт)"]),
                    int(row["Всього серверів (шт)"]),
                    price_mode
                ))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Error saving snapshot to DB: {e}")

    @staticmethod
    def get_real_history(selected_gpus: Optional[List[str]] = None, price_mode: str = "per_gpu", days_back: int = 7, db_path: str = DB_PATH) -> pd.DataFrame:
        """Retrieves actual recorded real historical points from SQLite database."""
        try:
            conn = sqlite3.connect(db_path)
            since_time = (datetime.datetime.now() - datetime.timedelta(days=days_back)).strftime("%Y-%m-%d %H:%M:%S")
            query = "SELECT * FROM snapshot_stats WHERE timestamp >= ? AND price_mode = ?"
            params = [since_time, price_mode]

            df = pd.read_sql_query(query, conn, params=params)
            conn.close()

            if df.empty:
                return pd.DataFrame()

            df["timestamp"] = pd.to_datetime(df["timestamp"])
            if selected_gpus:
                df = df[df["gpu_name"].isin(selected_gpus)]

            return df.sort_values(by="timestamp").reset_index(drop=True)
        except Exception as e:
            logger.error(f"Error reading history from DB: {e}")
            return pd.DataFrame()

    @staticmethod
    def get_historical_summary(
        selected_gpus: Optional[List[str]] = None,
        price_mode: str = "per_gpu",
        days_back: int = 7,
        db_path: str = DB_PATH,
        live_summary_df: Optional[pd.DataFrame] = None
    ) -> pd.DataFrame:
        """
        Calculates aggregated historical metrics per GPU model over the selected days:
        - Mean / Median historical rental prices
        - Mean, Min, Max historical utilization %
        - Average total & available servers
        - Fallbacks to live summary when no history exists for a GPU.
        """
        try:
            conn = sqlite3.connect(db_path)
            since_time = (datetime.datetime.now() - datetime.timedelta(days=days_back)).strftime("%Y-%m-%d %H:%M:%S")
            query = "SELECT * FROM snapshot_stats WHERE timestamp >= ? AND price_mode = ?"
            params = [since_time, price_mode]

            df = pd.read_sql_query(query, conn, params=params)
            conn.close()

            if not df.empty and selected_gpus:
                df = df[df["gpu_name"].isin(selected_gpus)]

            if df.empty:
                return live_summary_df.copy() if live_summary_df is not None else pd.DataFrame()

            grouped_rows = []
            grouped = df.groupby("gpu_name")

            for gpu_name, gdf in grouped:
                mean_price = gdf["mean_price"].mean()
                median_price = gdf["median_price"].median()
                p10_price = gdf["p10_price"].mean()
                p90_price = gdf["p90_price"].mean()
                min_price = gdf["min_price"].min()
                max_price = gdf["max_price"].max()
                mean_util = gdf["utilization_pct"].mean()
                min_util = gdf["utilization_pct"].min()
                max_util = gdf["utilization_pct"].max()
                avg_rentable = gdf["rentable_count"].mean()
                avg_total = gdf["total_count"].mean()
                snapshot_count = len(gdf)

                grouped_rows.append({
                    "Карта": gpu_name,
                    "Мін. ціна ($/год)": round(min_price, 4),
                    "P10 ($/год)": round(p10_price, 4),
                    "Медіана ($/год)": round(median_price, 4),
                    "Сер. ціна ($/год)": round(mean_price, 4),
                    "P90 ($/год)": round(p90_price, 4),
                    "Макс. ціна ($/год)": round(max_price, 4),
                    "Утилізація (%)": round(mean_util, 1),
                    "Мін. утилізація (%)": round(min_util, 1),
                    "Макс. утилізація (%)": round(max_util, 1),
                    "Доступно (шт)": int(round(avg_rentable)),
                    "Всього серверів (шт)": int(round(avg_total)),
                    "К-сть вимірів": int(snapshot_count),
                })

            hist_summary_df = pd.DataFrame(grouped_rows)

            # If some selected GPUs are missing in DB history, add them from live summary
            if live_summary_df is not None and not live_summary_df.empty:
                existing_gpus = set(hist_summary_df["Карта"])
                missing_live = live_summary_df[~live_summary_df["Карта"].isin(existing_gpus)].copy()
                if not missing_live.empty:
                    missing_live["К-сть вимірів"] = 1
                    missing_live["Мін. утилізація (%)"] = missing_live["Утилізація (%)"]
                    missing_live["Макс. утилізація (%)"] = missing_live["Утилізація (%)"]
                    hist_summary_df = pd.concat([hist_summary_df, missing_live], ignore_index=True)

            return hist_summary_df.sort_values(by="Медіана ($/год)", ascending=False).reset_index(drop=True)
        except Exception as e:
            logger.error(f"Error computing historical summary: {e}")
            return live_summary_df.copy() if live_summary_df is not None else pd.DataFrame()
    @staticmethod
    def get_historical_summary_by_config(
        selected_gpus: Optional[List[str]] = None,
        selected_configs: Optional[List[int]] = None,
        price_mode: str = "per_gpu",
        days_back: int = 7,
        db_path: str = DB_PATH,
        live_config_summary_df: Optional[pd.DataFrame] = None
    ) -> pd.DataFrame:
        """Calculates historical summary metrics grouped by GPU model and number of GPUs."""
        try:
            conn = sqlite3.connect(db_path)
            since_time = (datetime.datetime.now() - datetime.timedelta(days=days_back)).strftime("%Y-%m-%d %H:%M:%S")
            price_col = "dph_per_gpu" if price_mode == "per_gpu" else "dph_total"

            query = f"SELECT snapshot_time, display_name, num_gpus, {price_col} as price, rentable FROM raw_offers_history WHERE snapshot_time >= ?"
            df = pd.read_sql_query(query, conn, params=[since_time])
            conn.close()

            if not df.empty and selected_gpus:
                df = df[df["display_name"].isin(selected_gpus)]
            if not df.empty and selected_configs:
                df = df[df["num_gpus"].isin(selected_configs)]

            if df.empty:
                return live_config_summary_df.copy() if live_config_summary_df is not None else pd.DataFrame()

            snap_grouped = df.groupby(["snapshot_time", "display_name", "num_gpus"])
            snap_rows = []
            for (st_time, gname, ngpu), grp in snap_grouped:
                prices = grp["price"].dropna()
                if prices.empty:
                    continue
                t_cnt = len(grp)
                r_cnt = int(grp["rentable"].sum())
                u_pct = ((t_cnt - r_cnt) / t_cnt * 100.0) if t_cnt > 0 else 0.0
                snap_rows.append({
                    "display_name": gname,
                    "num_gpus": ngpu,
                    "mean_price": float(prices.mean()),
                    "median_price": float(prices.median()),
                    "p10_price": float(np.percentile(prices, 10)),
                    "p90_price": float(np.percentile(prices, 90)),
                    "min_price": float(prices.min()),
                    "max_price": float(prices.max()),
                    "utilization_pct": u_pct,
                    "rentable_count": r_cnt,
                    "total_count": t_cnt,
                })

            snap_df = pd.DataFrame(snap_rows)
            if snap_df.empty:
                return live_config_summary_df.copy() if live_config_summary_df is not None else pd.DataFrame()

            final_rows = []
            for (gname, ngpu), gdf in snap_df.groupby(["display_name", "num_gpus"]):
                final_rows.append({
                    "Карта": gname,
                    "К-сть GPU": int(ngpu),
                    "Конфігурація": f"{gname} [{ngpu}x GPU]",
                    "Мін. ціна ($/год)": round(float(gdf["min_price"].min()), 4),
                    "P10 ($/год)": round(float(gdf["p10_price"].mean()), 4),
                    "Медіана ($/год)": round(float(gdf["median_price"].median()), 4),
                    "Сер. ціна ($/год)": round(float(gdf["mean_price"].mean()), 4),
                    "P90 ($/год)": round(float(gdf["p90_price"].mean()), 4),
                    "Макс. ціна ($/год)": round(float(gdf["max_price"].max()), 4),
                    "Утилізація (%)": round(float(gdf["utilization_pct"].mean()), 1),
                    "Мін. утилізація (%)": round(float(gdf["utilization_pct"].min()), 1),
                    "Макс. утилізація (%)": round(float(gdf["utilization_pct"].max()), 1),
                    "Доступно (шт)": int(round(gdf["rentable_count"].mean())),
                    "Всього серверів (шт)": int(round(gdf["total_count"].mean())),
                    "К-сть вимірів": int(len(gdf)),
                })

            res_df = pd.DataFrame(final_rows)

            if live_config_summary_df is not None and not live_config_summary_df.empty:
                existing_configs = set(res_df["Конфігурація"])
                missing_live = live_config_summary_df[~live_config_summary_df["Конфігурація"].isin(existing_configs)].copy()
                if not missing_live.empty:
                    missing_live["К-сть вимірів"] = 1
                    missing_live["Мін. утилізація (%)"] = missing_live["Утилізація (%)"]
                    missing_live["Макс. утилізація (%)"] = missing_live["Утилізація (%)"]
                    res_df = pd.concat([res_df, missing_live], ignore_index=True)

            return res_df.sort_values(by=["Карта", "К-сть GPU"]).reset_index(drop=True)
        except Exception as e:
            logger.error(f"Error in get_historical_summary_by_config: {e}")
            return live_config_summary_df.copy() if live_config_summary_df is not None else pd.DataFrame()




GPU_DEFAULT_SPECS = {
    # RTX 50 Series (GPUpoet & market min)
    "RTX 5090": {"load_w": 600, "idle_w": 45, "price_usd": 2850.0},
    "RTX 5080": {"load_w": 400, "idle_w": 35, "price_usd": 933.0},
    "RTX 5070 Ti": {"load_w": 300, "idle_w": 25, "price_usd": 683.0},
    "RTX 5070": {"load_w": 250, "idle_w": 25, "price_usd": 549.0},

    # RTX 40 Series (GPUpoet & market min)
    "RTX 4090": {"load_w": 450, "idle_w": 35, "price_usd": 1850.0},
    "RTX 4090D": {"load_w": 425, "idle_w": 35, "price_usd": 1680.0},
    "RTX 4080 Super": {"load_w": 320, "idle_w": 25, "price_usd": 930.0},
    "RTX 4080": {"load_w": 320, "idle_w": 25, "price_usd": 837.0},
    "RTX 4070 Ti Super": {"load_w": 285, "idle_w": 20, "price_usd": 698.0},
    "RTX 4070 Ti": {"load_w": 285, "idle_w": 20, "price_usd": 497.0},
    "RTX 4070 Super": {"load_w": 220, "idle_w": 20, "price_usd": 549.0},
    "RTX 4070": {"load_w": 200, "idle_w": 20, "price_usd": 419.0},
    "RTX 4060 Ti": {"load_w": 160, "idle_w": 15, "price_usd": 339.0},
    "RTX 4060": {"load_w": 115, "idle_w": 15, "price_usd": 207.0},

    # RTX 30 Series (GPUpoet & market min)
    "RTX 3090 Ti": {"load_w": 450, "idle_w": 35, "price_usd": 1149.0},
    "RTX 3090": {"load_w": 350, "idle_w": 30, "price_usd": 780.0},
    "RTX 3080 Ti": {"load_w": 350, "idle_w": 30, "price_usd": 407.0},
    "RTX 3080": {"load_w": 320, "idle_w": 30, "price_usd": 295.0},
    "RTX 3070 Ti": {"load_w": 290, "idle_w": 25, "price_usd": 269.0},
    "RTX 3070": {"load_w": 220, "idle_w": 25, "price_usd": 197.0},
    "RTX 3060 Ti": {"load_w": 200, "idle_w": 20, "price_usd": 189.0},
    "RTX 3060": {"load_w": 170, "idle_w": 20, "price_usd": 175.0},

    # RTX 20 & GTX Series
    "RTX 2080 Ti": {"load_w": 250, "idle_w": 25, "price_usd": 225.0},
    "RTX 2080 Super": {"load_w": 250, "idle_w": 25, "price_usd": 195.0},
    "RTX 2080": {"load_w": 215, "idle_w": 20, "price_usd": 170.0},
    "RTX 2070 Super": {"load_w": 215, "idle_w": 20, "price_usd": 160.0},
    "RTX 2070": {"load_w": 175, "idle_w": 20, "price_usd": 140.0},
    "RTX 2060 Super": {"load_w": 175, "idle_w": 20, "price_usd": 135.0},
    "RTX 2060": {"load_w": 160, "idle_w": 20, "price_usd": 115.0},
    "TITAN RTX": {"load_w": 280, "idle_w": 30, "price_usd": 680.0},
    "TITAN V": {"load_w": 250, "idle_w": 30, "price_usd": 340.0},
    "GTX 1080 Ti": {"load_w": 250, "idle_w": 25, "price_usd": 120.0},
    "GTX 1080": {"load_w": 180, "idle_w": 20, "price_usd": 85.0},

    # Tesla & Data Center (GPUpoet min)
    "Tesla V100 16GB": {"load_w": 250, "idle_w": 40, "price_usd": 204.0},
    "Tesla V100 32GB": {"load_w": 250, "idle_w": 40, "price_usd": 580.0},
    "Tesla T4": {"load_w": 70, "idle_w": 15, "price_usd": 290.0},
    "Tesla P100": {"load_w": 250, "idle_w": 35, "price_usd": 57.0},
    "Tesla P40": {"load_w": 250, "idle_w": 35, "price_usd": 115.0},
    "Tesla P4": {"load_w": 75, "idle_w": 15, "price_usd": 75.0},
    "Tesla K80": {"load_w": 300, "idle_w": 40, "price_usd": 35.0},
    "Tesla M40": {"load_w": 250, "idle_w": 35, "price_usd": 50.0},

    # Workstation & AI (GPUpoet min)
    "RTX 6000Ada": {"load_w": 300, "idle_w": 35, "price_usd": 5633.0},
    "RTX 5000Ada": {"load_w": 250, "idle_w": 30, "price_usd": 3600.0},
    "RTX 4000Ada": {"load_w": 130, "idle_w": 20, "price_usd": 1250.0},
    "RTX A6000": {"load_w": 300, "idle_w": 35, "price_usd": 3015.0},
    "RTX A5000": {"load_w": 230, "idle_w": 30, "price_usd": 1480.0},
    "RTX A4000": {"load_w": 140, "idle_w": 20, "price_usd": 620.0},
    "RTX A2000": {"load_w": 70, "idle_w": 15, "price_usd": 260.0},
    "Quadro RTX 8000": {"load_w": 260, "idle_w": 30, "price_usd": 1650.0},
    "Quadro RTX 6000": {"load_w": 260, "idle_w": 30, "price_usd": 850.0},
    "A100 (All variants)": {"load_w": 400, "idle_w": 50, "price_usd": 5950.0},
    "A100 80GB": {"load_w": 400, "idle_w": 50, "price_usd": 8049.0},
    "A100 40GB": {"load_w": 300, "idle_w": 45, "price_usd": 3900.0},
    "A800": {"load_w": 400, "idle_w": 50, "price_usd": 7100.0},
    "A40": {"load_w": 300, "idle_w": 35, "price_usd": 3200.0},
    "L40S": {"load_w": 350, "idle_w": 40, "price_usd": 7100.0},
    "L40": {"load_w": 300, "idle_w": 35, "price_usd": 5600.0},
    "L4": {"load_w": 72, "idle_w": 15, "price_usd": 1850.0},
    "H100 (All variants)": {"load_w": 700, "idle_w": 70, "price_usd": 22500.0},
    "H100 SXM": {"load_w": 700, "idle_w": 70, "price_usd": 25500.0},
    "H100 PCIE": {"load_w": 350, "idle_w": 50, "price_usd": 19000.0},
    "H100 NVL": {"load_w": 700, "idle_w": 70, "price_usd": 30500.0},
    "H800": {"load_w": 700, "idle_w": 70, "price_usd": 19500.0},
    "H200": {"load_w": 700, "idle_w": 70, "price_usd": 34500.0},

    # AMD & Intel (GPUpoet min)
    "AMD MI50": {"load_w": 300, "idle_w": 40, "price_usd": 135.0},
    "AMD MI100": {"load_w": 300, "idle_w": 40, "price_usd": 1050.0},
    "AMD MI210": {"load_w": 300, "idle_w": 40, "price_usd": 2650.0},
    "AMD MI300X": {"load_w": 750, "idle_w": 80, "price_usd": 16500.0},
    "Radeon RX 7900 XTX": {"load_w": 355, "idle_w": 35, "price_usd": 747.0},
    "Radeon RX 7900 XT": {"load_w": 315, "idle_w": 30, "price_usd": 522.0},
    "Radeon RX 6800 XT": {"load_w": 300, "idle_w": 30, "price_usd": 272.0},
}




def get_gpu_specs(gpu_name: str) -> Dict[str, float]:
    """Returns default load power, idle power, and purchase price for a GPU calibrated to GPUpoet & wholesale market minimums."""
    if gpu_name in GPU_DEFAULT_SPECS:
        return GPU_DEFAULT_SPECS[gpu_name].copy()
    # Intelligent fallbacks based on name
    if "4090" in gpu_name:
        return {"load_w": 450, "idle_w": 35, "price_usd": 1850.0}
    if "3090" in gpu_name:
        return {"load_w": 350, "idle_w": 30, "price_usd": 780.0}
    if "5090" in gpu_name:
        return {"load_w": 600, "idle_w": 45, "price_usd": 2850.0}
    if "V100" in gpu_name:
        return {"load_w": 250, "idle_w": 40, "price_usd": 204.0}
    if "A100" in gpu_name:
        return {"load_w": 400, "idle_w": 50, "price_usd": 5950.0}
    if "H100" in gpu_name or "H200" in gpu_name:
        return {"load_w": 700, "idle_w": 70, "price_usd": 22500.0}
    return {"load_w": 250, "idle_w": 25, "price_usd": 400.0}



def calculate_roi_table(
    summary_df: pd.DataFrame,
    custom_prices: Optional[Dict[str, float]] = None,
    custom_load_w: Optional[Dict[str, float]] = None,
    custom_idle_w: Optional[Dict[str, float]] = None,
    electricity_kwh_cost: float = 0.08,
    host_system_load_w: float = 60.0,
    host_system_idle_w: float = 30.0,
    psu_efficiency: float = 0.90,
    platform_fee_pct: float = 10.0,
    monthly_fixed_cost: float = 0.0,
    price_metric: str = "Медіана ($/год)",
) -> pd.DataFrame:
    """
    Calculates 100% REAL Profitability and ROI metrics based on Vast.ai market data.
    """
    if summary_df.empty:
        return pd.DataFrame()

    custom_prices = custom_prices or {}
    custom_load_w = custom_load_w or {}
    custom_idle_w = custom_idle_w or {}

    psu_efficiency = max(0.5, min(1.0, float(psu_efficiency)))
    electricity_kwh_cost = max(0.0, float(electricity_kwh_cost))
    platform_fee_pct = max(0.0, min(100.0, float(platform_fee_pct)))

    HOURS_PER_MONTH = 730.0
    HOURS_PER_DAY = 24.0

    rows = []
    for _, srow in summary_df.iterrows():
        gpu_name = str(srow["Карта"])
        util_pct = float(srow.get("Утилізація (%)", 0.0))
        hourly_rate = float(srow.get(price_metric, srow.get("Медіана ($/год)", 0.0)))

        def_specs = get_gpu_specs(gpu_name)
        card_purchase_price = float(custom_prices.get(gpu_name, def_specs["price_usd"]))
        gpu_load_w = float(custom_load_w.get(gpu_name, def_specs["load_w"]))
        gpu_idle_w = float(custom_idle_w.get(gpu_name, def_specs["idle_w"]))

        wall_load_w = (gpu_load_w + host_system_load_w) / psu_efficiency
        wall_idle_w = (gpu_idle_w + host_system_idle_w) / psu_efficiency

        load_hours_month = HOURS_PER_MONTH * (util_pct / 100.0)
        idle_hours_month = HOURS_PER_MONTH * (1.0 - (util_pct / 100.0))

        net_host_hourly_rate = hourly_rate * (1.0 - (platform_fee_pct / 100.0))
        gross_monthly_rev = load_hours_month * net_host_hourly_rate
        gross_daily_rev = gross_monthly_rev / (HOURS_PER_MONTH / HOURS_PER_DAY)

        kwh_load = (wall_load_w / 1000.0) * load_hours_month
        kwh_idle = (wall_idle_w / 1000.0) * idle_hours_month
        total_kwh_month = kwh_load + kwh_idle

        monthly_electr_cost = total_kwh_month * electricity_kwh_cost
        daily_electr_cost = monthly_electr_cost / (HOURS_PER_MONTH / HOURS_PER_DAY)

        monthly_opex = monthly_electr_cost + monthly_fixed_cost
        daily_opex = monthly_opex / (HOURS_PER_MONTH / HOURS_PER_DAY)

        net_monthly_profit = gross_monthly_rev - monthly_opex
        net_daily_profit = gross_daily_rev - daily_opex
        net_yearly_profit = net_monthly_profit * 12.0

        if net_monthly_profit > 0 and card_purchase_price > 0:
            payback_months = round(card_purchase_price / net_monthly_profit, 1)
            payback_days = int(round(card_purchase_price / net_daily_profit))
            roi_annual_pct = round((net_yearly_profit / card_purchase_price) * 100.0, 1)
        else:
            payback_months = None
            payback_days = None
            roi_annual_pct = 0.0

        net_margin_pct = round((net_monthly_profit / gross_monthly_rev * 100.0), 1) if gross_monthly_rev > 0 else 0.0

        if total_kwh_month > 0:
            breakeven_elec_cost = round(max(0.0, (gross_monthly_rev - monthly_fixed_cost) / total_kwh_month), 4)
        else:
            breakeven_elec_cost = 0.0

        hourly_delta_power_cost = ((wall_load_w - wall_idle_w) / 1000.0) * electricity_kwh_cost
        hourly_net_contribution = net_host_hourly_rate - hourly_delta_power_cost
        monthly_idle_power_cost = ((wall_idle_w / 1000.0) * HOURS_PER_MONTH) * electricity_kwh_cost + monthly_fixed_cost

        if hourly_net_contribution > 0:
            breakeven_util_pct = round(min(100.0, max(0.0, (monthly_idle_power_cost / (HOURS_PER_MONTH * hourly_net_contribution)) * 100.0)), 1)
        else:
            breakeven_util_pct = 100.0

        rows.append({
            "Карта": gpu_name,
            "Ціна карти ($)": round(card_purchase_price, 1),
            "Оренда ($/год)": round(hourly_rate, 4),
            "Утилізація (%)": util_pct,
            "Споживання під навантаженням (Вт)": int(round(wall_load_w)),
            "Споживання в простої (Вт)": int(round(wall_idle_w)),
            "Світло ($/міс)": round(monthly_electr_cost, 2),
            "Валовий дохід ($/міс)": round(gross_monthly_rev, 2),
            "Чистий прибуток ($/день)": round(net_daily_profit, 2),
            "Чистий прибуток ($/міс)": round(net_monthly_profit, 2),
            "Чистий прибуток ($/рік)": round(net_yearly_profit, 2),
            "Окупність (місяців)": payback_months,
            "Окупність (днів)": payback_days,
            "Річний ROI (%)": roi_annual_pct,
            "Маржа (%)": net_margin_pct,
            "Граничне світло ($/кВт·год)": breakeven_elec_cost,
            "Мін. утилізація (%)": breakeven_util_pct,
        })

    return pd.DataFrame(rows)


RIG_PLATFORM_SPECS = {
    1: {"cost_usd": 350.0, "load_w": 60.0, "idle_w": 30.0, "name": "1x GPU Rig Platform (MB+CPU+32GB RAM+1kW PSU+SSD)"},
    2: {"cost_usd": 550.0, "load_w": 90.0, "idle_w": 45.0, "name": "2x GPU Rig Platform (MB+CPU+64GB RAM+1.6kW PSU+SSD)"},
    4: {"cost_usd": 950.0, "load_w": 150.0, "idle_w": 80.0, "name": "4x GPU Server Platform (Dual PSU 2.4kW+128GB RAM+4U Chassis)"},
    8: {"cost_usd": 1700.0, "load_w": 250.0, "idle_w": 140.0, "name": "8x GPU Server Platform (4x PSU 4kW+256GB RAM+8U Chassis)"},
}


def get_platform_specs(num_gpus: int) -> Dict[str, Any]:
    """Returns platform base hardware cost ($), load watts, and idle watts."""
    if num_gpus in RIG_PLATFORM_SPECS:
        return RIG_PLATFORM_SPECS[num_gpus].copy()
    cost = 350.0 + max(0, num_gpus - 1) * 200.0
    load_w = 60.0 + max(0, num_gpus - 1) * 30.0
    idle_w = 30.0 + max(0, num_gpus - 1) * 15.0
    return {"cost_usd": cost, "load_w": load_w, "idle_w": idle_w, "name": f"{num_gpus}x Rig Platform"}


def calculate_roi_table_by_config(
    config_summary_df: pd.DataFrame,
    custom_prices: Optional[Dict[str, float]] = None,
    custom_load_w: Optional[Dict[str, float]] = None,
    custom_idle_w: Optional[Dict[str, float]] = None,
    custom_platform_costs: Optional[Dict[int, float]] = None,
    electricity_kwh_cost: float = 0.08,
    psu_efficiency: float = 0.90,
    platform_fee_pct: float = 10.0,
    monthly_fixed_cost_per_server: float = 0.0,
    price_metric: str = "Медіана ($/год)",
) -> pd.DataFrame:
    """
    Calculates 100% REAL Profitability and ROI metrics for full multi-GPU server configurations (1x, 2x, 4x, 8x).
    """
    if config_summary_df.empty:
        return pd.DataFrame()

    custom_prices = custom_prices or {}
    custom_load_w = custom_load_w or {}
    custom_idle_w = custom_idle_w or {}
    custom_platform_costs = custom_platform_costs or {}

    psu_efficiency = max(0.5, min(1.0, float(psu_efficiency)))
    electricity_kwh_cost = max(0.0, float(electricity_kwh_cost))
    platform_fee_pct = max(0.0, min(100.0, float(platform_fee_pct)))

    HOURS_PER_MONTH = 730.0
    HOURS_PER_DAY = 24.0

    rows = []
    for _, srow in config_summary_df.iterrows():
        gpu_name = str(srow["Карта"])
        num_gpus = int(srow.get("К-сть GPU", 1))
        config_name = str(srow.get("Конфігурація", f"{gpu_name} [{num_gpus}x GPU]"))
        util_pct = float(srow.get("Утилізація (%)", 0.0))
        hourly_rate_per_gpu = float(srow.get(price_metric, srow.get("Медіана ($/год)", 0.0)))

        def_specs = get_gpu_specs(gpu_name)
        card_price = float(custom_prices.get(gpu_name, def_specs["price_usd"]))
        gpu_load_w = float(custom_load_w.get(gpu_name, def_specs["load_w"]))
        gpu_idle_w = float(custom_idle_w.get(gpu_name, def_specs["idle_w"]))

        plat_specs = get_platform_specs(num_gpus)
        plat_cost = float(custom_platform_costs.get(num_gpus, plat_specs["cost_usd"]))
        plat_load_w = float(plat_specs["load_w"])
        plat_idle_w = float(plat_specs["idle_w"])

        total_rig_price = (num_gpus * card_price) + plat_cost
        wall_rig_load_w = ((num_gpus * gpu_load_w) + plat_load_w) / psu_efficiency
        wall_rig_idle_w = ((num_gpus * gpu_idle_w) + plat_idle_w) / psu_efficiency

        server_hourly_rate_gross = hourly_rate_per_gpu * num_gpus
        server_hourly_rate_net = server_hourly_rate_gross * (1.0 - (platform_fee_pct / 100.0))

        load_hours_month = HOURS_PER_MONTH * (util_pct / 100.0)
        idle_hours_month = HOURS_PER_MONTH * (1.0 - (util_pct / 100.0))

        gross_monthly_rev = load_hours_month * server_hourly_rate_net
        gross_daily_rev = gross_monthly_rev / (HOURS_PER_MONTH / HOURS_PER_DAY)

        kwh_load = (wall_rig_load_w / 1000.0) * load_hours_month
        kwh_idle = (wall_rig_idle_w / 1000.0) * idle_hours_month
        total_kwh_month = kwh_load + kwh_idle

        monthly_electr_cost = total_kwh_month * electricity_kwh_cost
        daily_electr_cost = monthly_electr_cost / (HOURS_PER_MONTH / HOURS_PER_DAY)

        monthly_opex = monthly_electr_cost + monthly_fixed_cost_per_server
        daily_opex = monthly_opex / (HOURS_PER_MONTH / HOURS_PER_DAY)

        net_monthly_profit = gross_monthly_rev - monthly_opex
        net_daily_profit = gross_daily_rev - daily_opex
        net_yearly_profit = net_monthly_profit * 12.0

        if net_monthly_profit > 0 and total_rig_price > 0:
            payback_months = round(total_rig_price / net_monthly_profit, 1)
            payback_days = int(round(total_rig_price / net_daily_profit))
            roi_annual_pct = round((net_yearly_profit / total_rig_price) * 100.0, 1)
        else:
            payback_months = None
            payback_days = None
            roi_annual_pct = 0.0

        net_margin_pct = round((net_monthly_profit / gross_monthly_rev * 100.0), 1) if gross_monthly_rev > 0 else 0.0

        rows.append({
            "Конфігурація": config_name,
            "Карта": gpu_name,
            "К-сть GPU": num_gpus,
            "Ціна карти ($)": round(card_price, 1),
            "Ціна платформи ($)": round(plat_cost, 1),
            "Вартість сервера ($)": round(total_rig_price, 1),
            "Оренда / 1 GPU ($/год)": round(hourly_rate_per_gpu, 4),
            "Оренда сервера ($/год)": round(server_hourly_rate_gross, 4),
            "Утилізація (%)": util_pct,
            "Споживання сервера (Вт)": int(round(wall_rig_load_w)),
            "Споживання в простої (Вт)": int(round(wall_rig_idle_w)),
            "Світло ($/міс)": round(monthly_electr_cost, 2),
            "Валовий дохід ($/міс)": round(gross_monthly_rev, 2),
            "Чистий прибуток ($/день)": round(net_daily_profit, 2),
            "Чистий прибуток ($/міс)": round(net_monthly_profit, 2),
            "Чистий прибуток ($/рік)": round(net_yearly_profit, 2),
            "Окупність (місяців)": payback_months,
            "Окупність (днів)": payback_days,
            "Річний ROI (%)": roi_annual_pct,
            "Маржа (%)": net_margin_pct,
            "Всього серверів (шт)": int(srow.get("Всього серверів (шт)", 0)),
            "Доступно (шт)": int(srow.get("Доступно (шт)", 0)),
        })

    return pd.DataFrame(rows)


