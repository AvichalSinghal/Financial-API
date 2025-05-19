from fastapi import FastAPI, HTTPException, Response
# Import your functions from sec_data_processor.py
from sec_data_processor import get_company_financial_details, generate_metric_plot_as_bytes, METRICS_TO_EXTRACT # and any other specific things you need

app = FastAPI()

@app.get("/company/{ticker_symbol}/financials")
async def get_financials(ticker_symbol: str):
    details, error = get_company_financial_details(ticker_symbol)
    if error:
        raise HTTPException(status_code=404, detail=error)
    if not details: # Should be covered by error, but for safety
        raise HTTPException(status_code=404, detail="No details found.")
    return details # FastAPI will convert this dict (with datetime objects) to JSON

@app.get("/company/{ticker_symbol}/plot/{metric_key}")
async def get_plot(ticker_symbol: str, metric_key: str): # metric_key would be "Revenue", "Net Income" etc.
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
        metric_key, # Display name
        company_display_name,
        unit
    )
    if not plot_bytes_val:
        raise HTTPException(status_code=500, detail="Failed to generate plot.")

    return Response(content=plot_bytes_val, media_type="image/png")

# To run (save as main.py and run 'uvicorn main:app --reload' in your terminal):
# Example usage:
# http://localhost:8000/company/AAPL/financials
# http://localhost:8000/company/AAPL/plot/Revenue