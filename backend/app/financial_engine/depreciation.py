"""
Depreciation Validation Engine

Validates fixed asset depreciation schedules deterministically using the straight-line formula:
    Monthly Depreciation = (Cost - Salvage Value) / Useful Life (months)
and verifies against GL posted depreciation entries.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class DepreciationEngine:
    """Deterministic Fixed Asset Depreciation Validation Engine.

    Parameters
    ----------
    tolerance : float, default 0.01
        Maximum allowed difference between calculated schedule and posted depreciation.
    """

    def __init__(self, tolerance: float = 0.01) -> None:
        self.tolerance = max(0.0, float(tolerance))

    @staticmethod
    def calculate_straight_line_monthly(
        cost: float,
        salvage_value: float = 0.0,
        useful_life_months: int = 36,
    ) -> float:
        """Calculate monthly straight-line depreciation.

        Raises ValueError if useful_life_months <= 0 or cost < salvage_value.
        """
        if useful_life_months <= 0:
            raise ValueError("useful_life_months must be strictly greater than 0.")
        if cost < salvage_value:
            raise ValueError(f"Asset cost ({cost}) cannot be less than salvage value ({salvage_value}).")

        depreciable_base = cost - salvage_value
        return round(depreciable_base / useful_life_months, 2)

    def validate_depreciation_schedule(
        self,
        asset_records: List[Dict[str, Any]],
        period_posted_depreciation: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Validate fixed asset records and posted depreciation entries.

        Parameters
        ----------
        asset_records : list of dict
            Fixed asset records. Keys: 'asset_id' (or 'id'), 'asset_name', 'cost',
            'salvage_value' (default 0.0), 'useful_life_months', 'accumulated_depreciation_prior' (default 0.0).
        period_posted_depreciation : dict
            Mapping of asset_id (or asset account) to posted depreciation amount (number or dict with 'amount').

        Returns
        -------
        dict
            Depreciation evaluation report with calculated schedules and discrepancies.
        """
        schedules: List[Dict[str, Any]] = []
        discrepancies: List[Dict[str, Any]] = []

        total_calculated = 0.0
        total_posted = 0.0

        for asset in asset_records:
            asset_id = str(asset.get("asset_id") or asset.get("id") or "")
            asset_name = str(asset.get("asset_name") or asset.get("name") or asset_id)
            cost = float(asset.get("cost", 0.0))
            salvage_value = float(asset.get("salvage_value", 0.0))
            useful_life = int(asset.get("useful_life_months", 0))
            prior_accum = float(asset.get("accumulated_depreciation_prior", 0.0))

            # Retrieve posted amount
            posted_val = period_posted_depreciation.get(asset_id)
            if posted_val is None and asset_id:
                # Try case-insensitive lookup
                for p_k, p_v in period_posted_depreciation.items():
                    if str(p_k).strip().lower() == asset_id.strip().lower():
                        posted_val = p_v
                        break

            posted_amount = 0.0
            if posted_val is not None:
                if isinstance(posted_val, (int, float)):
                    posted_amount = float(posted_val)
                elif isinstance(posted_val, dict) and "amount" in posted_val:
                    posted_amount = float(posted_val["amount"])

            total_posted += posted_amount

            # 1. Validate inputs
            if useful_life <= 0 or cost < salvage_value:
                discrepancies.append({
                    "asset_id": asset_id,
                    "asset_name": asset_name,
                    "reason": "INVALID_ASSET_PARAMETERS",
                    "calculated_depreciation": 0.0,
                    "posted_depreciation": posted_amount,
                    "variance": posted_amount,
                    "details": f"Invalid asset data: cost={cost}, salvage={salvage_value}, useful_life={useful_life}",
                })
                continue

            # 2. Calculate schedule
            depreciable_base = round(cost - salvage_value, 2)
            monthly_standard = self.calculate_straight_line_monthly(
                cost=cost,
                salvage_value=salvage_value,
                useful_life_months=useful_life,
            )

            remaining_depreciable = max(0.0, round(depreciable_base - prior_accum, 2))
            expected_current_depreciation = min(monthly_standard, remaining_depreciable)
            total_calculated += expected_current_depreciation

            schedule_info = {
                "asset_id": asset_id,
                "asset_name": asset_name,
                "cost": cost,
                "salvage_value": salvage_value,
                "useful_life_months": useful_life,
                "accumulated_depreciation_prior": prior_accum,
                "monthly_standard_depreciation": monthly_standard,
                "remaining_depreciable_base": remaining_depreciable,
                "expected_current_depreciation": expected_current_depreciation,
                "posted_depreciation": posted_amount,
                "is_fully_depreciated": remaining_depreciable == 0.0,
            }
            schedules.append(schedule_info)

            # 3. Discrepancy checks
            variance = round(posted_amount - expected_current_depreciation, 2)

            # Case A: Asset is fully depreciated, but depreciation is still being posted
            if remaining_depreciable == 0.0 and posted_amount > self.tolerance:
                discrepancies.append({
                    "asset_id": asset_id,
                    "asset_name": asset_name,
                    "reason": "FULLY_DEPRECIATED_STILL_POSTING",
                    "calculated_depreciation": 0.0,
                    "posted_depreciation": posted_amount,
                    "variance": variance,
                    "details": (
                        f"Asset '{asset_name}' is fully depreciated (prior accum: ${prior_accum:,.2f}), "
                        f"but ${posted_amount:,.2f} was posted in the GL."
                    ),
                })
            # Case B: Unposted depreciation
            elif expected_current_depreciation > self.tolerance and posted_amount == 0.0:
                discrepancies.append({
                    "asset_id": asset_id,
                    "asset_name": asset_name,
                    "reason": "UNPOSTED_DEPRECIATION",
                    "calculated_depreciation": expected_current_depreciation,
                    "posted_depreciation": 0.0,
                    "variance": variance,
                    "details": (
                        f"Schedule requires ${expected_current_depreciation:,.2f} monthly depreciation, "
                        f"but no entry was posted."
                    ),
                })
            # Case C: Over-posted or under-posted
            elif abs(variance) > self.tolerance:
                reason = "OVER_POSTED" if variance > 0 else "UNDER_POSTED"
                discrepancies.append({
                    "asset_id": asset_id,
                    "asset_name": asset_name,
                    "reason": reason,
                    "calculated_depreciation": expected_current_depreciation,
                    "posted_depreciation": posted_amount,
                    "variance": variance,
                    "details": (
                        f"Posted depreciation (${posted_amount:,.2f}) differs from schedule "
                        f"(${expected_current_depreciation:,.2f}) by ${abs(variance):,.2f}."
                    ),
                })

        return {
            "total_assets_evaluated": len(asset_records),
            "schedules": schedules,
            "discrepancies": discrepancies,
            "total_calculated_depreciation": round(total_calculated, 2),
            "total_posted_depreciation": round(total_posted, 2),
            "net_variance": round(total_posted - total_calculated, 2),
            "status": "VALID" if len(discrepancies) == 0 else "DISCREPANCIES_FOUND",
        }
