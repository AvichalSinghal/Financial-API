# At the top of your main.py
import os
import json # For parsing arguments from Gemini if needed
import requests # To call your own API endpoints if you choose external calls
from fastapi import FastAPI, HTTPException, Body # Body for POST requests
from pydantic import BaseModel # For request body validation

# Your existing imports from sec_data_processor
from sec_data_processor import (
    get_company_financial_details,
    generate_metric_plot_as_bytes,
    METRICS_TO_EXTRACT,
    # Make sure USER_AGENT is set in sec_data_processor or here via os.environ
    # SEC_HEADERS is also defined in sec_data_processor
)

# Import and configure Gemini
import google.generativeai as genai

# --- Initialize FastAPI app (you already have this) ---
app = FastAPI()

# --- Configure Gemini ---
# This should run once when the app starts if possible, or within the endpoint.
# For FastAPI, you can use startup events.
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
if not GEMINI_API_KEY:
    print("CRITICAL WARNING: GEMINI_API_KEY environment variable not found!")
    # In a real app, you might want to prevent startup or handle this gracefully
else:
    genai.configure(api_key=GEMINI_API_KEY)

# Define the Gemini model you want to use for chat/NLU
gemini_model = genai.GenerativeModel(model_name='gemini-1.5-flash') # Or gemini-1.5-pro for more power


# --- Define Pydantic model for the bot's input ---
class BotQuery(BaseModel):
    query: str

# --- Define Function Schemas for your existing API capabilities ---
# These tell Gemini what your API can do.
# Adjust descriptions and parameters to match your actual API endpoints.

get_financial_data_tool = {
    "name": "get_company_financial_data",
    "description": "Fetches historical financial data (like Revenue, Net Income, EPS) for a specific public company. Returns data points with dates and values.",
    "parameters": {
        "type_": "OBJECT",
        "properties": {
            "ticker_symbol": {
                "type_": "STRING",
                "description": "The stock ticker symbol of the company (e.g., AAPL for Apple, MSFT for Microsoft)."
            },
            "metric_name": {
                "type_": "STRING",
                "description": f"The specific financial metric to retrieve. Supported metrics: {', '.join(METRICS_TO_EXTRACT.keys())}."
            }
            # You could add 'period' here if your backend supports specific period queries.
            # For now, we assume get_company_financial_details gets all historical for selected metrics.
        },
        "required": ["ticker_symbol", "metric_name"]
    }
}

generate_financial_plot_tool = {
    "name": "generate_financial_plot",
    "description": "Generates and returns a plot (as an image) for a specific financial metric of a company.",
    "parameters": {
        "type_": "OBJECT",
        "properties": {
            "ticker_symbol": {
                "type_": "STRING",
                "description": "The stock ticker symbol of the company (e.g., AAPL for Apple, MSFT for Microsoft)."
            },
            "metric_key": { # Corresponds to your /plot/{metric_key}
                "type_": "STRING",
                "description": f"The financial metric to plot. Supported metrics: {', '.join(METRICS_TO_EXTRACT.keys())}."
            }
        },
        "required": ["ticker_symbol", "metric_key"]
    }
}

# List of tools Gemini can use
available_tools = [get_financial_data_tool, generate_financial_plot_tool]


# --- Your existing API endpoints from before ---
@app.get("/")
async def home(): # Changed from sync to async as FastAPI prefers async route handlers
    return "Financial Data API with Gemini Bot endpoint is running!"

@app.get("/company/{ticker_symbol}/financials")
async def get_financials_endpoint(ticker_symbol: str): # Changed to async
    # Note: Your get_company_financial_details is likely synchronous.
    # For a truly async endpoint with synchronous backend logic, use_threadpool for FastAPI.
    # For now, direct call is okay for simplicity in a learning context.
    details, error = get_company_financial_details(ticker_symbol)
    if error:
        raise HTTPException(status_code=404, detail=error)
    if not details:
        raise HTTPException(status_code=404, detail="No details found.")
    
    # Convert datetime objects before returning if not handled by FastAPI's encoder
    if details.get("metrics"):
        for metric_name, metric_info in details["metrics"].items():
            if metric_info.get("data"):
                for item in metric_info["data"]:
                    if 'EndDate' in item and hasattr(item['EndDate'], 'isoformat'):
                        item['EndDate'] = item['EndDate'].isoformat()
                    if 'Filed' in item and hasattr(item['Filed'], 'isoformat'):
                        item['Filed'] = item['Filed'].isoformat()
    return details

# ... (your /company/{ticker_symbol}/plot/{metric_key} endpoint - make it async too) ...
from fastapi import Response # For sending image bytes

