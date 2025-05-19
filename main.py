# main.py

import os
import json
import requests # For bot logic calling its own data API (alternative to direct function call)
from fastapi import FastAPI, HTTPException, Body, Query, Response
from pydantic import BaseModel
from dotenv import load_dotenv
from io import BytesIO # For sending image from plot endpoint

# Load .env file if you are using one for local development
# For Render, set environment variables in the Render dashboard
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
dotenv_path = os.path.join(BASE_DIR, '.env')
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path)
else:
    print(f"MAIN.PY INFO: .env file not found at {dotenv_path}, relying on preset environment variables.")


# Import your modularized functions
try:
    from sec_data_processor import (
        get_company_financial_details,
        generate_metric_plot_as_bytes,
        METRICS_TO_EXTRACT,
        USER_AGENT as SCRIPT_USER_AGENT # To check if it's set
    )
except ImportError as e:
    print(f"MAIN.PY CRITICAL ERROR: Could not import from sec_data_processor.py: {e}")
    # Define dummy functions if import fails, to allow FastAPI to at least start and report errors
    def get_company_financial_details(*args, **kwargs): return None, "sec_data_processor not loaded"
    def generate_metric_plot_as_bytes(*args, **kwargs): return None
    METRICS_TO_EXTRACT = {}
    SCRIPT_USER_AGENT = "PLEASE_CONFIG_USER_AGENT_IN_SEC_DATA_PROCESSOR"


# Import and configure Gemini
import google.generativeai as genai
from google.generativeai.types import Part
app = FastAPI()

# --- Configure Gemini ---
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
gemini_model = None # Initialize
if not GEMINI_API_KEY:
    print("MAIN.PY CRITICAL WARNING: GEMINI_API_KEY environment variable not found!")
else:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        gemini_model = genai.GenerativeModel(model_name='gemini-1.5-flash') # Or your preferred model
        print("MAIN.PY INFO: Gemini configured successfully.")
    except Exception as e:
        print(f"MAIN.PY CRITICAL WARNING: Failed to configure Gemini: {e}")

# Check SEC_USER_AGENT from imported module
print(f"MAIN.PY INFO: SEC Data Processor User-Agent: '{SCRIPT_USER_AGENT}'")
if "PLEASE_UPDATE" in SCRIPT_USER_AGENT or SCRIPT_USER_AGENT is None :
     print("MAIN.PY CRITICAL WARNING: SEC_USER_AGENT is not properly set in sec_data_processor.py or environment.")


# --- Pydantic model for the bot's input ---
class BotQuery(BaseModel):
    query: str

# --- Define Function Schemas for Gemini ---
get_financial_data_tool = {
    "name": "get_company_financial_data",
    "description": (
        "Fetches historical financial data (like Revenue, Net Income, EPS) for a specific public company. "
        "Can filter by a specific fiscal year and/or fiscal period (Q1, Q2, Q3, Q4 for quarterly, or FY for the full fiscal year's data from a 10-K). "
        "If year and period are not specified, it returns all available historical data for the metric."
    ),
    "parameters": {
        "type_": "OBJECT", # Note: Some Gemini SDK versions might use 'type' instead of 'type_'
        "properties": {
            "ticker_symbol": {
                "type_": "STRING",
                "description": "The stock ticker symbol of the company (e.g., AAPL for Apple, MSFT for Microsoft)."
            },
            "metric_name": {
                "type_": "STRING",
                "description": f"The specific financial metric to retrieve. Supported metrics: {', '.join(METRICS_TO_EXTRACT.keys())}."
            },
            "year": {
                "type_": "NUMBER", # Gemini will pass numbers. Convert to int in your code.
                "description": "Optional. The specific fiscal year to filter for (e.g., 2022, 2023)."
            },
            "fiscal_period": {
                "type_": "STRING",
                "description": "Optional. The specific fiscal period to filter for (e.g., 'Q1', 'Q2', 'Q3', 'Q4', or 'FY' for the full fiscal year)."
            }
        },
        "required": ["ticker_symbol", "metric_name"]
    }
}

