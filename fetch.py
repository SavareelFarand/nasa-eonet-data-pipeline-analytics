import requests
import json
import ijson
import sqlite3
from requests.exceptions import ConnectionError, Timeout
import time
from datetime import datetime
from decimal import Decimal
import logging
import os


def log_folder():
    """Define and create a dedicated folders for log"""

    log_dir = os.path.join(os.getcwd(), "logs")
    os.makedirs(log_dir, exist_ok=True)

    # Define the full path to the log file
    log_file = os.path.join(log_dir, "fetch.log")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file)
        ],
        # Force function to repeatly be used
        force=True

    )


def decimal_to_float(obj):
    """Recursively walks polygons (list of Decimal), converting every Decimal to float"""

    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, list):
        return [decimal_to_float(item) for item in obj]
    return obj


def check_user_input():
    """Validate user input and accept it if its a number between 1 and 10000"""

    attempts_left = 3
    while attempts_left > 0:
        user = input("How many events do you want to fetch? (1-10000): ").strip()
        if not user:
            raise SystemExit

        if user.isdecimal() and 1 <= int(user) <= 10000:
            return int(user)

        attempts_left -= 1
        if attempts_left > 0:
            print("Invalid Input! Please enter a number between 1 and 10000.")
        else:
            print("Invalid input, Try again next time!")
            raise SystemExit


def check_status_input():
    """Attempts every part of event the user want to fetch. Either that be open, closed, or both"""

    attempts_left = 3
    while attempts_left > 0:
        status = input("Fetch which status? (open/closed/both): ").strip().lower()

        if status == "both":
            return "all"
        if status in ("open", "closed"):
            return status

        attempts_left -= 1
        if attempts_left > 0:
            print("Invalid input! Please type open, closed, or both")
        else:
            print("Invalid input, Try again next time!")
            raise SystemExit


def check_date_range(start_prompt, end_prompt):

    def check_date_input(prompt):
        attempts_left = 3
        while attempts_left > 0:
            user_date = (input(prompt) or "").strip()
            if user_date.lower() in ("exit", "enter", ""):
                raise SystemExit

            try:
                datetime.strptime(user_date, "%Y-%m-%d")
                return user_date
            except ValueError:
                attempts_left -= 1
                if attempts_left > 0:
                    print("Invalid date format! Please use YYYY-MM-DD format, or leave blank to exit")
                else:
                    print("Invalid input, Try again next time!")
                    break
        raise SystemExit

    attempts_left = 3
    while attempts_left > 0:
        start = check_date_input(start_prompt)
        end = check_date_input(end_prompt)

        if start <= end:
            return start, end

        attempts_left -= 1
        if attempts_left > 0:
            print(
                f"Start date ({start}) must be before or equal to end date ({end}). Please try again")
        else:
            print("Invalid input, Try again next time!")
            break
    raise SystemExit


def build_query(limit, status, start, end):
    params: dict[str, str | int] = {"limit": limit}
    if status:
        params["status"] = status
    if start:
        params["start"] = start
    if end:
        params["end"] = end

    return params


def fetch_with_backoff(url, max_retries=4):
    delay = 3
    for attempt in range(max_retries):
        try:
            response = session.get(url, timeout=30, stream=True)
            if response.status_code in (429, 503):

                # We ask the server directly to ask how long we have to wait, the server will give a number
                retry_after = response.headers.get("Retry-After")

                if retry_after:
                    wait = int(retry_after)
                else:
                    wait = delay

                logger.info(
                    f"Got {response.status_code} status code, waiting for {wait}s before retrying (attempt {attempt+1})...")
                time.sleep(wait)
                delay *= 2
                continue
            response.raise_for_status()
            return response
        except (Timeout, ConnectionError):
            logger.info(f"Timed out, retrying in {delay}s...")
            time.sleep(delay)
            delay *= 2
    logger.error("Max retries exceeded — fetching stopped to avoid further strain on the API")
    raise Exception("Max Retries exceeded")


log_folder()
logger = logging.getLogger(__name__)
limit = check_user_input()
status = check_status_input()
start, end = check_date_range(
    "Start date (YYYY-MM-DD) [exit/enter]: ",
    "End date (YYYY-MM-DD) [exit/enter]: " 
)

params = build_query(limit, status, start, end)
query_string = '&'.join(f"{k}={v}" for k, v in params.items())
url = f"https://eonet.gsfc.nasa.gov/api/v3/events?{query_string}"

