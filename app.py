"""
app.py — FishSafe Flask Application
=====================================
Entry point for the FishSafe web application.
Run this file with:   python app.py
Then open:            http://127.0.0.1:5000
"""

import uuid
import datetime
from flask import (
    Flask, render_template, request, jsonify, redirect, url_for, abort
)
import database as db
import color_analyzer as ca

# ------------------------------------------------------------------
# App setup
# ------------------------------------------------------------------

app = Flask(__name__)

# Database tables are created in Supabase SQL Editor
db.init_db()


# ------------------------------------------------------------------
# Helper: generate a unique sample ID
# ------------------------------------------------------------------

def make_sample_id():
    """Generate a short, readable sample ID like FS-20251013-A3F2."""
    date_part = datetime.datetime.now().strftime("%Y%m%d")
    uid_part  = uuid.uuid4().hex[:4].upper()
    return f"FS-{date_part}-{uid_part}"


# ==================================================================
# PAGE ROUTES
# ==================================================================

@app.route("/")
def dashboard():
    """Dashboard — summary statistics and recent tests."""
    stats = db.get_stats()
    recent = db.get_recent_readings(limit=10)
    return render_template("dashboard.html", stats=stats, recent=recent)


@app.route("/new-sample", methods=["GET", "POST"])
def new_sample():
    """Fish sample registration form."""
    if request.method == "POST":
        fish_type    = request.form.get("fish_type", "").strip()
        vendor_name  = request.form.get("vendor_name", "").strip()
        location     = request.form.get("location", "").strip()
        collected_at = request.form.get("collected_at", "").strip()
        notes        = request.form.get("notes", "").strip()

        # Basic server-side validation
        errors = []
        if not fish_type:
            errors.append("Fish type is required.")
        if not vendor_name:
            errors.append("Vendor / Source name is required.")
        if not location:
            errors.append("Collection location is required.")
        if not collected_at:
            errors.append("Date and time is required.")

        if errors:
            return render_template("new_sample.html", errors=errors,
                                   form_data=request.form)

        sample_id = make_sample_id()
        try:
            db.insert_sample(sample_id, fish_type, vendor_name,
                             location, collected_at, notes or None)
        except Exception as exc:
            return render_template("new_sample.html",
                                   errors=[f"Database error: {exc}"],
                                   form_data=request.form)

        return redirect(url_for("live_screening", sample_id=sample_id))

    # GET: show blank form with a pre-filled datetime
    now = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M")
    return render_template("new_sample.html", now=now)


@app.route("/screening/<sample_id>")
def live_screening(sample_id):
    """Live screening page for a registered sample."""
    sample = db.get_sample(sample_id)
    if not sample:
        abort(404)
    profiles = db.get_all_calibration_profiles()
    demo_mode = len(profiles) < 2
    return render_template("screening.html", sample=sample,
                           demo_mode=demo_mode, profiles=profiles)


@app.route("/history")
def history():
    """Test history page with search and filter."""
    search        = request.args.get("search", "").strip()
    date_filter   = request.args.get("date", "").strip()
    result_filter = request.args.get("result", "").strip()

    readings = db.get_all_readings(
        search=search or None,
        date_filter=date_filter or None,
        result_filter=result_filter or None,
    )
    return render_template("history.html", readings=readings,
                           search=search, date_filter=date_filter,
                           result_filter=result_filter)


@app.route("/report/<int:reading_id>")
def report(reading_id):
    """Printable screening report for a single reading."""
    reading = db.get_reading_by_id(reading_id)
    if not reading:
        abort(404)
    profiles = db.get_all_calibration_profiles()
    calibrated = len(profiles) >= 2
    return render_template("report.html", reading=reading,
                           calibrated=calibrated,
                           generated_at=datetime.datetime.now().strftime(
                               "%d %B %Y, %I:%M %p"))


@app.route("/calibration")
def calibration():
    """Calibration management page."""
    profiles = db.get_all_calibration_profiles()
    demo_mode = len(profiles) < 2
    return render_template("calibration.html", profiles=profiles,
                           demo_mode=demo_mode)


# ==================================================================
# API ROUTES
# ==================================================================

