import os
from dotenv import load_dotenv

load_dotenv() # This line loads variables from .env into os.environ

# ... rest of your imports and code ...
# The USER_AGENT setup logic using os.environ.get() will then pick it up.

import requests
import json
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime
from io import BytesIO # For handling image data in memory

# --- Configuration ---

# User-Agent Setup for local environment (VS Code)
# Your desired User-Agent string will be used as a fallback.
DESIRED_USER_AGENT_FALLBACK = "MyFinancialReporter/1.0 (avichalai2004@gmail.com)"

# Try to get the User-Agent from an environment variable named 'SEC_USER_AGENT'.
# If the environment variable is not set, it uses your DESIRED_USER_AGENT_FALLBACK.
USER_AGENT = os.environ.get('SEC_USER_AGENT', DESIRED_USER_AGENT_FALLBACK)

# Informative print statement about which User-Agent is being used
if USER_AGENT == DESIRED_USER_AGENT_FALLBACK and 'SEC_USER_AGENT' not in os.environ:
    print(f"INFO: Environment variable 'SEC_USER_AGENT' not set. Using fallback User-Agent: '{USER_AGENT}'")
elif 'SEC_USER_AGENT' in os.environ : # Checks if the SEC_USER_AGENT env var is explicitly set
    print(f"INFO: Using User-Agent from environment variable 'SEC_USER_AGENT': '{USER_AGENT}'")
# No specific message needed if SEC_USER_AGENT is set and matches the fallback,
# or if you just want one confirmation message:
# print(f"INFO: Using User-Agent: '{USER_AGENT}'")


# Global headers for SEC requests, initialized after USER_AGENT is determined
SEC_HEADERS = {'User-Agent': USER_AGENT}

TICKER_CIK_MAP = {
    "NVDA": "0001045810",
    "AAPL": "0000320193",
    "MSFT": "0000789019",
    "GOOGL": "0001652044",
    "GOOG": "0001652044",
    "AMZN": "0001018724",
    "TSLA": "0001318605",
    "META": "0001326801",
}

METRICS_TO_EXTRACT = {
    "Revenue": {"tag": "Revenues", "unit": "USD"},
    "Net Income": {"tag": "NetIncomeLoss", "unit": "USD"},
    "EPS (Basic)": {"tag": "EarningsPerShareBasic", "unit": "USD/shares"}
}

# --- Core Logic Functions ---

def get_cik_from_ticker(ticker_symbol: str) -> str | None:
    """Looks up CIK from the predefined TICKER_CIK_MAP."""
    return TICKER_CIK_MAP.get(ticker_symbol.upper())

def fetch_company_financial_facts(cik_number: str) -> tuple[dict | None, str | None]:
    """
    Fetches all company financial facts from SEC Edgar for a given CIK.
    Returns a tuple: (json_data, error_message).
    If successful, json_data is the parsed JSON and error_message is None.
    If failed, json_data is None and error_message contains the error.
    """
    if not cik_number:
        return None, "CIK number cannot be empty."

    facts_url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik_number}.json"
    try:
        response = requests.get(facts_url, headers=SEC_HEADERS)
        response.raise_for_status()  # Raises HTTPError for bad responses (4XX or 5XX)
        return response.json(), None
    except requests.exceptions.HTTPError as http_err:
        err_msg = f"HTTP error: {http_err}"
        if hasattr(http_err, 'response') and http_err.response is not None:
             err_msg += f" - Status: {http_err.response.status_code} - Body: {http_err.response.text[:200]}"
        return None, err_msg
    except requests.exceptions.RequestException as req_err:
        return None, f"Request error: {req_err}"
    except json.JSONDecodeError:
        return None, "Failed to decode JSON response from SEC API."

