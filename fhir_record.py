"""
fhir_record.py — build the pipeline's RECORD from a real Synthea FHIR Bundle.

Why this shape:
  - Synthea does NOT encode dosing frequency (all inhalers export as
    asNeededBoolean=true), so "prescribed twice daily" cannot be read from the
    record. We treat it as a DOCUMENTED domain constant (asthma ICS controllers
    are standardly BID) and say so out loud.
  - Synthea emits no MedicationDispense; refill history lives in Claim /
    SupplyDelivery. We derive ACTUAL consumption from the interval between
    budesonide Claims — this is the real data signal driving Axis A.

Output: a RECORD dict shaped identically to the hand-built one in
res0216_end2end.py, so nothing downstream changes.

Usage:
    from fhir_record import build_record
    RECORD, meta = build_record("output/fhir/Pearl430_...json")
"""

import json
from datetime import datetime, date

# domain constants (NOT from the record — Synthea can't supply these)
CONTROLLER_PRESCRIBED_FREQ_PER_DAY = 2      # ICS controller, standard BID
DAYS_SUPPLY_PER_INHALER = 30                 # typical dispense window

CONTROLLER_KEYS = ("budesonide", "fluticasone", "formoterol", "beclomethasone")
RESCUE_KEYS = ("albuterol", "salbutamol")


def _parse_dt(s):
    # tolerate the trailing timezone Synthea uses
    try:
        return datetime.fromisoformat(s).date()
    except Exception:
        return datetime.fromisoformat(s[:19]).date()


def _med_text(r):
    return r.get("medicationCodeableConcept", {}).get("text", "").lower()


def _claim_dates_for(res, keyword):
    dates = []
    for r in res:
        if r["resourceType"] == "Claim" and keyword in json.dumps(r).lower():
            bp = r.get("billablePeriod", {}).get("start")
            if bp:
                dates.append(_parse_dt(bp))
    return sorted(dates)


def _median_interval_days(dates):
    if len(dates) < 2:
        return None
    gaps = [(dates[i] - dates[i - 1]).days for i in range(1, len(dates))]
    gaps.sort()
    n = len(gaps)
    return gaps[n // 2] if n % 2 else (gaps[n // 2 - 1] + gaps[n // 2]) / 2


def build_record(bundle_path):
    b = json.load(open(bundle_path))
    res = [e["resource"] for e in b["entry"]]

    record, meta = {}, {}

    # ---- controller ----
    ctrl_reqs = [r for r in res if r["resourceType"] == "MedicationRequest"
                 and any(k in _med_text(r) for k in CONTROLLER_KEYS)]
    if ctrl_reqs:
        keyword = next(k for k in CONTROLLER_KEYS if k in _med_text(ctrl_reqs[0]))
        refill_dates = _claim_dates_for(res, keyword)
        median_gap = _median_interval_days(refill_dates)

        # actual consumption: one inhaler covers DAYS_SUPPLY at prescribed rate;
        # if refills come every `median_gap` days, effective coverage is
        # DAYS_SUPPLY / median_gap of the prescribed regimen.
        actual_freq = None
        if median_gap:
            coverage = DAYS_SUPPLY_PER_INHALER / median_gap          # e.g. 30/365
            actual_freq = round(CONTROLLER_PRESCRIBED_FREQ_PER_DAY * coverage, 2)

        record["mr-controller"] = {
            "kind": "medication",
            "intent": "controller",
            "prescribed_freq_per_day": CONTROLLER_PRESCRIBED_FREQ_PER_DAY,  # domain constant
            "actual_freq_per_day": actual_freq,                            # derived from refills
        }
        meta["controller"] = {
            "med": ctrl_reqs[0].get("medicationCodeableConcept", {}).get("text"),
            "n_refills": len(refill_dates),
            "median_refill_gap_days": median_gap,
            "derived_actual_freq_per_day": actual_freq,
        }

    # ---- rescue ----
    resc_reqs = [r for r in res if r["resourceType"] == "MedicationRequest"
                 and any(k in _med_text(r) for k in RESCUE_KEYS)]
    if resc_reqs:
        keyword = next(k for k in RESCUE_KEYS if k in _med_text(resc_reqs[0]))
        refill_dates = _claim_dates_for(res, keyword)
        last_gap_days = None
        if refill_dates:
            # Synthea dates can run to a simulated "now"; use last refill vs newest date in bundle
            newest = max(refill_dates)
            last_gap_days = (date.today() - newest).days
        record["mr-rescue"] = {
            "kind": "medication",
            "intent": "rescue",
            "dosing": "PRN",
            "last_dispense_days_ago": last_gap_days,
        }
        meta["rescue"] = {
            "med": resc_reqs[0].get("medicationCodeableConcept", {}).get("text"),
            "n_refills": len(refill_dates),
            "last_refill_days_ago": last_gap_days,
        }

    return record, meta


if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else \
        "output/fhir/Pearl430_Ziemann98_e7e2e3bd-7bb1-af8e-8c53-94393768ce6e.json"
    record, meta = build_record(path)
    print("=== derived RECORD ===")
    print(json.dumps(record, indent=2))
    print("\n=== provenance (what drove Axis A) ===")
    print(json.dumps(meta, indent=2, default=str))
    print("\nInterpretation:")
    c = meta.get("controller", {})
    if c.get("median_refill_gap_days"):
        print(f"  controller refilled every ~{c['median_refill_gap_days']} days;")
        print(f"  a BID inhaler (30-day supply) should refill ~monthly.")
        print(f"  -> derived actual use ~{c['derived_actual_freq_per_day']}/day vs "
              f"prescribed {CONTROLLER_PRESCRIBED_FREQ_PER_DAY}/day = large adherence gap.")