generate_financial_plot_tool = { # You'll need to decide how the bot uses this.
    "name": "generate_financial_plot",
    "description": "Indicates that a plot can be generated for a specific financial metric of a company. The bot should then instruct the user on how to view the plot, perhaps by providing the direct API URL for the plot.",
    "parameters": {
        "type_": "OBJECT",
        "properties": {
            "ticker_symbol": {
                "type_": "STRING",
                "description": "The stock ticker symbol of the company."
            },
            "metric_key": {
                "type_": "STRING",
                "description": f"The financial metric to plot. Supported metrics: {', '.join(METRICS_TO_EXTRACT.keys())}."
            }
        },
        "required": ["ticker_symbol", "metric_key"]
    }
}

available_tools = [get_financial_data_tool, generate_financial_plot_tool]

# --- API Endpoints ---

@app.get("/")
async def home():
    return {"message": "Financial Data API with Gemini Bot endpoint is running!"}

@app.get("/company/{ticker_symbol}/financials")
async def get_financials_endpoint(
    ticker_symbol: str, 
    year: int = Query(None, description="Filter by specific fiscal year, e.g., 2022"),
    fiscal_period: str = Query(None, description="Filter by fiscal period, e.g., Q1, Q2, Q3, Q4, FY", min_length=2, max_length=2) # Added length constraints
):
    details, error = get_company_financial_details(ticker_symbol, target_year=year, target_fiscal_period=fiscal_period)
    if error:
        raise HTTPException(status_code=404, detail=error)
    if not details:
        raise HTTPException(status_code=404, detail="No details found.")
    # Datetime conversion to string is now handled in sec_data_processor.py
    return details

@app.get("/company/{ticker_symbol}/plot/{metric_key}")
async def get_plot_endpoint(ticker_symbol: str, metric_key: str):
    if metric_key not in METRICS_TO_EXTRACT:
        raise HTTPException(status_code=400, detail=f"Invalid metric key. Available: {list(METRICS_TO_EXTRACT.keys())}")

    # Fetch potentially filtered data if query parameters for year/period were added to this endpoint
    # For now, it fetches all data for the metric before plotting.
    details, error = get_company_financial_details(ticker_symbol) 
    if error:
        raise HTTPException(status_code=404, detail=error)
    if not details or metric_key not in details.get("metrics", {}):
            raise HTTPException(status_code=404, detail=f"Data for metric '{metric_key}' not found for '{ticker_symbol}'.")

    metric_info = details["metrics"][metric_key]
    metric_data_list = metric_info["data"] # Already list of dicts with string dates
    unit = metric_info["unit"]
    company_display_name = details["company_display_name"]

    if not metric_data_list:
        raise HTTPException(status_code=404, detail=f"No data points for metric '{metric_key}' for '{ticker_symbol}'.")

    plot_bytes_val = generate_metric_plot_as_bytes(
        metric_data_list, metric_key, company_display_name, unit
    )
    if not plot_bytes_val:
        raise HTTPException(status_code=500, detail="Failed to generate plot.")
    
    return Response(content=plot_bytes_val, media_type="image/png")