def get_historical_facts_for_metric(all_company_facts_json: dict, metric_tag: str, unit_type: str) -> list[dict]:
    """
    Extracts historical values for a given metric tag from the SEC facts data.
    (This is largely your existing function, adapted for clarity and consistent return)
    """
    historical_data = []
    if not all_company_facts_json or 'us-gaap' not in all_company_facts_json or \
       metric_tag not in all_company_facts_json['us-gaap']:
        # print(f"Warning: Metric tag '{metric_tag}' not found or data missing.") # Less verbose for API
        return historical_data

    metric_info = all_company_facts_json['us-gaap'][metric_tag]

    if unit_type not in metric_info['units']:
        available_units = list(metric_info['units'].keys())
        if available_units:
            # print(f"Warning: Unit '{unit_type}' not found for {metric_tag}. Using '{available_units[0]}'.")
            unit_type = available_units[0]
        else:
            # print(f"Warning: No units found for {metric_tag}.")
            return historical_data

    all_filings_for_unit = metric_info['units'][unit_type]

    for fact in all_filings_for_unit:
        if fact.get('form') in ['10-K', '10-Q'] and 'val' in fact and fact.get('end') and fact.get('fp'):
            try:
                historical_data.append({
                    'EndDate': datetime.strptime(fact['end'], '%Y-%m-%d'),
                    'Value': float(fact['val']),
                    'Form': fact['form'],
                    'FiscalPeriod': fact['fp'],
                    'FiscalYear': fact['fy'],
                    'Filed': datetime.strptime(fact['filed'], '%Y-%m-%d')
                })
            except (ValueError, TypeError):
                # print(f"Skipping fact due to data conversion error: {fact}. Error: {e}") # Less verbose
                continue

    if historical_data:
        temp_df = pd.DataFrame(historical_data)
        temp_df.sort_values(by=['EndDate', 'Filed'], ascending=[True, True], inplace=True)
        # Convert to list of dicts after deduplication
        deduplicated_data = temp_df.drop_duplicates(subset=['EndDate'], keep='last').to_dict('records')
        
        # Ensure datetime objects are Python datetimes (pandas might make them Timestamps)
        # This is important if the direct list of dicts is used elsewhere before JSON serialization by FastAPI
        for item in deduplicated_data:
            if isinstance(item.get('EndDate'), pd.Timestamp):
                item['EndDate'] = item['EndDate'].to_pydatetime()
            if isinstance(item.get('Filed'), pd.Timestamp):
                item['Filed'] = item['Filed'].to_pydatetime()
        
        deduplicated_data.sort(key=lambda x: x['EndDate'])
        return deduplicated_data
    return []


def generate_metric_plot_as_bytes(metric_data_list: list[dict], display_name: str, 
                                  company_name_display: str, unit: str) -> bytes | None:
    """
    Generates a plot for a given metric's data (list of dicts) and returns it as PNG bytes.
    """
    if not metric_data_list:
        return None

    df_metric = pd.DataFrame(metric_data_list)
    if df_metric.empty or 'EndDate' not in df_metric.columns or 'Value' not in df_metric.columns:
        return None
    
    df_metric['EndDate'] = pd.to_datetime(df_metric['EndDate'])
    df_metric.set_index('EndDate', inplace=True)

    plt.figure(figsize=(10, 5)) # Adjusted size for potential embedding
    plt.plot(df_metric.index, df_metric['Value'], marker='o', linestyle='-')

    if not df_metric['Value'].empty and pd.api.types.is_numeric_dtype(df_metric['Value']):
        # Ensure values are numeric and not all NaN before trying to get max
        valid_values = df_metric['Value'].dropna()
        if not valid_values.empty:
            max_val = valid_values.abs().max()
            if max_val > 1e9:
                plt.gca().yaxis.set_major_formatter(plt.FuncFormatter(lambda x, loc: f"{x/1e9:.2f}B"))
            elif max_val > 1e6:
                plt.gca().yaxis.set_major_formatter(plt.FuncFormatter(lambda x, loc: f"{x/1e6:.2f}M"))
            elif "EPS" not in display_name and max_val > 0 : # Avoid K for EPS and zero/negative max_val
                plt.gca().yaxis.set_major_formatter(plt.FuncFormatter(lambda x, loc: f"{x/1e3:.2f}K"))

    plt.title(f"Historical {display_name} for {company_name_display} ({unit})")
    plt.xlabel("Period End Date")
    plt.ylabel(display_name)
    plt.grid(True)
    plt.xticks(rotation=45)
    plt.tight_layout()

    img_bytes_io = BytesIO()
    plt.savefig(img_bytes_io, format='PNG', bbox_inches='tight')
    plt.close() # Close the figure to free up memory
    img_bytes_io.seek(0)
    return img_bytes_io.getvalue()

