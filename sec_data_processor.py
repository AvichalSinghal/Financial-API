# sec_data_processor.py

import requests
import json
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime
from io import BytesIO
import os # For USER_AGENT fallback

# --- Configuration ---
_USER_AGENT_FALLBACK = "MyFinancialReporter/1.0 (avichalai2004@gmail.com) - Fallback" # Your desired default
USER_AGENT = os.environ.get('SEC_USER_AGENT', _USER_AGENT_FALLBACK)

if USER_AGENT == _USER_AGENT_FALLBACK and 'SEC_USER_AGENT' not in os.environ:
    print(f"SEC_DATA_PROCESSOR INFO: Environment variable 'SEC_USER_AGENT' not set. Using fallback: '{USER_AGENT}'")
else:
    print(f"SEC_DATA_PROCESSOR INFO: Using User-Agent: '{USER_AGENT}'")

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
    return TICKER_CIK_MAP.get(ticker_symbol.upper())

def fetch_company_financial_facts(cik_number: str) -> tuple[dict | None, str | None]:
    if not cik_number:
        return None, "CIK number cannot be empty."
    facts_url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik_number}.json"
    try:
        response = requests.get(facts_url, headers=SEC_HEADERS)
        response.raise_for_status()
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

def get_historical_facts_for_metric(
    all_company_facts_json: dict, 
    metric_tag: str, 
    unit_type: str,
    target_year: int = None, 
    target_fiscal_period: str = None
) -> list[dict]:
    """
    Extracts historical values for a given metric tag,
    optionally filtering by target_year and target_fiscal_period.
    Ensures datetime objects are converted to ISO format strings.
    """
    raw_historical_data = [] # Before string conversion for dates
    if not all_company_facts_json or 'us-gaap' not in all_company_facts_json or \
       metric_tag not in all_company_facts_json['us-gaap']:
        return []

    metric_info = all_company_facts_json['us-gaap'][metric_tag]

    # Determine correct unit type
    actual_unit_type = unit_type
    if unit_type not in metric_info['units']:
        available_units = list(metric_info['units'].keys())
        if available_units:
            actual_unit_type = available_units[0]
            print(f"Warning: Unit '{unit_type}' not found for {metric_tag}. Using '{actual_unit_type}'.")
        else:
            return [] # No units, no data

    all_filings_for_unit = metric_info['units'][actual_unit_type]

    for fact in all_filings_for_unit:
        if fact.get('form') in ['10-K', '10-Q'] and 'val' in fact and fact.get('end') and fact.get('fp'):
            try:
                current_fy_str = fact['fy']
                current_fp_str = fact['fp']
                
                # Apply year filter
                if target_year:
                    try:
                        if int(current_fy_str) != target_year:
                            continue
                    except ValueError: # if 'fy' is not a simple year string
                        print(f"Warning: Could not parse fiscal year '{current_fy_str}' for filtering.")
                        continue
                
                # Apply fiscal period filter
                if target_fiscal_period:
                    # For 'FY' target, we are typically looking for the annual report data (10-K)
                    # or the data point that represents the full year.
                    if target_fiscal_period.upper() == "FY":
                        if fact.get('form') != '10-K' and current_fp_str.upper() != 'FY': # Ensure it's an annual figure or explicitly marked FY
                            continue
                    elif current_fp_str.upper() != target_fiscal_period.upper():
                        continue
                
                raw_historical_data.append({
                    'EndDate': datetime.strptime(fact['end'], '%Y-%m-%d'),
                    'Value': float(fact['val']),
                    'Form': fact['form'],
                    'FiscalPeriod': current_fp_str,
                    'FiscalYear': current_fy_str,
                    'Filed': datetime.strptime(fact['filed'], '%Y-%m-%d')
                })
            except (ValueError, TypeError, KeyError) as e:
                print(f"Skipping fact due to data error: {fact}. Error: {e}")
                continue
    
    serializable_data = []
    if raw_historical_data:
        temp_df = pd.DataFrame(raw_historical_data)
        if not temp_df.empty:
            temp_df.sort_values(by=['EndDate', 'Filed'], ascending=[True, True], inplace=True)
            # Consider FiscalPeriod in deduplication if a company files different forms for same EndDate
            # For example, a 10-Q for Q4 and a 10-K for FY might have same EndDate.
            # The filter logic for target_fiscal_period='FY' should help select the 10-K.
            # If no specific period, taking the 'last' filed for an EndDate is a reasonable default.
            deduplicated_data = temp_df.drop_duplicates(subset=['EndDate', 'FiscalPeriod', 'Form'], keep='last').to_dict('records')
            
            for item in deduplicated_data:
                # Convert datetime objects to ISO format strings for JSON serialization
                if 'EndDate' in item and hasattr(item['EndDate'], 'isoformat'):
                    item['EndDate'] = item['EndDate'].isoformat()
                if 'Filed' in item and hasattr(item['Filed'], 'isoformat'):
                    item['Filed'] = item['Filed'].isoformat()
                serializable_data.append(item)
            
            # Sort final list by the original EndDate (now a string, but ISO format sorts chronologically)
            serializable_data.sort(key=lambda x: x['EndDate'])
            
    return serializable_data


