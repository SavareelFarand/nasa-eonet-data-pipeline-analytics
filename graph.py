import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
import sqlite3
import logging
import argparse
import os

conn = sqlite3.connect("parsed_data.sqlite")
cur = conn.cursor()


def log_folder():
    """Define and create a dedicated folders for log"""

    log_dir = os.path.join(os.getcwd(), "logs")
    os.makedirs(log_dir, exist_ok=True)

    # Define the full path to the log file
    log_file = os.path.join(log_dir, "graph.log")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file)
        ],
        # Force function to repeatly be used
        force=True

    )


def is_valid(date_str, label):
    """Check if user input is in datetime, else return None"""

    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return date_str
    except ValueError:
        logger.info(f"User typed invalid {label} date format ({date_str})")
        return None


def get_date_range():
    """Get date range and check any errors from user input"""

    logger.info("Get user date range...")
    parser = argparse.ArgumentParser(description="Generate EONET event graphs")
    parser.add_argument("--start", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, help="End date (YYYY-MM-DD)")
    args = parser.parse_args()

    start, end = args.start, args.end

    attempts_left = 3
    while attempts_left > 0:

        if not start:
            start = input("Start date (YYYY-MM-DD): ").strip()
        if not end:
            end = input("End date (YYYY-MM-DD): ").strip()

        # Count user wrong input
        faults = 0
        if start and not is_valid(start, "start"):
            print(f"Invalid start date ({start})")
            faults += 1
        if end and not is_valid(end, "end"):
            print(f"Invalid end date ({end})")
            faults += 1

        # Catch if either start, end, or both aren't datetime
        if faults == 1:
            attempts_left -= 1
            start, end = None, None  # Reset to None for CLI usage
            print("Wrong date either start or end date. Must be in YYYY-MM-DD format")
            continue
        if faults == 2:
            attempts_left -= 1
            start, end = None, None
            print("Wrong date input for both start and end date. Must be in YYYY-MM-DD format")
            continue

        start_dt = datetime.strptime(start, "%Y-%m-%d")
        end_dt = datetime.strptime(end, "%Y-%m-%d")

        if start_dt < end_dt:
            return start, end
        else:
            print(f"Start date ({start}) must be less than end date ({end})")
            attempts_left -= 1
            start, end = None, None
    raise SystemExit


def build_date(alias, start, end):
    """build user date for SQL queries"""

    clauses = []
    params = []

    if start:
        clauses.append(f"{alias}.date >= ?")
        params.append(start)
    if end:
        clauses.append(f"{alias}.date <= ?")
        params.append(end)

    return clauses, params


def country_ranking(start=None, end=None):

    logger.info("Running country_ranking()...")

    clauses, params = build_date("t", start, end)
    where_extra = (" AND " + " AND ".join(clauses)) if clauses else ""
    cur.execute(f"""
    SELECT c.territory, COUNT(DISTINCT c.event_id) AS event_count
    FROM coordinates AS c
    JOIN timelines as t ON c.event_id = t.event_id
    WHERE c.territory NOT IN ('Antarctica', 'high seas')
    {where_extra}
    GROUP BY c.territory
    ORDER BY event_count DESC
    LIMIT 10
    """, params)

    rows = cur.fetchall()

    countries = [row[0] for row in rows]
    accumulations = [row[1] for row in rows]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(30, 7))

    # Linear scale
    bars1 = ax1.barh(countries, accumulations)
    ax1.invert_yaxis()
    ax1.set_xlabel("Number of Events", fontsize=12)
    ax1.set_title("Linear Scale (Actual data)", fontsize=15)
    ax1.bar_label(bars1, labels=[str(accul) for accul in accumulations], padding=4)

    # Log scale
    bars2 = ax2.barh(countries, accumulations)
    ax2.invert_yaxis()
    ax2.set_xscale("log")
    ax2.set_xlabel("Number of Events (log scale)", fontsize=12)
    ax2.set_title("Log Scale (Balanced view)", fontsize=15)
    ax2.bar_label(bars2, labels=[str(accul) for accul in accumulations], padding=4)

    fig.suptitle("Distribution of Natural Events Across Top 10 Countries",
                 fontweight="bold", fontsize=20)
    plt.tight_layout()
    plt.savefig(f"{file_output}/country_ranking.png", dpi=150)
    plt.close()


def category_ranking(start=None, end=None):

    logger.info("Running category_ranking()...")

    clauses, params = build_date("t", start, end)
    where_clause = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    cur.execute(f"""
    SELECT c.title, COUNT(DISTINCT c.event_id) AS event_count
    FROM categories AS c
    JOIN timelines AS t ON c.event_id = t.event_id
    {where_clause}
    GROUP BY c.title
    ORDER BY event_count DESC
    LIMIT 5
    """, params
    )

    rows = cur.fetchall()

    titles = [row[0] for row in rows]
    accumulations = [row[1] for row in rows]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(25, 6))

    # Linear scale
    bars1 = ax1.barh(titles, accumulations)
    ax1.invert_yaxis()
    ax1.set_xlabel("Number of Events", labelpad=15, fontsize=12)
    ax1.set_title("Linear Scale (Actual data)", fontsize=15)
    ax1.bar_label(bars1, labels=[str(accul) for accul in accumulations], padding=4)

    # Log scale
    bars2 = ax2.barh(titles, accumulations)
    ax2.invert_yaxis()
    ax2.set_xscale("log")
    ax2.set_xlabel("Number of Events (log scale)", labelpad=10, fontsize=12)
    ax2.set_title("Log Scale (Balanced view)", fontsize=15)
    ax2.bar_label(bars2, labels=[str(accul) for accul in accumulations], padding=4)

    fig.suptitle("Top 5 Natural Event Categories by Frequency", fontweight="bold", fontsize=20)
    plt.tight_layout()
    plt.savefig(f"{file_output}/category_ranking.png", dpi=150)
    plt.close()