# Reuse connection to reduce overhead for 10,000 API requests
session = requests.Session()

# Identify the project to NASA's API to respect data server and ethical scraping compliance
session.headers.update({"User-Agent": "EONET-Portfolio-Project (student research)"})

logger.info(f"Starting fetch: limit={limit}, status={status}, start={start}, end={end}")

try:
    response = fetch_with_backoff(url)
except Exception as e:
    logger.error(f"API Request Error: {e}")
    print("There was an error during the API request \nWait a while then try again!")
    raise SystemExit

conn = sqlite3.connect("raw_data.sqlite")
cur = conn.cursor()
cur.executescript("""
    CREATE TABLE IF NOT EXISTS events (
        id TEXT PRIMARY KEY,
        title TEXT,
        description TEXT,
        link TEXT,
        closed TEXT
    );

    CREATE TABLE IF NOT EXISTS event_categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id TEXT,
        category_id TEXT,
        title TEXT,
        UNIQUE(event_id, category_id),                  --prevent duplicates
        FOREIGN KEY (event_id) REFERENCES events(id)
    );

    CREATE TABLE IF NOT EXISTS event_sources (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id TEXT,
        source_id TEXT,
        url TEXT,
        UNIQUE(event_id, source_id),
        FOREIGN KEY (event_id) REFERENCES events(id)
    );

    CREATE TABLE IF NOT EXISTS event_geometry (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id TEXT,
        magnitude_value REAL,
        magnitude_unit TEXT,
        date TEXT,
        type TEXT,
        lon REAL,
        lat REAL,
        coords TEXT,
        UNIQUE(event_id, date, lon, lat, coords),
        FOREIGN KEY (event_id) REFERENCES events(id)
    );
""")

success = True
event_count = 0
# Stream JSON with ijson to avoid loading all 10,000 events into memory at once
try:
    for event in ijson.items(response.raw, "events.item"):
        event_id = event["id"]
        title = event.get("title")
        desc = event.get("description")
        link = event.get("link")
        closed = event.get("closed")

        event_count += 1

        cur.execute("INSERT OR IGNORE INTO events (id, title, description, link, closed) VALUES (?, ?, ?, ?, ?)",
                    (event_id, title, desc, link, closed))

        for cat in event["categories"]:
            cat_id = cat["id"]
            cat_title = cat["title"]

            cur.execute("INSERT OR IGNORE INTO event_categories (event_id, category_id, title) VALUES (?, ?, ?)",
                        (event_id, cat_id, cat_title))

        for src in event["sources"]:
            src_id = src["id"]
            src_url = src["url"]

            cur.execute("INSERT OR IGNORE INTO event_sources (event_id, source_id, url) VALUES (?, ?, ?)",
                        (event_id, src_id, src_url))

        for geo in event["geometry"]:
            try:
                mag_val = float(geo.get("magnitudeValue"))  # float(None)
            except TypeError:
                mag_val = None
            mag_un = geo.get("magnitudeUnit")
            date = geo["date"]
            geo_type = geo["type"]

            if geo_type.lower() == "point":
                lon = float(geo["coordinates"][0])
                lat = float(geo["coordinates"][1])
                coords = None
            elif geo_type.lower() == "polygon":
                lon = None
                lat = None
                coords = json.dumps(decimal_to_float(geo["coordinates"][0]))
            else:
                logger.warning(f"Unknown geometry type: {geo_type}")
                continue

            cur.execute("""INSERT OR IGNORE INTO event_geometry (event_id, magnitude_value, magnitude_unit, date, type, lon, lat, coords)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", (event_id, mag_val, mag_un, date, geo_type, lon, lat, coords))

    logger.debug(f"event_count: {event_count}")

except Exception:
    success = False
    logger.exception("Data stream was incomplete")

finally:
    conn.commit()
    cur.close()
    conn.close()

# Equal count suggests data may be truncated by the limit, consider to increase the limit if you need all events in this date range
if event_count == limit:
    logger.warning(
        f"Returned {event_count} events, equals to limit: {limit} — data may be truncated")
    print("Data may be truncated — consider rerunning with a higher limit for this date range\n")

if success:
    logger.info(f"Fetching Success: {event_count} events processed")
    print('='*10, "Go to parse.py to parse them further", 10*'=')
else:
    logger.error("Fetching Failed — data stream was incomplete")
    print("Fetching Failed, Try again next time!")