"""
color_analyzer.py — FishSafe Colour Analysis Module
=====================================================
Accepts raw RGB and clear-light values from the TCS34725 sensor,
normalizes them, compares them against calibrated reference profiles,
and returns a screening classification.

Classifications:
  - "Flagged"       : Colour is close to the positive-control reference.
  - "Not Flagged"   : Colour is close to the negative-control reference.
  - "Inconclusive"  : Reading does not confidently match either reference.

IMPORTANT DISCLAIMER
--------------------
This module compares sensor colours against user-collected calibration
references only. It does NOT independently detect formalin or any chemical
compound. All classifications are preliminary and must be confirmed by an
accredited laboratory before any regulatory or public-health action is taken.
"""

import math
from typing import Optional


# ------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------

# If max raw channel value exceeds this, the sensor may be saturated.
SATURATION_THRESHOLD = 65000

# Minimum clear-light value below which the reading is considered too
# dark / invalid (possible LED failure or obstruction).
MIN_CLEAR_VALUE = 10

# Euclidean distance in normalized RGB space (0-1 per channel) below
# which a reading is considered a "close match" to a reference.
# Adjust this value during calibration to suit your reagent and lighting.
MATCH_THRESHOLD = 0.12

# Distance beyond which a reading is considered far from ALL references,
# triggering an Inconclusive result.
INCONCLUSIVE_THRESHOLD = 0.25


# ------------------------------------------------------------------
# Demo-mode example reference profiles
# These are illustrative values only — not chemically validated.
# They are used ONLY when no real calibration profiles exist in the DB.
# ------------------------------------------------------------------

DEMO_PROFILES = [
    {
        "profile_name": "DEMO — Example Positive Control",
        "label": "positive_control",
        # Hypothetical colour after reagent reaction
        "r_norm": 0.65, "g_norm": 0.20, "b_norm": 0.15,
    },
    {
        "profile_name": "DEMO — Example Negative Control",
        "label": "negative_control",
        # Hypothetical colour of unreacted strip
        "r_norm": 0.30, "g_norm": 0.55, "b_norm": 0.15,
    },
]


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _normalize_rgb(red: int, green: int, blue: int, clear: int):
    """
    Normalize raw RGB values to the 0–1 range using the clear-light
    channel as the illumination reference.

    Returns (r_norm, g_norm, b_norm) as floats, or raises ValueError
    if the clear channel is zero (to avoid division by zero).
    """
    if clear <= 0:
        raise ValueError("Clear-light value must be greater than zero for normalization.")
    r_norm = min(red   / clear, 1.0)
    g_norm = min(green / clear, 1.0)
    b_norm = min(blue  / clear, 1.0)
    return r_norm, g_norm, b_norm


def _euclidean_distance(r1, g1, b1, r2, g2, b2) -> float:
    """Compute Euclidean distance between two points in normalized RGB space."""
    return math.sqrt((r1 - r2) ** 2 + (g1 - g2) ** 2 + (b1 - b2) ** 2)


def _validate_reading(red: int, green: int, blue: int, clear: int):
    """
    Check for obviously invalid or saturated sensor readings.
    Returns (is_valid: bool, reason: str).
    """
    if clear < MIN_CLEAR_VALUE:
        return False, (
            "Clear-light value is too low. "
            "Check that the white illumination LEDs are powered and the sensor "
            "is positioned correctly over the test strip."
        )
    if red > SATURATION_THRESHOLD or green > SATURATION_THRESHOLD or blue > SATURATION_THRESHOLD:
        return False, (
            "One or more colour channels appear saturated (value > 65000). "
            "The sensor may be too close to the LED or the ambient light is too bright. "
            "Reposition the sensor and try again."
        )
    if red == 0 and green == 0 and blue == 0:
        return False, (
            "All RGB values are zero. "
            "Sensor may not be connected or responding. "
            "Check I2C wiring and the TCS34725 library initialization."
        )
    return True, "OK"


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