# --- BOT ENDPOINT ---
@app.post("/ask_financial_bot")
async def ask_bot(bot_query: BotQuery):
    user_query = bot_query.query
    print(f"BOT_ENDPOINT: Received query: {user_query}")

    if not gemini_model: # Check if Gemini model was initialized
        raise HTTPException(status_code=503, detail="Gemini model not available. Check API key and server configuration.")

    try:
        gemini_response = gemini_model.generate_content(
            user_query,
            tools=available_tools # Provide the tool schemas
        )
        
        response_candidate = gemini_response.candidates[0]
        # Check for function calls
        # Note: The exact structure of function_call might vary slightly with SDK updates.
        # Always refer to the latest `google-generativeai` documentation.
        function_call_to_execute = None
        if response_candidate.content and response_candidate.content.parts:
            for part in response_candidate.content.parts:
                if hasattr(part, 'function_call') and part.function_call.name:
                    function_call_to_execute = part.function_call
                    break
        
        if function_call_to_execute:
            function_name = function_call_to_execute.name
            args = dict(function_call_to_execute.args) # Convert args to a Python dict
            print(f"BOT_ENDPOINT: Gemini wants to call function: {function_name} with args: {args}")

            api_response_content = None # This will hold data for Gemini to summarize
            tool_response_summary_for_debug = "" # For your debugging

            if function_name == "get_company_financial_data":
                ticker = args.get("ticker_symbol")
                metric = args.get("metric_name")
                year_arg = args.get("year")
                fiscal_period_arg = args.get("fiscal_period")

                target_year_int = None
                if year_arg is not None:
                    try: target_year_int = int(year_arg)
                    except ValueError: print(f"Warning: Invalid year from Gemini: {year_arg}")

                if ticker and metric:
                    # Call your *internal* enhanced function directly for efficiency
                    details, error = get_company_financial_details(
                        ticker, 
                        target_year=target_year_int, 
                        target_fiscal_period=fiscal_period_arg
                    )
                    if error or not details or metric not in details.get("metrics", {}):
                        tool_response_summary_for_debug = f"Could not retrieve data for {metric} for {ticker} (Year: {year_arg}, Period: {fiscal_period_arg})."
                        api_response_content = {"error": tool_response_summary_for_debug}
                    else:
                        metric_data_from_tool = details["metrics"][metric]["data"]
                        if not metric_data_from_tool:
                             tool_response_summary_for_debug = f"No data found for {metric} for {ticker} for the specified period (Year: {year_arg}, Period: {fiscal_period_arg})."
                             api_response_content = {"status": tool_response_summary_for_debug, "data": []}
                        else:
                            api_response_content = {
                                "status": "success",
                                "data_summary": f"Found {len(metric_data_from_tool)} data point(s) for {metric} for {ticker}.",
                                "data_points": metric_data_from_tool # Already JSON serializable (dates are strings)
                            }
                            tool_response_summary_for_debug = f"Successfully fetched {len(metric_data_from_tool)} data points for {metric} for {ticker}."
                else:
                    tool_response_summary_for_debug = "Missing ticker or metric for get_company_financial_data call."
                    api_response_content = {"error": tool_response_summary_for_debug}
            
            elif function_name == "generate_financial_plot":
                ticker = args.get("ticker_symbol")
                metric = args.get("metric_key")
                plot_url_on_render = f"/company/{ticker}/plot/{metric}" # Relative path
                # For the actual full URL, you'd need to know your Render service's base URL.
                # For simplicity, we'll give Gemini a summary of the action.
                api_response_content = {
                    "status": "Plot generation requested.",
                    "action_taken": f"A plot for {metric} for {ticker} can be viewed. The user should be directed to access the plot, for example, via the URL: {plot_url_on_render}"
                }
                tool_response_summary_for_debug = f"Plot requested for {metric} for {ticker}. Client should use {plot_url_on_render}."

            else:
                tool_response_summary_for_debug = f"Unknown function '{function_name}' requested by Gemini."
                api_response_content = {"error": tool_response_summary_for_debug}

            # Send the function call result back to Gemini to get a final natural language response
            # Ensure api_response_content is well-defined before this step
            if api_response_content is None: # Should not happen if logic above is correct
                api_response_content = {"error": "Internal error processing tool call."}

            second_gemini_response = gemini_model.generate_content(
                [
                    # The original user query for context, or parts that triggered the function call
                    response_candidate.content, # Send back the previous turn from Gemini that included the function call
                    Part.from_function_response( # Use Part.from_function_response
                        name=function_name,
                        response=api_response_content # This must be JSON serializable
                    ),
                ]
            )
            return {"answer": second_gemini_response.text, "debug_tool_summary": tool_response_summary_for_debug}

        else: # Gemini did not request a function call, return its direct text response
            if response_candidate.text:
                return {"answer": response_candidate.text}
            else:
                # Handle cases where Gemini might not return text if it expected a function call but didn't make one
                # or if the response was blocked, etc.
                print(f"BOT_ENDPOINT: Gemini did not call a function and returned no text. Full response: {gemini_response}")
                return {"answer": "I'm sorry, I couldn't determine the next step or find a direct answer. Could you rephrase?"}

    except Exception as e:
        print(f"Error in /ask_financial_bot: {e}")
        import traceback
        traceback.print_exc() # This will print to your Render logs
        raise HTTPException(status_code=500, detail=f"An internal error occurred: {str(e)}")

# To run locally (if you want to test before deploying to Render):
# if __name__ == "__main__":
#     import uvicorn
#     print(f"Attempting to run Uvicorn locally. USER_AGENT for sec_data_processor: {SCRIPT_USER_AGENT}")
#     if not GEMINI_API_KEY:
#         print("CRITICAL: GEMINI_API_KEY not set. Bot endpoint will fail. Set it in your .env file or environment.")
#     uvicorn.run(app, host="0.0.0.0", port=8000)