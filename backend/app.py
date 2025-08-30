from flask import Flask, request, jsonify
import requests
from flask import render_template
import sqlite3
import datetime
import os
import json
from datetime import datetime, timedelta

app = Flask(__name__)

# Database setup
DB_PATH = os.path.join(os.path.dirname(__file__), "search_history.db")


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Create SearchHistory table
    cursor.execute(
        """
    CREATE TABLE IF NOT EXISTS SearchHistory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker TEXT NOT NULL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """
    )

    # Create CachedStockData table
    cursor.execute(
        """
    CREATE TABLE IF NOT EXISTS CachedStockData (
        ticker TEXT PRIMARY KEY,
        company_json TEXT,
        stock_json TEXT,
        last_updated DATETIME
    )
    """
    )

    conn.commit()
    conn.close()


# Initialize the database
init_db()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/search", methods=["GET"])
def get_stock_data():
    ticker = request.args.get("ticker")
    if not ticker:
        return jsonify({"error": "Ticker is required"}), 400

    ticker = ticker.upper()
    api_key = "8fcdab89525b84d2bf01ec2a7300de63c004d70f"

    # Check if we have cached data
    cached_data = get_cached_data(ticker)

    # If we have valid cached data, return it
    if cached_data:
        save_search(ticker)  # Still record the search in history
        return jsonify({**cached_data, "cached": True})

    # Otherwise, fetch from API
    daily_url = f"https://api.tiingo.com/tiingo/daily/{ticker}?token={api_key}"
    iex_url = f"https://api.tiingo.com/iex/{ticker}?token={api_key}"

    try:
        # Fetch data from tiingo daily API
        daily_response = requests.get(daily_url)
        daily_response.raise_for_status()
        daily_data = daily_response.json()

        # Fetch data from tiingo IEX API
        iex_response = requests.get(iex_url)
        iex_response.raise_for_status()
        iex_data = iex_response.json()

        # Save successful search to database
        save_search(ticker)

        # Cache the API responses
        cache_stock_data(ticker, daily_data, iex_data)

        # Combine the data into a single response
        combined_data = {"daily": daily_data, "iex": iex_data, "cached": False}
        return jsonify(combined_data)
    except requests.exceptions.RequestException as e:
        return jsonify({"error": str(e)}), 500


def save_search(ticker):
    """Save a successful search to the database"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO SearchHistory (ticker) VALUES (?)", (ticker.upper(),))
    conn.commit()
    conn.close()


def get_cached_data(ticker):
    """Check if we have cached data for this ticker that's less than 15 minutes old"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        "SELECT company_json, stock_json, last_updated FROM CachedStockData WHERE ticker = ?",
        (ticker,),
    )
    row = cursor.fetchone()
    conn.close()

    if row:
        last_updated = datetime.fromisoformat(row["last_updated"])
        # Check if the data is less than 15 minutes old
        if datetime.utcnow() - last_updated < timedelta(minutes=15):
            # Use cached result
            return {
                "daily": json.loads(row["company_json"]),
                "iex": json.loads(row["stock_json"]),
            }

    # Either no cached data or it's too old
    return None


def cache_stock_data(ticker, company_data, stock_data):
    """Cache API responses in the database"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    current_time = datetime.utcnow().isoformat()

    # Convert Python objects to JSON strings for storage
    company_json = json.dumps(company_data)
    stock_json = json.dumps(stock_data)

    # Insert or replace existing data
    cursor.execute(
        """
        INSERT OR REPLACE INTO CachedStockData 
        (ticker, company_json, stock_json, last_updated) 
        VALUES (?, ?, ?, ?)
        """,
        (ticker, company_json, stock_json, current_time),
    )

    conn.commit()
    conn.close()


@app.route("/history", methods=["GET"])
def get_search_history():
    """Return the last 10 searches"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        "SELECT ticker, timestamp FROM SearchHistory ORDER BY timestamp DESC LIMIT 10"
    )
    rows = cursor.fetchall()

    # Convert to list of dictionaries
    history = [{"ticker": row["ticker"], "timestamp": row["timestamp"]} for row in rows]
    conn.close()
    return jsonify(history)


if __name__ == "__main__":
    app.run(debug=True)
