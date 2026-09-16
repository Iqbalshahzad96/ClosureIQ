"""Deterministic heuristic detection for financial files."""

import re
from datetime import datetime, date
from app.ingestion.adapters.tabular import physical_rows, date_value, normalize_header

DOCUMENT_TYPES = {
    'GENERAL_LEDGER': {'account', 'debit', 'credit', 'balance', 'gl', 'journal', 'entry', 'ledger'},
    'BANK_STATEMENT': {'bank', 'statement', 'payee', 'deposit', 'withdrawal', 'transaction', 'amount'},
    'TRIAL_BALANCE': {'trial', 'balance', 'beginning', 'ending', 'activity', 'tb', 'net'},
    'AP_INVOICES': {'invoice', 'vendor', 'ap', 'payable', 'due', 'supplier', 'tax'},
    'FIXED_ASSETS': {'asset', 'depreciation', 'useful', 'life', 'salvage', 'accumulated', 'equipment'}
}

CURRENCY_SYMBOLS = {
    '$': 'USD',
    '€': 'EUR',
    '£': 'GBP',
    '¥': 'JPY',
    'KES': 'KES',
    'KSh': 'KES'
}

def detect_context(content: bytes, filename: str) -> dict:
    """Analyze file headers and data to guess document type, period, currency, and bank account."""
    scores = {k: 0 for k in DOCUMENT_TYPES.keys()}
    all_dates = []
    currencies_found = set()
    bank_account_candidates = []
    
    try:
        rows_iter = physical_rows(content, row_limit=150)
        for sheet_name, row_num, cells, epoch in rows_iter:
            str_cells = [str(c).strip() for c in cells if c is not None]
            norm_cells = [normalize_header(c) for c in str_cells]
            
            # Detect document type from headers and sheet name
            norm_sheet = normalize_header(sheet_name)
            for doc_type, keywords in DOCUMENT_TYPES.items():
                if any(kw in norm_sheet for kw in keywords):
                    scores[doc_type] += 2
                
                match_count = sum(1 for c in norm_cells if any(kw in c for kw in keywords))
                scores[doc_type] += match_count
            
            # Detect bank account (often in top rows like "Account: 123456")
            if row_num < 20:
                row_text = " ".join(str_cells).lower()
                if "account" in row_text and any(char.isdigit() for char in row_text):
                    match = re.search(r'(?:account|acct)[\s#:]*([a-z0-9-]+)', row_text)
                    if match:
                        bank_account_candidates.append(match.group(1).upper())

            # Detect currency
            for cell in str_cells:
                for sym, code in CURRENCY_SYMBOLS.items():
                    if sym in cell:
                        currencies_found.add(code)
                if len(cell) == 3 and cell.isupper() and cell.isalpha():
                    if cell in ('USD', 'EUR', 'GBP', 'KES', 'CAD', 'AUD', 'ZAR', 'JPY'):
                        currencies_found.add(cell)

            # Detect dates for period
            for cell in cells:
                d = date_value(cell, epoch)
                if isinstance(d, (datetime, date)):
                    if d.year > 1990 and d.year < 2100:
                        all_dates.append(d)

    except Exception:
        pass # Ignore parsing errors during detection

    best_type = max(scores, key=scores.get) if any(scores.values()) else 'GENERAL_LEDGER'
    confidence = 'HIGH' if scores.get(best_type, 0) > 4 else 'LOW'
    
    period = ""
    if all_dates:
        all_dates.sort()
        # use the maximum date to denote the period
        quarter = (all_dates[-1].month - 1) // 3 + 1
        period = f"{all_dates[-1].year}-Q{quarter}"
        
    currency = list(currencies_found)[0] if currencies_found else ''
    bank_account = bank_account_candidates[0] if bank_account_candidates else ''

    return {
        'documentType': best_type,
        'period': period,
        'currency': currency,
        'bankAccount': bank_account,
        'confidence': confidence
    }