# --- Orchestration Function ---

def get_company_financial_details(ticker_symbol: str) -> tuple[dict | None, str | None]:
    """
    Orchestrates fetching CIK, company facts, and extracting all defined metrics.
    Returns a dictionary with company info and metrics data, or an error message.
    """
    cik = get_cik_from_ticker(ticker_symbol)
    if not cik:
        return None, f"CIK not found for ticker '{ticker_symbol}' in predefined map."

    all_company_facts_json, error_msg = fetch_company_financial_facts(cik)
    if error_msg:
        return None, f"Failed to fetch data for {ticker_symbol} (CIK: {cik}): {error_msg}"
    if not all_company_facts_json: # Should be covered by error_msg, but good for robustness
        return None, f"No data returned from SEC API for {ticker_symbol} (CIK: {cik})."

    company_name = all_company_facts_json.get('entityName', ticker_symbol)
    company_display_name = f"{company_name} ({ticker_symbol})"

    results = {
        "company_name": company_name,
        "company_display_name": company_display_name,
        "ticker": ticker_symbol,
        "cik": cik,
        "metrics": {} # Store data for each metric
    }

    for display_name_key, metric_details_val in METRICS_TO_EXTRACT.items():
        tag_name = metric_details_val["tag"]
        unit = metric_details_val["unit"]
        
        # Pass the 'facts' part of the JSON to the extraction function
        metric_data_list = get_historical_facts_for_metric(
            all_company_facts_json.get('facts', {}), # Safely get 'facts'
            tag_name,
            unit
        )
        results["metrics"][display_name_key] = {
            "data": metric_data_list,
            "unit": unit,
            "tag": tag_name
        }
    return results, None

# --- Main Execution (for testing the functions) ---
if __name__ == "__main__":
    print(f"Using User-Agent: {USER_AGENT}")
    if "PLEASE_UPDATE" in USER_AGENT:
        print("CRITICAL: Update the USER_AGENT in the script's configuration section or via Colab Secrets for reliable SEC API access before proceeding.")
        # exit() # Uncomment to halt if USER_AGENT is not set

    ticker_input = input("Enter company ticker symbol (e.g., NVDA, AAPL): ").upper()

    financial_details, error = get_company_financial_details(ticker_input)

    if error:
        print(f"\nError processing {ticker_input}: {error}")
    elif financial_details:
        print(f"\n--- Financial Details for {financial_details['company_display_name']} ---")
        for metric_display_name, metric_info in financial_details["metrics"].items():
            print(f"\nMetric: {metric_display_name} ({metric_info['unit']})")
            data_list = metric_info["data"]
            if data_list:
                # For display purposes, convert to DataFrame
                df_display = pd.DataFrame(data_list)
                if not df_display.empty:
                    # Select specific columns to print, ensure 'EndDate' is a column for printing
                    cols_to_print = ['EndDate', 'Value', 'Form', 'FiscalPeriod', 'FiscalYear']
                    existing_cols = [col for col in cols_to_print if col in df_display.columns]
                    print(df_display[existing_cols].tail().to_string())

                    # Generate and attempt to display plot (useful in IPython/Jupyter)
                    plot_bytes = generate_metric_plot_as_bytes(
                        data_list,
                        metric_display_name,
                        financial_details['company_display_name'],
                        metric_info['unit']
                    )
                    if plot_bytes:
                        print(f"Generated plot for {metric_display_name} ({len(plot_bytes)} bytes).")
                        try:
                            try:
                                from IPython.display import Image, display
                                display(Image(data=plot_bytes))
                            except ImportError:
                                print(f"To view plot for {metric_display_name}, save bytes to a file or run in an IPython environment.")
                        except ImportError:
                            print(f"To view plot for {metric_display_name}, save bytes to a file or run in an IPython environment.")
                            # Example: Save plot to a file
                            # plot_filename = f"{ticker_input.lower()}_{metric_display_name.lower().replace(' ', '_').replace('(', '').replace(')', '')}.png"
                            # with open(plot_filename, "wb") as f:
                            #     f.write(plot_bytes)
                            # print(f"Plot saved as {plot_filename}")
            else:
                print("No data found for this metric.")
    else:
        print(f"No financial details retrieved for {ticker_input}.")