@app.get("/company/{ticker_symbol}/plot/{metric_key}")
async def get_plot_endpoint(ticker_symbol: str, metric_key: str): # Changed to async
    if metric_key not in METRICS_TO_EXTRACT:
        raise HTTPException(status_code=400, detail=f"Invalid metric key. Available: {list(METRICS_TO_EXTRACT.keys())}")

    details, error = get_company_financial_details(ticker_symbol) # Fetch all data first
    if error:
        raise HTTPException(status_code=404, detail=error)
    if not details or metric_key not in details.get("metrics", {}):
            raise HTTPException(status_code=404, detail=f"Data for metric '{metric_key}' not found for ticker '{ticker_symbol}'.")

    metric_data_list = details["metrics"][metric_key]["data"]
    unit = details["metrics"][metric_key]["unit"]
    company_display_name = details["company_display_name"]

    if not metric_data_list:
        raise HTTPException(status_code=404, detail=f"No data points found for metric '{metric_key}' for ticker '{ticker_symbol}'.")

    plot_bytes_val = generate_metric_plot_as_bytes(
        metric_data_list,
        metric_key,
        company_display_name,
        unit
    )
    if not plot_bytes_val:
        raise HTTPException(status_code=500, detail="Failed to generate plot.")
    
    return Response(content=plot_bytes_val, media_type="image/png")


# --- NEW BOT ENDPOINT ---
@app.post("/ask_financial_bot")
async def ask_bot(bot_query: BotQuery):
    user_query = bot_query.query
    print(f"Received query for bot: {user_query}")

    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="Gemini API key not configured on server.")

    try:
        # Send the query and tool definitions to Gemini
        gemini_response = gemini_model.generate_content(
            user_query,
            tools=available_tools
        )

        # Check if Gemini wants to call a function
        # The exact response structure for function calls needs to be handled
        # based on the Gemini SDK version. Refer to Google's documentation.
        # This is a conceptual example:
        response_parts = gemini_response.candidates[0].content.parts
        function_call_part = None
        for part in response_parts:
            if part.function_call.name: # Check if function_call exists and has a name
                function_call_part = part.function_call
                break
        
        if function_call_part:
            function_name = function_call_part.name
            args = dict(function_call_part.args) # Convert args to a Python dict
            print(f"Gemini wants to call function: {function_name} with args: {args}")

            api_response_content = None
            tool_response_summary = ""

            # Call your internal functions or make HTTP requests to your own API
            if function_name == "get_company_financial_data":
                ticker = args.get("ticker_symbol")
                metric = args.get("metric_name")
                if ticker and metric:
                    # Call your existing logic (more efficient than HTTP to self)
                    details, error = get_company_financial_details(ticker)
                    if error or not details or metric not in details.get("metrics", {}):
                        tool_response_summary = f"Could not retrieve data for {metric} for {ticker}."
                    else:
                        # Extract just the specific metric data Gemini asked for
                        metric_data = details["metrics"][metric]["data"]
                        api_response_content = { # Prepare what Gemini needs
                            "function_name": function_name,
                            "data": metric_data[:5] # Send a snippet, e.g., last 5 data points
                        }
                        tool_response_summary = f"Successfully fetched data for {metric} for {ticker}."
                else:
                    tool_response_summary = "Missing ticker or metric for get_company_financial_data."

            elif function_name == "generate_financial_plot":
                ticker = args.get("ticker_symbol")
                metric = args.get("metric_key")
                if ticker and metric:
                    # For plots, we can't easily send image data back to Gemini in this flow
                    # to generate text *about* the plot. Instead, the bot's client
                    # might need to make two calls: one to get plot parameters,
                    # then another to your /plot endpoint.
                    # Or, this bot endpoint could return a URL to the plot.
                    # For simplicity now, let's say Gemini just confirms it *would* make a plot.
                    plot_url = f"/company/{ticker}/plot/{metric}" # Relative URL the client can use
                    api_response_content = {
                        "function_name": function_name,
                        "status": "Plot can be generated.",
                        "plot_url_suggestion": plot_url # Suggest the client call this
                    }
                    tool_response_summary = f"A plot for {metric} for {ticker} can be generated at {plot_url}."
                else:
                    tool_response_summary = "Missing ticker or metric for generate_financial_plot."
            else:
                tool_response_summary = f"Unknown function '{function_name}' requested by Gemini."

            # If Gemini made a function call, send the result back to Gemini
            # so it can formulate the final natural language response
            if api_response_content:
                # This is the second call to Gemini, providing the tool's output
                final_gemini_response = gemini_model.generate_content(
                    [
                        user_query, # Original user query (or the function call part)
                        response_parts[0], # The part containing the function call request from Gemini
                        { # The result of your function call
                            "function_response": {
                                "name": function_name,
                                "response": api_response_content,
                            }
                        },
                    ]
                )
                return {"answer": final_gemini_response.text, "debug_tool_response": tool_response_summary}
            else: # If the tool call didn't yield results for Gemini to process further
                return {"answer": tool_response_summary, "debug_tool_response": tool_response_summary}

        else:
            # If Gemini didn't request a function call, just return its direct text response
            return {"answer": gemini_response.text}

    except Exception as e:
        print(f"Error in /ask_financial_bot: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

# Your Dockerfile's CMD should still be:
# CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "${PORT:-8000}"]
# Or your entrypoint.sh handling this.