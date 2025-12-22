import mysql.connector
import time

# --- MySQL Database Config ---
DB_CONFIG = {
    "host": "localhost",
    "port": 3308,
    "user": "root",
    "password": "TARAZOU",
    "database": "justice_game"
}


def get_conn():
    """Create and return a new DB connection."""
    return mysql.connector.connect(**DB_CONFIG)


def get_players_from_db():
    """
    Fetch players and their submitted numbers from the DB.
    Returns a dictionary: {name: number}
    """
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT name, number FROM players WHERE number IS NOT NULL")
    rows = cursor.fetchall()
    conn.close()
    return {name: num for name, num in rows}


def get_current_round():
    """Fetch the current round number from game_state table."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT current_round FROM game_state WHERE id=1")
    (r,) = cur.fetchone()
    conn.close()
    return int(r or 1)


def get_players_for_round(round_no: int) -> dict[str, int]:
    """Get players and their chosen numbers for a specific round."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT name, number FROM players
        WHERE number IS NOT NULL AND round = %s
    """, (round_no,))
    rows = cur.fetchall()
    conn.close()
    return {name: num for name, num in rows}


class GameState:
    def __init__(self):
        self.conn = get_conn()
        self.cursor = self.conn.cursor()

    # --- Core Game Logic ---
    def update_scores_based_on_closest(self, round_no: int | None = None):
        """
        Apply 80% rule for the given round.

        Returns a payload for the results page:
        {
            "had_submissions": bool,
            "target": float|None,
            "winner": str|None,
            "players_dict": {name: number}        # what you want to render
        }

        If there are no submissions, DB is NOT modified.
        """
        if round_no is None:
                round_no = get_current_round()

            # 1) Build dict {name:number} for this round (ignore NULL)
        players_numbers = get_players_for_round(round_no)

            # No data -> do nothing
        if not players_numbers:
                return {"had_submissions": False, "target": None, "winner": None, "players_dict": {}}

            # 2) Compute 80% of average
        nums = list(players_numbers.values())
        avg = sum(nums) / len(nums)
        target = 0.8 * avg

            # 3) Winner = closest to target (tie-break: smaller abs diff, then name ASC)
        winner = min(players_numbers.keys(),
                        key=lambda n: (abs(players_numbers[n] - target), n.lower()))

            # 4) Persist scores to SQL: winner +0, others -1
        conn = get_conn()
        cur = conn.cursor()
        for name in players_numbers:
                delta = 0 if name == winner else -1
                # keep points safe if NULL
                cur.execute("""
                    UPDATE players
                    SET points = COALESCE(points, 0) + %s
                    WHERE name = %s
                """, (delta, name))
        conn.commit()
        conn.close()

        return {
                "had_submissions": True,
                "target": target,
                "winner": winner,
                "players_dict": players_numbers
            }
    def summarize_round(round_no: int):
        """
        Read-only summary from DB (no mutations).
        Returns: {"had_submissions": bool, "target": float|None, "winner": str|None, "players_dict": {...}}
        """
        players_numbers = get_players_for_round(round_no)
        if not players_numbers:
            return {"had_submissions": False, "target": None, "winner": None, "players_dict": {}}

        nums = list(players_numbers.values())
        avg = sum(nums) / len(nums)
        target = 0.8 * avg
        winner = min(players_numbers.keys(),
                 key=lambda n: (abs(players_numbers[n] - target), n.lower()))
        return {"had_submissions": True, "target": target, "winner": winner, "players_dict": players_numbers}


    def get_current_results(self, round_no: int | None = None):
        """Get current round results from DB."""
        if round_no is None:
            round_no = get_current_round()
        conn = get_conn()
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT name, number, points
            FROM players
            WHERE number IS NOT NULL AND round = %s
            ORDER BY points DESC, name ASC
        """, (round_no,))
        data = {row['name']: {"number": row['number'], "points": row['points']} for row in cur.fetchall()}
        conn.close()
        return data

    # --- Game State Flags ---
    def set_results_ready(self, value: bool):
        self.cursor.execute("UPDATE game_state SET results_ready = %s WHERE id = 1", (1 if value else 0,))
        self.conn.commit()

    def get_results_ready(self) -> bool:
        self.cursor.execute("SELECT results_ready FROM game_state WHERE id = 1")
        row = self.cursor.fetchone()
        return bool(row[0]) if row else False

    def reset_flags(self):
        """Reset round and results flags in memory (doesn't reset DB)."""
        self.results_ready = False
        self.current_round = 1

    @staticmethod
    def add_results_column_if_not_exists():
        """Ensure results_ready column exists in game_state table."""
        conn = get_conn()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                ALTER TABLE game_state 
                ADD COLUMN IF NOT EXISTS results_ready BOOLEAN DEFAULT FALSE;
            """)
            conn.commit()
            print("✅ Column 'results_ready' ensured in game_state.")
        except mysql.connector.Error as e:
            print(f"⚠️ Error adding column: {e}")
        cursor.close()
        conn.close()

    # --- Round Management ---
    def open_next_round(self, round_duration=30):
        """Mark next round as open with start time + duration."""
        start_time = time.time()
        self.cursor.execute("""
            UPDATE game_state 
            SET next_round_open = 1, round_start_time = %s, round_duration = %s
            WHERE id = 1
        """, (start_time, round_duration))
        self.conn.commit()
        return start_time, round_duration

    def check_next_round_open(self):
        """Check if the next round is open and return its timing."""
        self.cursor.execute("""
            SELECT next_round_open, round_start_time, round_duration 
            FROM game_state WHERE id = 1
        """)
        row = self.cursor.fetchone()
        if row:
            next_open, start_time, duration = row
            return bool(next_open), start_time, duration
        return False, None, None

    # --- Utility ---
    def get_all_players(self):
        self.cursor.execute("SELECT name, number, points AS score FROM players WHERE number IS NOT NULL")
        return self.cursor.fetchall()

    def close(self):
        self.cursor.close()
        self.conn.close()
