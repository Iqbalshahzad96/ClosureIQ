import pytest
from app.ingestion.adapters.generic_bank import GenericBankStatementAdapter
from app.ingestion.adapters.tabular import parse_table, normalize_header

def test_bank_statement_extracts_pre_header_metadata():
    adapter = GenericBankStatementAdapter()
    csv_bytes = (
        "Statement for Account Number: ABC-123\n"
        "Currency: GBP\n"
        "Period: 2026-Jan\n"
        "\n"
        "Date,Description,Amount\n"
        "2026-01-01,Fee,-10.00\n"
    ).encode("utf-8")
    
    options = {}
    rows = list(adapter.parse_file(csv_bytes, "test.csv", options))
    
    # Check that metadata was extracted into options
    assert options.get("bank_account_id") == "ABC-123"
    assert options.get("currency_code") == "GBP"
    assert options.get("fiscal_period") == "2026-jan"
    
    # Check that the transaction row was parsed correctly
    payloads = adapter.map_to_canonical(rows, options)
    assert len(payloads) == 1
    assert payloads[0].data["bank_account_id"] == "ABC-123"
    assert payloads[0].data["currency_code"] == "GBP"


def test_missing_header_raises_enriched_error():
    adapter = GenericBankStatementAdapter()
    csv_bytes = (
        "Report Title\n"
        "Date,Desc,Something Else\n" # Missing amount!
        "2026-01-01,Fee,10\n"
    ).encode("utf-8")
    
    with pytest.raises(ValueError) as excinfo:
        list(adapter.parse_file(csv_bytes, "bad.csv", {}))
        
    err_msg = str(excinfo.value)
    assert "Missing required columns" in err_msg
    assert "['date', 'desc', 'something_else']" in err_msg or "['date', 'desc', 'something else']" in err_msg