def events_over_time(start=None, end=None):

    logger.info("Running events_over_time()...")

    clauses, params = build_date("timelines", start, end)
    where_clause = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    cur.execute(f"""
    SELECT title, strftime('%Y-%m', date) AS month, COUNT(DISTINCT event_id) AS event_count
    FROM timelines
    {where_clause}
    GROUP BY title, month
    ORDER BY title, month
    """, params)

    rows = cur.fetchall()

    # Reshape into dict for easier graphing
    category_data = {}
    for title, month, count in rows:
        if title not in category_data:
            category_data[title] = {}

        category_data[title][month] = count

    category_colors = {
        "Wildfires": "firebrick",
        "Floods": "darkblue",
        "Severe Storms": "indigo",
        "Sea And Lake Ice": "royalblue",
        "Volcanoes": "darkgoldenrod",
        "Drought": "sienna",
        "Dust And Haze": "grey",
        "Earthquakes": "darkkhaki",
        "Landslides": "saddlebrown",
        "Temperature Extremes": "darkmagenta",
        "Water Color": "seagreen",
        "Manmade": "black",
        "Snow": "skyblue"
    }

    # Get default color cycle for new categories
    default_colors = plt.rcParams["axes.prop_cycle"].by_key()["color"]
    color_counter = 0

    def get_category_color(title):
        """Check if title exists in category_color, if not generate, store then return new color"""
        nonlocal color_counter

        if title in category_colors:
            return category_colors[title]

        # Pick then store new color (wrap color_counter to stays bounded)
        color = default_colors[color_counter % len(default_colors)]
        category_colors[title] = color
        color_counter = (color_counter + 1) % len(default_colors)

        return color

    def get_sorted(title):
        """Extract title, YYYY-MM, and counts from category_data | dt = date"""

        dates_counts = category_data[title]
        sorted_dates = sorted(dates_counts.keys())
        datatypes_dt = [datetime.strptime(dt, "%Y-%m") for dt in sorted_dates]
        counts = [dates_counts[dt] for dt in sorted_dates]

        return datatypes_dt, counts

    def apply_date_format(ax):
        """Compute date format to be printed in a graphs"""

        locator = mdates.AutoDateLocator()
        formatter = mdates.ConciseDateFormatter(locator)
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(formatter)

    unique_categories = sorted(category_data.keys())

    # INDIVIDUAL CHARTS
    for title in unique_categories:
        dates_dt, counts = get_sorted(title)
        color = get_category_color(title)

        fig, ax = plt.subplots(figsize=(16, 5))
        x = mdates.date2num(dates_dt)  # Convert datetime to numbers
        ax.plot(x, counts, color=color, marker='o', markersize=3)
        ax.xaxis_date()  # Tells apply_date_format() that x is datetime

        ax.set_title(f"Monthly Trend: {title}", fontweight="bold", fontsize=14)
        ax.set_xlabel("Date")
        ax.set_ylabel("Event Count")
        apply_date_format(ax)

        plt.tight_layout()
        safe_name = title.lower().replace(' ', '_')
        plt.savefig(f"{file_output}/timeline_{safe_name}.png", dpi=150)
        plt.close(fig)

    # TRELLIS CHART | n refers to subplots
    n_categories = len(unique_categories)

    fig, axes = plt.subplots(
        n_categories, 1,
        figsize=(16, 3 * n_categories),
        sharex=True
    )

    if n_categories == 1:
        axes = [axes]

    for ax, title in zip(axes, unique_categories):
        dates_dt, counts = get_sorted(title)
        color = get_category_color(title)

        x = mdates.date2num(dates_dt)
        ax.plot(x, counts, color=color, marker='o', markersize=3)
        ax.xaxis_date()

        ax.set_title(title, fontsize=12)
        ax.set_ylabel("Event Count")
        apply_date_format(ax)

    axes[-1].set_xlabel("Date")
    fig.suptitle("Monthly Event Trends by Category", fontweight="bold", fontsize=18)
    plt.tight_layout(rect=(0, 0, 1, 0.97))
    plt.savefig(f"{file_output}/timeline_trellis.png", dpi=150)
    plt.close()


file_output = "result_graphs"
os.makedirs(file_output, exist_ok=True)

log_folder()
logger = logging.getLogger(__name__)

try:
    logger.info("Program started...")
    start_date, end_date = get_date_range()
    print("Loading...")
    country_ranking(start_date, end_date)
    category_ranking(start_date, end_date)
    events_over_time(start_date, end_date)
    print(f"Data Graphing Success! Go to the {file_output} file to see the results")
    logger.info("Program Successfully finished")
except SystemExit:
    logger.info("Successfuly defended against wrong input!")
    print("Invalid input, Try again next time!")
except Exception:
    logger.exception("Undetected problem")
except KeyboardInterrupt:
    logger.info("Program stopped")
    print("\nProgram stopped by user")
finally:
    cur.close()
    conn.close()