"""
Accrual Validation Engine

Validates expense and revenue accruals deterministically against prior periods,
historical baselines, and variance policy thresholds (e.g. Policy ACC-002).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class AccrualEngine:
    """Deterministic Accrual Validation Engine.

    Parameters
    ----------
    variance_threshold_pct : float, default 0.10
        Percentage threshold above which variance is considered material (e.g. 0.10 = 10%).
    material_amount_threshold : float, default 50.0
        Absolute dollar amount threshold below which variances are ignored as immaterial.
    """

    def __init__(
        self,
        variance_threshold_pct: float = 0.10,
        material_amount_threshold: float = 50.0,
    ) -> None:
        self.variance_threshold_pct = max(0.0, float(variance_threshold_pct))
        self.material_amount_threshold = max(0.0, float(material_amount_threshold))

    @staticmethod
    def _extract_key(item: Dict[str, Any]) -> str:
        """Derive a canonical key for matching accrual to historical baseline."""
        vendor = str(item.get("vendor") or "").strip().lower()
        account_code = str(item.get("account_code") or "").strip()
        name = str(item.get("name") or "").strip().lower()

        if vendor and account_code:
            return f"{account_code}:{vendor}"
        if vendor:
            return vendor
        if account_code:
            return account_code
        return name

    def validate_accruals(
        self,
        accrual_entries: List[Dict[str, Any]],
        historical_baseline: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Validate period accrual entries against historical baseline.

        Parameters
        ----------
        accrual_entries : list of dict
            Current period accruals. Each dict can contain 'account_code', 'vendor',
            'amount', 'description', 'period', 'id'.
        historical_baseline : dict
            Baseline expectations keyed by account code, vendor, or '{account_code}:{vendor}'.
            Values can be numbers (expected amount) or dicts with 'amount', 'is_recurring', 'vendor_name'.

        Returns
        -------
        dict
            Validation report detailing valid accruals, variance anomalies, and missing accruals.
        """
        valid_accruals: List[Dict[str, Any]] = []
        anomalies: List[Dict[str, Any]] = []
        processed_baseline_keys = set()

        # 1. Evaluate current period accruals
        for entry in accrual_entries:
            key = self._extract_key(entry)
            amount = float(entry.get("amount", 0.0))

            # Find matching baseline
            baseline_val = None
            matched_key = None

            # Try exact key, vendor, or account_code
            for candidate in [key, entry.get("vendor"), entry.get("account_code")]:
                if candidate and candidate in historical_baseline:
                    matched_key = candidate
                    baseline_val = historical_baseline[candidate]
                    break
                # Case-insensitive search on baseline keys
                if candidate:
                    for b_k, b_v in historical_baseline.items():
                        if str(b_k).strip().lower() == str(candidate).strip().lower():
                            matched_key = b_k
                            baseline_val = b_v
                            break
                if matched_key is not None:
                    break

            if matched_key is not None:
                processed_baseline_keys.add(matched_key)

            expected_amount = None
            if baseline_val is not None:
                if isinstance(baseline_val, (int, float)):
                    expected_amount = float(baseline_val)
                elif isinstance(baseline_val, dict) and "amount" in baseline_val:
                    expected_amount = float(baseline_val["amount"])

            # Check 1: Non-positive or zero amount
            if amount <= 0:
                anomalies.append({
                    "type": "INVALID_AMOUNT",
                    "entry": entry,
                    "actual_amount": amount,
                    "expected_amount": expected_amount or 0.0,
                    "variance_amount": round(amount - (expected_amount or 0.0), 2),
                    "variance_pct": 0.0,
                    "reason": f"Accrual amount {amount} is zero or negative.",
                })
                continue

            # Check 2: Variance against baseline
            if expected_amount is not None and expected_amount > 0:
                variance_amount = round(amount - expected_amount, 2)
                variance_pct = round(abs(variance_amount) / expected_amount, 4)

                if (
                    variance_pct > self.variance_threshold_pct
                    and abs(variance_amount) >= self.material_amount_threshold
                ):
                    anomalies.append({
                        "type": "MATERIAL_VARIANCE",
                        "entry": entry,
                        "actual_amount": amount,
                        "expected_amount": expected_amount,
                        "variance_amount": variance_amount,
                        "variance_pct": round(variance_pct * 100, 2),
                        "reason": (
                            f"Variance of {round(variance_pct * 100, 2)}% (${abs(variance_amount):,.2f}) "
                            f"exceeds policy threshold of {round(self.variance_threshold_pct * 100, 1)}%."
                        ),
                    })
                else:
                    valid_accruals.append({
                        "entry": entry,
                        "actual_amount": amount,
                        "expected_amount": expected_amount,
                        "variance_amount": variance_amount,
                        "variance_pct": round(variance_pct * 100, 2),
                    })
            else:
                # No baseline or new vendor accrual
                valid_accruals.append({
                    "entry": entry,
                    "actual_amount": amount,
                    "expected_amount": expected_amount,
                    "variance_amount": 0.0,
                    "variance_pct": 0.0,
                    "note": "New or un-baselined accrual item.",
                })

        # 2. Check for missing recurring accruals from historical baseline
        for b_k, b_v in historical_baseline.items():
            if b_k in processed_baseline_keys:
                continue

            expected_amt = 0.0
            is_recurring = True  # Default baseline expectations are treated as expected recurring items

            if isinstance(b_v, (int, float)):
                expected_amt = float(b_v)
            elif isinstance(b_v, dict):
                expected_amt = float(b_v.get("amount", 0.0))
                is_recurring = bool(b_v.get("is_recurring", True))

            if is_recurring and expected_amt >= self.material_amount_threshold:
                anomalies.append({
                    "type": "MISSING_ACCRUAL",
                    "baseline_key": b_k,
                    "actual_amount": 0.0,
                    "expected_amount": expected_amt,
                    "variance_amount": round(-expected_amt, 2),
                    "variance_pct": 100.0,
                    "reason": f"Expected recurring accrual for '{b_k}' (${expected_amt:,.2f}) was not posted.",
                })

        total_accrued = round(sum(float(e.get("amount", 0.0)) for e in accrual_entries), 2)
        total_baseline = round(
            sum(
                float(v if isinstance(v, (int, float)) else v.get("amount", 0.0))
                for v in historical_baseline.values()
            ),
            2,
        )

        return {
            "total_accruals_checked": len(accrual_entries),
            "valid_accruals_count": len(valid_accruals),
            "anomalies_count": len(anomalies),
            "valid_accruals": valid_accruals,
            "anomalies": anomalies,
            "total_accrued_amount": total_accrued,
            "total_baseline_amount": total_baseline,
            "net_variance": round(total_accrued - total_baseline, 2),
            "status": "CLEAN" if len(anomalies) == 0 else "ANOMALIES_DETECTED",
        }