@app.route("/api/sensor-reading", methods=["POST"])
def api_sensor_reading():
    """
    Receive a sensor reading from the ESP32 (or the demo simulator).

    Expected JSON body:
    {
        "sample_id":  "FS-20251013-A3F2",
        "red":        4200,
        "green":      3100,
        "blue":       2800,
        "clear":      9500,
        "device_id":  "ESP32-001"   (optional)
    }

    Returns JSON with classification and explanation.
    """
    import os
    import hmac
    device_key = os.environ.get("FISHSAFE_DEVICE_KEY")
    if device_key and not hmac.compare_digest(
        request.headers.get("X-Device-Key", ""), device_key
    ):
        return jsonify({"error": "Unauthorized device"}), 401

    if not request.is_json:
        return jsonify({"error": "Content-Type must be application/json"}), 400

    data = request.get_json()

    # --- Validate required fields ---
    required = ["sample_id", "red", "green", "blue", "clear"]
    missing  = [f for f in required if f not in data]
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400

    sample_id = str(data["sample_id"]).strip()
    device_id = str(data.get("device_id", "unknown")).strip()
    is_demo   = bool(data.get("is_demo", False))

    # Validate numeric types
    try:
        red   = int(data["red"])
        green = int(data["green"])
        blue  = int(data["blue"])
        clear = int(data["clear"])
    except (ValueError, TypeError):
        return jsonify({"error": "red, green, blue, clear must be integers"}), 400

    if any(v < 0 for v in [red, green, blue, clear]):
        return jsonify({"error": "Sensor values must not be negative"}), 400

    # --- Check sample exists ---
    sample = db.get_sample(sample_id)
    if not sample:
        return jsonify({"error": f"Sample '{sample_id}' not found. Register it first."}), 404

    # --- Load calibration profiles ---
    profiles = db.get_all_calibration_profiles()

    # --- Run colour analysis ---
    result = ca.analyze(red, green, blue, clear,
                        calibration_profiles=profiles if profiles else None,
                        is_demo=is_demo)

    # --- Save to database ---
    db.insert_reading(
        sample_id=sample_id,
        device_id=device_id,
        red=red, green=green, blue=blue, clear=clear,
        classification=result["classification"],
        explanation=result["explanation"],
        is_demo=is_demo or result["demo_mode_active"],
    )

    return jsonify({
        "status":           "saved",
        "sample_id":        sample_id,
        "classification":   result["classification"],
        "explanation":      result["explanation"],
        "normalized_rgb":   result["normalized_rgb"],
        "distance_scores":  result["distance_scores"],
        "demo_mode_active": result["demo_mode_active"],
        "warning":          result["warning"],
    }), 200


@app.route("/api/demo-reading", methods=["POST"])
def api_demo_reading():
    """
    Generate a simulated sensor reading for demo mode.

    Expected JSON body:
    {
        "sample_id": "FS-20251013-A3F2",
        "scenario":  "positive" | "negative" | "random"
    }
    """
    if not request.is_json:
        return jsonify({"error": "Content-Type must be application/json"}), 400

    data      = request.get_json()
    sample_id = str(data.get("sample_id", "")).strip()
    scenario  = str(data.get("scenario", "negative")).strip()

    if not sample_id:
        return jsonify({"error": "sample_id is required"}), 400

    if db.get_sample(sample_id) is None:
        return jsonify({"error": f"Sample '{sample_id}' not found."}), 404

    # Generate simulated values
    sim = ca.generate_demo_reading(scenario)
    sim["sample_id"] = sample_id
    sim["device_id"] = "DEMO"
    sim["is_demo"]   = True

    # Reuse the main sensor-reading endpoint logic via internal call
    with app.test_request_context(
        "/api/sensor-reading",
        method="POST",
        json=sim,
        content_type="application/json",
    ):
        # Forward to the main handler
        pass

    # Direct analysis (avoids recursive HTTP call)
    profiles = db.get_all_calibration_profiles()
    result = ca.analyze(
        sim["red"], sim["green"], sim["blue"], sim["clear"],
        calibration_profiles=profiles if profiles else None,
        is_demo=True,
    )
    db.insert_reading(
        sample_id=sample_id,
        device_id="DEMO",
        red=sim["red"], green=sim["green"],
        blue=sim["blue"], clear=sim["clear"],
        classification=result["classification"],
        explanation=result["explanation"],
        is_demo=True,
    )

    return jsonify({
        "status":           "saved",
        "sample_id":        sample_id,
        "red":              sim["red"],
        "green":            sim["green"],
        "blue":             sim["blue"],
        "clear":            sim["clear"],
        "classification":   result["classification"],
        "explanation":      result["explanation"],
        "normalized_rgb":   result["normalized_rgb"],
        "demo_mode_active": result["demo_mode_active"],
        "warning":          result["warning"],
    }), 200


@app.route("/api/calibration", methods=["POST"])
def api_save_calibration():
    """Save a calibration reference reading."""
    if not request.is_json:
        return jsonify({"error": "Content-Type must be application/json"}), 400

    data = request.get_json()
    required = ["profile_name", "label", "red", "green", "blue", "clear"]
    missing  = [f for f in required if f not in data]
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400

    label = str(data["label"]).strip()
    if label not in ("positive_control", "negative_control"):
        return jsonify({"error": "label must be 'positive_control' or 'negative_control'"}), 400

    try:
        db.insert_calibration_profile(
            profile_name=str(data["profile_name"]).strip(),
            label=label,
            red=float(data["red"]),
            green=float(data["green"]),
            blue=float(data["blue"]),
            clear=float(data["clear"]),
            notes=str(data.get("notes", "") or ""),
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    return jsonify({"status": "saved"}), 200


@app.route("/api/calibration/<int:profile_id>", methods=["DELETE"])
def api_delete_calibration(profile_id):
    """Delete a calibration profile."""
    db.delete_calibration_profile(profile_id)
    return jsonify({"status": "deleted"}), 200


@app.route("/api/stats")
def api_stats():
    """Return dashboard statistics as JSON."""
    return jsonify(db.get_stats())


@app.route("/api/esp32-status")
def api_esp32_status():
    """
    Simple endpoint the ESP32 can call to confirm server connectivity.
    Returns 200 with a JSON handshake.
    """
    return jsonify({"status": "online", "server": "FishSafe"})


# ==================================================================
# Error handlers
# ==================================================================

@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404


# ==================================================================
# Run
# ==================================================================

if __name__ == "__main__":
    # host="0.0.0.0" makes the server reachable on the local network
    # so the ESP32 can POST readings to your laptop's IP address.
    app.run(host="0.0.0.0", port=5000, debug=True)