def generate_metric_plot_as_bytes(metric_data_list: list[dict], display_name: str, 
                                  company_name_display: str, unit: str) -> bytes | None:
    if not metric_data_list:
        return None

    df_metric = pd.DataFrame(metric_data_list)
    if df_metric.empty or 'EndDate' not in df_metric.columns or 'Value' not in df_metric.columns:
        return None
    
    # Convert EndDate strings back to datetime for plotting
    try:
        df_metric['EndDate'] = pd.to_datetime(df_metric['EndDate'])
        df_metric.set_index('EndDate', inplace=True)
        df_metric.sort_index(inplace=True) # Ensure data is sorted for plotting
    except Exception as e:
        print(f"Error converting EndDate for plotting: {e}")
        return None


    plt.figure(figsize=(10, 5))
    plt.plot(df_metric.index, df_metric['Value'], marker='o', linestyle='-')

    if not df_metric['Value'].empty and pd.api.types.is_numeric_dtype(df_metric['Value']):
        valid_values = df_metric['Value'].dropna()
        if not valid_values.empty:
            max_val = valid_values.abs().max()
            if max_val > 1e9:
                plt.gca().yaxis.set_major_formatter(plt.FuncFormatter(lambda x, loc: f"{x/1e9:.2f}B"))
            elif max_val > 1e6:
                plt.gca().yaxis.set_major_formatter(plt.FuncFormatter(lambda x, loc: f"{x/1e6:.2f}M"))
            elif "EPS" not in display_name and max_val > 0 :
                 plt.gca().yaxis.set_major_formatter(plt.FuncFormatter(lambda x, loc: f"{x/1e3:.2f}K"))

    plt.title(f"Historical {display_name} for {company_name_display} ({unit})")
    plt.xlabel("Period End Date")
    plt.ylabel(display_name)
    plt.grid(True)
    plt.xticks(rotation=45)
    plt.tight_layout()

    img_bytes_io = BytesIO()
    plt.savefig(img_bytes_io, format='PNG', bbox_inches='tight')
    plt.close()
    img_bytes_io.seek(0)
    return img_bytes_io.getvalue()

def get_company_financial_details(ticker_symbol: str, target_year: int = None, target_fiscal_period: str = None) -> tuple[dict | None, str | None]:
    cik = get_cik_from_ticker(ticker_symbol)
    if not cik:
        return None, f"CIK not found for ticker '{ticker_symbol}' in predefined map."

    all_company_facts_json, error_msg = fetch_company_financial_facts(cik)
    if error_msg:
        return None, f"Failed to fetch SEC data for {ticker_symbol} (CIK: {cik}): {error_msg}"
    if not all_company_facts_json:
        return None, f"No data returned from SEC API for {ticker_symbol} (CIK: {cik})."

    company_name = all_company_facts_json.get('entityName', ticker_symbol)
    company_display_name = f"{company_name} ({ticker_symbol})"

    results = {
        "company_name": company_name,
        "company_display_name": company_display_name,
        "ticker": ticker_symbol,
        "cik": cik,
        "metrics": {}
    }

    for display_name_key, metric_details_val in METRICS_TO_EXTRACT.items():
        tag_name = metric_details_val["tag"]
        unit = metric_details_val["unit"]
        
        metric_data_list = get_historical_facts_for_metric(
            all_company_facts_json.get('facts', {}),
            tag_name,
            unit,
            target_year=target_year, # Pass filtering parameters
            target_fiscal_period=target_fiscal_period 
        )
        results["metrics"][display_name_key] = {
            "data": metric_data_list, # This is now potentially filtered and dates are strings
            "unit": unit,
            "tag": tag_name
        }
    return results, None

# --- Main Execution (for testing the functions locally) ---
if __name__ == "__main__":
    print(f"Using User-Agent: {USER_AGENT}")
    if "PLEASE_UPDATE" in USER_AGENT: # Check the module-level USER_AGENT
        print("CRITICAL: Update the USER_AGENT in the script's configuration or environment for reliable SEC API access before proceeding.")
        # exit()

    ticker_input = input("Enter company ticker symbol (e.g., NVDA, AAPL): ").upper()
    year_input_str = input("Enter target fiscal year (e.g., 2022, or leave blank for all): ")
    period_input = input("Enter target fiscal period (e.g., Q1, Q2, FY, or leave blank for all): ").upper()

    target_year_int = None
    if year_input_str:
        try:
            target_year_int = int(year_input_str)
        except ValueError:
            print(f"Invalid year input '{year_input_str}'. Fetching all years.")
    
    target_fp = period_input if period_input else None

    financial_details, error = get_company_financial_details(ticker_input, target_year=target_year_int, target_fiscal_period=target_fp)

    if error:
        print(f"\nError processing {ticker_input}: {error}")
    elif financial_details:
        print(f"\n--- Financial Details for {financial_details['company_display_name']} (Year: {target_year_int or 'All'}, Period: {target_fp or 'All'}) ---")
        for metric_display_name, metric_info in financial_details["metrics"].items():
            print(f"\nMetric: {metric_display_name} ({metric_info['unit']})")
            data_list = metric_info["data"]
            if data_list:
                df_display = pd.DataFrame(data_list)
                if not df_display.empty:
                    cols_to_print = ['EndDate', 'Value', 'Form', 'FiscalPeriod', 'FiscalYear']
                    existing_cols = [col for col in cols_to_print if col in df_display.columns]
                    print(df_display[existing_cols].to_string()) # Print more rows for clarity

                    plot_bytes = generate_metric_plot_as_bytes(
                        data_list, # Pass the list of dicts
                        metric_display_name,
                        financial_details['company_display_name'],
                        metric_info['unit']
                    )
                    if plot_bytes:
                        print(f"Generated plot for {metric_display_name} ({len(plot_bytes)} bytes).")
                        # To display in environments like Jupyter/Colab:
                        # from IPython.display import Image, display
                        # display(Image(data=plot_bytes))
                        # To save locally:
                        # plot_filename = f"{ticker_input.lower()}_{metric_display_name.lower().replace(' ', '_')}.png"
                        # with open(plot_filename, "wb") as f:
                        #     f.write(plot_bytes)
                        # print(f"Plot saved as {plot_filename}")
            else:
                print("No data found for this metric for the specified period.")
    else:
        print(f"No financial details retrieved for {ticker_input}.")