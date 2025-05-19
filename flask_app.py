import os
from flask import Flask, jsonify, request, Response, send_file
from dotenv import load_dotenv
from io import BytesIO

# Import your modularized functions
# Assuming sec_data_processor.py is in the same directory or your Python path is set up
try:
    from sec_data_processor import (
        get_company_financial_details,
        generate_metric_plot_as_bytes,
        METRICS_TO_EXTRACT # If you need to validate metric_key
    )
except ImportError:
    # This error handling is more for local development;
    # on PythonAnywhere, ensure files are in the correct place.
    print("Error: Could not import from sec_data_processor.py. Make sure it's in the same directory or PYTHONPATH.")
    # You might want to define dummy functions or raise an error to prevent app from starting misconfigured
    def get_company_financial_details(ticker): return None, "Module not loaded"
    def generate_metric_plot_as_bytes(*args, **kwargs): return None
    METRICS_TO_EXTRACT = {}


# Load environment variables from .env file (especially for local development)
# PythonAnywhere can also set environment variables via its web UI
load_dotenv()

# Initialize the Flask app
app = Flask(__name__)

# --- API Endpoints ---

@app.route('/')
def home():
    return "Financial Data API is running!"

@app.route('/company/<string:ticker_symbol>/financials', methods=['GET'])
def get_financials_route(ticker_symbol):
    # You could also allow users to specify metrics via query parameters
    # e.g., request.args.getlist('metrics')
    details, error = get_company_financial_details(ticker_symbol)

    if error:
        return jsonify({"error": error}), 404 # Or another appropriate status code
    if not details:
        return jsonify({"error": "No details found for the ticker."}), 404
    
    # Convert datetime objects in data to ISO format strings for JSON compatibility
    # FastAPI handles this automatically, Flask's jsonify might or might not based on config/version.
    # It's safer to do it explicitly if your data_list contains datetime objects.
    if details.get("metrics"):
        for metric_name, metric_info in details["metrics"].items():
            if metric_info.get("data"):
                for item in metric_info["data"]:
                    if 'EndDate' in item and hasattr(item['EndDate'], 'isoformat'):
                        item['EndDate'] = item['EndDate'].isoformat()
                    if 'Filed' in item and hasattr(item['Filed'], 'isoformat'):
                        item['Filed'] = item['Filed'].isoformat()
    
    return jsonify(details)

@app.route('/company/<string:ticker_symbol>/plot/<string:metric_key>', methods=['GET'])
def get_plot_route(ticker_symbol: str, metric_key: str):
    if metric_key not in METRICS_TO_EXTRACT:
        return jsonify({"error": f"Invalid metric key. Available: {list(METRICS_TO_EXTRACT.keys())}"}), 400

    details, error = get_company_financial_details(ticker_symbol)
    if error:
        return jsonify({"error": error}), 404
    if not details or metric_key not in details.get("metrics", {}):
        return jsonify({"error": f"Data for metric '{metric_key}' not found for ticker '{ticker_symbol}'."}), 404

    metric_data_list = details["metrics"][metric_key]["data"]
    unit = details["metrics"][metric_key]["unit"]
    company_display_name = details["company_display_name"]

    if not metric_data_list:
        return jsonify({"error": f"No data points found for metric '{metric_key}' for ticker '{ticker_symbol}'."}), 404

    plot_bytes = generate_metric_plot_as_bytes(
        metric_data_list,
        metric_key,
        company_display_name,
        unit
    )

    if not plot_bytes:
        return jsonify({"error": "Failed to generate plot."}), 500
    
    return send_file(BytesIO(plot_bytes), mimetype='image/png')

# This part is for running the Flask app locally for development/testing
# PythonAnywhere will use a different method to run it (via WSGI)
if __name__ == '__main__':
    # Ensure USER_AGENT is set in sec_data_processor if it's used directly from there
    # or pass it to functions if they require it.
    # Your sec_data_processor.py already sets SEC_HEADERS['User-Agent'] globally.
    
    # Check if USER_AGENT was set properly from .env or fallback
    from sec_data_processor import USER_AGENT as SCRIPT_USER_AGENT # Import to check
    print(f"Flask App INFO: Using User-Agent: '{SCRIPT_USER_AGENT}'")
    if "PLEASE_UPDATE" in SCRIPT_USER_AGENT:
         print("Flask App CRITICAL: Update the USER_AGENT in your script's configuration or .env file.")
    
    app.run(debug=True) # debug=True is for development only