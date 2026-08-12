import sqlite3
import pandas as pd
import geopandas as gpd
import logging
import os
import json
import re

conn = sqlite3.connect("raw_data.sqlite")
cur = conn.cursor()

pars_conn = sqlite3.connect("parsed_data.sqlite")
pars_cur = pars_conn.cursor()


def log_folder():
    """Define and create a dedicated folders for log"""

    log_dir = os.path.join(os.getcwd(), "logs")
    os.makedirs(log_dir, exist_ok=True)

    # Define the full path to the log file
    log_file = os.path.join(log_dir, "parse.log")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file)
        ],
        # Force function to repeatly be used
        force=True

    )


def clear_category(title, category_id):
    """Clean event title (e.g. wildfires) into human-readable one (Wildfires)
       Helper function for category() and timeline()"""

    def is_blank(value):
        return value is None or value.strip() == ""

    try:
        if is_blank(title) and is_blank(category_id):
            return "Unknown"
        elif not is_blank(title):
            return title.strip().title()
        else:
            # separate word to make it readable
            return re.sub(r"(?<!^)(?=[A-Z])", " ", category_id).title()
    except Exception:
        logger.exception("Datahelp error")
        raise


def region():
    """Match any coordinates from raw_data.sqlite into EEZ land file then saves them to parsed_data.sqlite"""

    pars_cur.execute("""
        CREATE TABLE IF NOT EXISTS coordinates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT,
            lon REAL,
            lat REAL,
            coords TEXT,
            territory TEXT,
            UNIQUE(event_id, lon, lat, coords)
        )
    """)
    cur.execute("SELECT event_id, lon, lat, coords FROM event_geometry")

    try:
        logger.info("Starting region()...")
        world = gpd.read_file("EEZ_land_union_v4_202410/EEZ_land_union_v4_202410.shp")

        data_points = cur.fetchall()
        points_data = []

        skipped_empty_polygons = 0

        for event_id, lon, lat, coords in data_points:
            # Check if polygon
            if coords is not None:
                polygon_points = json.loads(coords)

                if polygon_points:

                    # Calculate the average of each longitude and latitude
                    center_lon = sum((p[0] for p in polygon_points)) / len(polygon_points)
                    center_lat = sum((p[1] for p in polygon_points)) / len(polygon_points)

                    polygon_json = coords
                else:
                    skipped_empty_polygons += 1
                    continue

            else:
                center_lon = lon
                center_lat = lat
                polygon_json = None

            points_data.append((event_id, center_lon, center_lat, polygon_json))

        logger.info(f"Skipped {skipped_empty_polygons} empty polygons")

        # Spatial join matches each point to the EEZ/land polygon it falls within
        # Vectorized in GeoPandas, much faster than looping with regular looping
        df = pd.DataFrame(points_data, columns=["event_id", "lon", "lat", "polygon_coords"])
        gdf_points = gpd.GeoDataFrame(
            df, geometry=gpd.points_from_xy(df.lon, df.lat), crs=world.crs)
        joins = gpd.sjoin(gdf_points, world, how="left", predicate="within")

        rows_to_insert = []

        for row in joins.itertuples():

            if pd.isna(row.SOVEREIGN1):

                # Under the Antarctic Treaty Article VI
                # Any latitude that is equal to or less than -60° is part of Antarctica
                if pd.to_numeric(row.lat) <= -60:
                    territory = "Antarctica"
                else:
                    territory = "high seas"

            else:
                territory = row.SOVEREIGN1

            rows_to_insert.append((row.event_id, row.lon, row.lat, row.polygon_coords, territory))

        pars_cur.executemany("INSERT OR IGNORE INTO coordinates (event_id, lon, lat, coords, territory) VALUES (?, ?, ?, ?, ?)",
                             rows_to_insert)
        logger.info(f"Coordinates: inserted {pars_cur.rowcount}")

        pars_cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_coordinates_territory ON coordinates (territory)")

    except Exception as e:
        logger.exception("Dataparse 1 error")
        raise SystemExit(e)


def category():
    """Clean title into human-readable one"""

    logger.info("Starting category()...")
    pars_cur.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT,
            category_id TEXT,           -- Added this if I need to debug it elsewhere
            title TEXT,
            UNIQUE(event_id, category_id)
        )
    """)
    cur.execute("SELECT event_id, category_id, title FROM event_categories")

    try:
        rows = cur.fetchall()

        # EONET_20558 | wildfires | Wildfires
        rows_to_insert = []
        for event_id, category_id, title in rows:
            pars_title = clear_category(title, category_id)
            rows_to_insert.append((event_id, category_id, pars_title))

        pars_cur.executemany("INSERT OR IGNORE INTO categories (event_id, category_id, title) VALUES (?, ?, ?)",
                             rows_to_insert)

        pars_cur.execute("CREATE INDEX IF NOT EXISTS idx_categories_title ON categories (title)")
    except Exception as e:
        logger.exception("Dataparse 2 error")
        raise SystemExit(e)


def timeline():
    """Extracts, cleans, and indexes event dates and titles into a timeline table"""

    logger.info("Starting timeline()...")
    pars_cur.execute("""
        CREATE TABLE IF NOT EXISTS timelines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT,
            title TEXT,
            date TEXT,
            UNIQUE(event_id, date)
        )
    """)
    cur.execute("""
        SELECT eg.event_id, ec.category_id, ec.title,
        SUBSTR(eg.date, 1, 10) AS date
        FROM event_geometry AS eg
        JOIN event_categories AS ec ON eg.event_id = ec.event_id
    """)

    try:
        rows = cur.fetchall()

        rows_to_insert = []
        for event_id, category_id, title, date in rows:
            pars_title = clear_category(title, category_id)
            rows_to_insert.append((event_id, pars_title, date))

        pars_cur.executemany("INSERT OR IGNORE INTO timelines (event_id, title, date) VALUES (?, ?, ?)",
                             rows_to_insert)
        pars_cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_timelines_title_date ON timelines (title, date)")
    except Exception as e:
        logger.exception("Dataparse 3 error")
        raise SystemExit(e)


log_folder()
logger = logging.getLogger(__name__)


try:
    print("Loading...")
    region()
    category()
    timeline()
    logger.info("Parsing complete: region(), category(), timeline() all finished")
    print("Parsing Success! Go to parse_data.sqlite to see the data")
    print('='*10, "Go to graph.py to see the graph of the data", 10*'=')
except SystemExit as e:
    logger.error(f"Dataparse step failed, exiting: {e}")
except Exception:
    logger.exception("SQL Table Error")
except KeyboardInterrupt:
    logger.info('Program stopped by user')
finally:
    pars_conn.commit()
    pars_cur.close()
    pars_conn.close()
    cur.close()
    conn.close()