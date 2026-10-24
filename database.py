"""FishSafe PostgreSQL database helpers. Requires DATABASE_URL in Vercel."""
import os
import psycopg2
from psycopg2.extras import RealDictCursor

class DBConnection:
    def __init__(self):
        url = os.environ.get("DATABASE_URL")
        if not url:
            raise RuntimeError("DATABASE_URL is not configured")
        self.conn = psycopg2.connect(url, sslmode="require", connect_timeout=10)
        self.cur = self.conn.cursor(cursor_factory=RealDictCursor)

    def execute(self, query, params=None):
        self.cur.execute(query, params or ())
        return self.cur

    def commit(self):
        self.conn.commit()

    def close(self):
        self.cur.close()
        self.conn.close()


def get_connection():
    return DBConnection()


def init_db():
    # Tables are created using Supabase SQL Editor, not at import time.
    # Avoid a database connection during Vercel cold starts.
    pass


# ------------------------------------------------------------------
# fish_samples helpers
# ------------------------------------------------------------------

def insert_sample(sample_id, fish_type, vendor_name, location, collected_at, notes):
    """Insert a new fish sample registration record."""
    conn = get_connection()
    conn.execute(
        """INSERT INTO fish_samples
               (sample_id, fish_type, vendor_name, location, collected_at, notes)
           VALUES (%s, %s, %s, %s, %s, %s)""",
        (sample_id, fish_type, vendor_name, location, collected_at, notes)
    )
    conn.commit()
    conn.close()


def get_sample(sample_id):
    """Return a single fish sample by sample_id, or None."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM fish_samples WHERE sample_id = %s", (sample_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_samples():
    """Return all fish samples ordered by most recent first."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM fish_samples ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ------------------------------------------------------------------
# sensor_readings helpers
# ------------------------------------------------------------------

def insert_reading(sample_id, device_id, red, green, blue, clear,
                   classification, explanation, is_demo=False):
    """Insert a sensor reading and its screening classification."""
    conn = get_connection()
    conn.execute(
        """INSERT INTO sensor_readings
               (sample_id, device_id, red, green, blue, clear,
                classification, explanation, is_demo)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (sample_id, device_id, red, green, blue, clear,
         classification, explanation, 1 if is_demo else 0)
    )
    conn.commit()
    conn.close()


def get_readings_for_sample(sample_id):
    """Return all readings for a given sample_id."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM sensor_readings WHERE sample_id = %s ORDER BY recorded_at DESC",
        (sample_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_readings(search=None, date_filter=None, result_filter=None):
    """
    Return all readings joined with sample info.
    Supports optional keyword search, date filter and result filter.
    """
    query = """
        SELECT sr.*, fs.fish_type, fs.vendor_name, fs.location
        FROM sensor_readings sr
        LEFT JOIN fish_samples fs ON sr.sample_id = fs.sample_id
        WHERE 1=1
    """
    params = []

    if search:
        query += " AND (sr.sample_id LIKE %s OR fs.fish_type LIKE %s OR fs.vendor_name LIKE %s)"
        like = f"%{search}%"
        params.extend([like, like, like])

    if date_filter:
        query += " AND DATE(sr.recorded_at) = %s"
        params.append(date_filter)

    if result_filter:
        query += " AND sr.classification = %s"
        params.append(result_filter)

    query += " ORDER BY sr.recorded_at DESC"

    conn = get_connection()
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_stats():
    """Return summary counts for the dashboard."""
    conn = get_connection()
    total = conn.execute("SELECT COUNT(*) FROM sensor_readings").fetchone()["count"]
    flagged = conn.execute(
        "SELECT COUNT(*) FROM sensor_readings WHERE classification = 'Flagged'"
    ).fetchone()["count"]
    not_flagged = conn.execute(
        "SELECT COUNT(*) FROM sensor_readings WHERE classification = 'Not Flagged'"
    ).fetchone()["count"]
    inconclusive = conn.execute(
        "SELECT COUNT(*) FROM sensor_readings WHERE classification = 'Inconclusive'"
    ).fetchone()["count"]
    conn.close()
    return {
        "total": total,
        "flagged": flagged,
        "not_flagged": not_flagged,
        "inconclusive": inconclusive
    }


def get_recent_readings(limit=10):
    """Return the most recent readings for the dashboard table."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT sr.sample_id, fs.fish_type, fs.vendor_name,
                  sr.classification, sr.is_demo, sr.recorded_at
           FROM sensor_readings sr
           LEFT JOIN fish_samples fs ON sr.sample_id = fs.sample_id
           ORDER BY sr.recorded_at DESC
           LIMIT %s""",
        (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ------------------------------------------------------------------
# calibration_profiles helpers
# ------------------------------------------------------------------

def insert_calibration_profile(profile_name, label, red, green, blue, clear, notes):
    """Save a new calibration reference profile."""
    conn = get_connection()
    conn.execute(
        """INSERT INTO calibration_profiles
               (profile_name, label, red, green, blue, clear, notes)
           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
        (profile_name, label, red, green, blue, clear, notes)
    )
    conn.commit()
    conn.close()


def get_all_calibration_profiles():
    """Return all saved calibration profiles."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM calibration_profiles ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_calibration_profile(profile_id):
    """Delete a calibration profile by its id."""
    conn = get_connection()
    conn.execute("DELETE FROM calibration_profiles WHERE id = %s", (profile_id,))
    conn.commit()
    conn.close()


def get_reading_by_id(reading_id):
    """Return a single reading joined with sample info for the report page."""
    conn = get_connection()
    row = conn.execute(
        """SELECT sr.*, fs.fish_type, fs.vendor_name, fs.location,
                  fs.collected_at, fs.notes AS sample_notes
           FROM sensor_readings sr
           LEFT JOIN fish_samples fs ON sr.sample_id = fs.sample_id
           WHERE sr.id = %s""",
        (reading_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None
