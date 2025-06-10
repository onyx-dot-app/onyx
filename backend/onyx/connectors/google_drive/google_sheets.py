from typing import Any, Optional
import datetime

from onyx.connectors.google_utils.resources import get_sheets_service
from onyx.connectors.google_utils.shared_constants import MISSING_SCOPES_ERROR_STR
from onyx.connectors.google_utils.shared_constants import ONYX_SCOPE_INSTRUCTIONS
from onyx.utils.logger import setup_logger

logger = setup_logger()


def get_sheet_metadata(
    sheets_service: Any,
    spreadsheet_id: str,
) -> dict[str, Any]:
    """
    Get metadata about all sheets in a spreadsheet.
    
    Args:
        sheets_service: The Google Sheets service instance
        spreadsheet_id: The ID of the spreadsheet
            
    Returns:
        dict: Metadata about the spreadsheet including sheet names and IDs
    """
    try:
        return sheets_service.spreadsheets().get(
            spreadsheetId=spreadsheet_id,
            fields="sheets.properties"
        ).execute()
    except Exception as e:
        if MISSING_SCOPES_ERROR_STR in str(e):
            raise PermissionError(ONYX_SCOPE_INSTRUCTIONS) from e
        raise e


def read_spreadsheet(
    creds: Any,
    primary_admin_email: str,
    spreadsheet_id: str,
    sheet_name: Optional[str] = None,
    cell_range: str = "",
) -> dict[str, Any]:
    """
    Read a Google Sheet and return its content.
    
    Args:
        creds: The credentials to use for authentication
        primary_admin_email: The email of the primary admin
        spreadsheet_id: The ID of the Google Sheet to read
        sheet_name: Name of the specific sheet to read. If None, uses the first sheet.
        cell_range: Optional A1 notation range within the sheet (e.g. "A1:B10").
            If empty, reads the entire sheet.
            
    Returns:
        dict: The spreadsheet content. If cell_range is specified, returns just the values
             for that range. Otherwise returns the full sheet data.
    """
    try:
        sheets_service = get_sheets_service(creds, primary_admin_email)
        
        # Get metadata to find sheet names/IDs if needed
        if not sheet_name:
            metadata = get_sheet_metadata(sheets_service, spreadsheet_id)
            if not metadata.get("sheets"):
                raise ValueError("No sheets found in spreadsheet")
            sheet_name = metadata["sheets"][0]["properties"]["title"]
        
        # Construct the full range with sheet name
        full_range = f"'{sheet_name}'" if not cell_range else f"'{sheet_name}'!{cell_range}"
        
        # Read the values with formatting to preserve hyperlinks and effective values for dates
        result = sheets_service.spreadsheets().get(
            spreadsheetId=spreadsheet_id,
            ranges=[full_range],
            fields="sheets(data(rowData(values(userEnteredValue,effectiveValue,hyperlink))))",
        ).execute()
        
        # Process the response to extract values and hyperlinks
        if not result.get("sheets"):
            return {"values": []}
            
        rows = result["sheets"][0]["data"][0].get("rowData", [])
        processed_values = []
        
        for row in rows:
            processed_row = []
            for cell in row.get("values", []):
                value = None
                # Check for date values in effectiveValue
                if "effectiveValue" in cell and "numberValue" in cell["effectiveValue"]:
                    number_value = cell["effectiveValue"]["numberValue"]
                    # Check if this might be a date (Google Sheets stores dates as serial numbers)
                    if "userEnteredValue" in cell and "numberValue" in cell["userEnteredValue"]:
                        # Convert Excel/Google Sheets date serial number to Python date
                        # Excel/Google Sheets dates are number of days since December 30, 1899
                        try:
                            # Excel/Google Sheets use a different epoch and we need to account for timezone
                            # Using timedelta to avoid timezone issues with fromtimestamp
                            base_date = datetime.datetime(1899, 12, 30)
                            date_value = base_date + datetime.timedelta(days=number_value)
                            value = date_value.isoformat().split('T')[0]  # Format as YYYY-MM-DD
                        except (ValueError, OverflowError):
                            # If conversion fails, fall back to the original number
                            value = number_value
                    else:
                        value = number_value
                # If not a date or conversion failed, use the original userEnteredValue
                elif "userEnteredValue" in cell:
                    for key, val in cell["userEnteredValue"].items():
                        value = val
                        break
                
                if "hyperlink" in cell:
                    value = {"value": value, "hyperlink": cell["hyperlink"]}
                    
                processed_row.append(value)
            processed_values.append(processed_row)
            
        return {"values": processed_values}
        
    except Exception as e:
        if MISSING_SCOPES_ERROR_STR in str(e):
            raise PermissionError(ONYX_SCOPE_INSTRUCTIONS) from e
        raise e