def analyze(
    red: int,
    green: int,
    blue: int,
    clear: int,
    calibration_profiles: Optional[list] = None,
    is_demo: bool = False,
) -> dict:
    """
    Analyze an RGB reading and return a classification dict.

    Parameters
    ----------
    red, green, blue : int
        Raw 16-bit values from the TCS34725 sensor.
    clear : int
        Raw clear-light channel value from the TCS34725 sensor.
    calibration_profiles : list of dicts, optional
        List of saved calibration profiles from the database.
        Each dict must contain: label, red, green, blue, clear (raw floats/ints).
        If None or empty, the module falls back to DEMO_PROFILES.
    is_demo : bool
        If True, the result is flagged as simulated.

    Returns
    -------
    dict with keys:
        classification : str   — "Flagged", "Not Flagged", or "Inconclusive"
        explanation    : str   — Human-readable explanation of the result
        normalized_rgb : tuple — (r_norm, g_norm, b_norm)
        distance_scores: dict  — distance to each reference profile
        is_demo        : bool
        demo_mode_active: bool — True if real calibration data was unavailable
        warning        : str or None
    """

    result = {
        "classification": "Inconclusive",
        "explanation": "",
        "normalized_rgb": None,
        "distance_scores": {},
        "is_demo": is_demo,
        "demo_mode_active": False,
        "warning": None,
    }

    # ---- 1. Validate raw reading ----------------------------------------
    valid, reason = _validate_reading(red, green, blue, clear)
    if not valid:
        result["classification"] = "Inconclusive"
        result["explanation"] = f"Reading invalid: {reason}"
        result["warning"] = reason
        return result

    # ---- 2. Normalize RGB -------------------------------------------------
    try:
        r_norm, g_norm, b_norm = _normalize_rgb(red, green, blue, clear)
    except ValueError as exc:
        result["classification"] = "Inconclusive"
        result["explanation"] = str(exc)
        result["warning"] = str(exc)
        return result

    result["normalized_rgb"] = (round(r_norm, 4), round(g_norm, 4), round(b_norm, 4))

    # ---- 3. Choose reference profiles ------------------------------------
    use_demo_profiles = False

    if calibration_profiles and len(calibration_profiles) >= 2:
        # Build normalized references from raw DB values
        profiles = []
        for cp in calibration_profiles:
            cp_clear = cp.get("clear") or 1
            if cp_clear <= 0:
                cp_clear = 1
            profiles.append({
                "label": cp["label"],
                "profile_name": cp.get("profile_name", cp["label"]),
                "r_norm": min(cp["red"] / cp_clear, 1.0),
                "g_norm": min(cp["green"] / cp_clear, 1.0),
                "b_norm": min(cp["blue"] / cp_clear, 1.0),
            })
    else:
        # Fall back to illustrative demo profiles
        profiles = DEMO_PROFILES
        use_demo_profiles = True
        result["demo_mode_active"] = True
        result["warning"] = (
            "DEMO MODE — Screening classification is not chemically validated. "
            "Collect calibration readings from reagent controls under faculty supervision "
            "before using this software for any real screening purpose."
        )

    # ---- 4. Calculate distances to each reference profile ---------------
    distances = {}
    for profile in profiles:
        dist = _euclidean_distance(
            r_norm, g_norm, b_norm,
            profile["r_norm"], profile["g_norm"], profile["b_norm"]
        )
        distances[profile["label"]] = {
            "distance": round(dist, 5),
            "profile_name": profile["profile_name"],
        }

    result["distance_scores"] = distances

    # ---- 5. Find the closest reference -----------------------------------
    # Sort profiles by distance to the test reading
    sorted_profiles = sorted(profiles, key=lambda p: distances[p["label"]]["distance"])
    closest = sorted_profiles[0]
    closest_dist = distances[closest["label"]]["distance"]

    # ---- 6. Classify -------------------------------------------------------
    if closest_dist <= MATCH_THRESHOLD:
        if closest["label"] == "positive_control":
            result["classification"] = "Flagged"
            result["explanation"] = (
                f"The colour of the test strip (normalised RGB: "
                f"{r_norm:.3f}, {g_norm:.3f}, {b_norm:.3f}) is within the "
                f"colour-distance threshold ({MATCH_THRESHOLD}) of the "
                f"positive-control reference (distance = {closest_dist:.4f}). "
                f"This reading is flagged for further laboratory investigation. "
                f"{'[DEMO — illustrative values only]' if use_demo_profiles else ''}"
            )
        else:
            result["classification"] = "Not Flagged"
            result["explanation"] = (
                f"The colour of the test strip (normalised RGB: "
                f"{r_norm:.3f}, {g_norm:.3f}, {b_norm:.3f}) is within the "
                f"colour-distance threshold ({MATCH_THRESHOLD}) of the "
                f"negative-control reference (distance = {closest_dist:.4f}). "
                f"The sample is not flagged based on colour comparison. "
                f"{'[DEMO — illustrative values only]' if use_demo_profiles else ''}"
            )
    else:
        result["classification"] = "Inconclusive"
        result["explanation"] = (
            f"The test strip colour (normalised RGB: "
            f"{r_norm:.3f}, {g_norm:.3f}, {b_norm:.3f}) does not closely "
            f"match any calibration reference within the threshold of "
            f"{MATCH_THRESHOLD}. Closest reference: '{closest['label']}' "
            f"(distance = {closest_dist:.4f}). "
            f"Please repeat the test or recalibrate the system under faculty supervision. "
            f"{'[DEMO — illustrative values only]' if use_demo_profiles else ''}"
        )

    return result


def generate_demo_reading(scenario: str = "negative") -> dict:
    """
    Generate a plausible simulated RGB reading for demo mode.

    scenario : "positive"  — simulates a colour near the positive control
               "negative"  — simulates a colour near the negative control
               "random"    — simulates a random inconclusive reading

    Returns a dict with keys: red, green, blue, clear (raw integer values).
    These are synthetic values for software demonstration only.
    """
    import random

    if scenario == "positive":
        # Simulate a strip colour shifted toward demo positive-control hue.
        # clear ~= 10000, then RGB channels derived from demo norm values
        clear = random.randint(8000, 12000)
        red   = int(DEMO_PROFILES[0]["r_norm"] * clear * random.uniform(0.92, 1.08))
        green = int(DEMO_PROFILES[0]["g_norm"] * clear * random.uniform(0.92, 1.08))
        blue  = int(DEMO_PROFILES[0]["b_norm"] * clear * random.uniform(0.92, 1.08))
    elif scenario == "negative":
        clear = random.randint(8000, 12000)
        red   = int(DEMO_PROFILES[1]["r_norm"] * clear * random.uniform(0.92, 1.08))
        green = int(DEMO_PROFILES[1]["g_norm"] * clear * random.uniform(0.92, 1.08))
        blue  = int(DEMO_PROFILES[1]["b_norm"] * clear * random.uniform(0.92, 1.08))
    else:
        # Random values that deliberately fall between the two controls
        clear = random.randint(5000, 15000)
        red   = random.randint(1500, 4000)
        green = random.randint(1500, 4000)
        blue  = random.randint(1000, 3500)

    return {
        "red":   max(red,   0),
        "green": max(green, 0),
        "blue":  max(blue,  0),
        "clear": max(clear, MIN_CLEAR_VALUE),
    }
