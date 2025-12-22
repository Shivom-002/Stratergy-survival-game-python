from flask import Flask, render_template, url_for, request, redirect, jsonify, session
import time
from game_logic import GameState
import qrcode
from io import BytesIO
import base64
import os
from flask import make_response

import re
game_state = GameState()
import mysql.connector
import time
import json
import pyttsx3
from flask import Response

app = Flask(__name__)
app.secret_key = "TARAZOU"

# MySQL DB config
DB_CONFIG = {
    "host": "localhost",
    "port": 3308,
    "user": "root",                # change to your MySQL username
    "password": "TARAZOU",  # change to your MySQL password
    "database": "justice_game"
}

COUNTDOWN_DURATION = 40
TIMER_DURATION = 45
RESULTROOM_DURATION = 50
countdown_start = None
global_timer_start = None
sync_timer_start = None
results_ready_flag = False
MOBILE_UA_RE = re.compile(
    r"(Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini)",
    re.I
)

def is_mobile_request(req):
    ua = req.headers.get("User-Agent", "")
    return bool(MOBILE_UA_RE.search(ua))
def get_conn():
    return mysql.connector.connect(**DB_CONFIG)
def ensure_column_exists(table_name, column_name, column_def):
    conn = get_conn()
    c = conn.cursor()
    c.execute(f"SHOW COLUMNS FROM {table_name} LIKE '{column_name}'")
    if not c.fetchone():
        c.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}")
    conn.commit()
    conn.close()

def reset_game_data():
    conn = get_conn()
    c = conn.cursor()
    # Delete all existing players
    c.execute("DELETE FROM players")
    # Reset results_ready flag
    c.execute("UPDATE game_state SET results_ready = 0 WHERE id = 1")
    conn.commit()
    conn.close()

def init_db():
    conn = mysql.connector.connect(
        host="localhost",
        port=3308,
        user="root",
        password="TARAZOU"
    )
    c = conn.cursor()
    c.execute("CREATE DATABASE IF NOT EXISTS justice_game")
    c.execute("USE justice_game")

    c.execute("""
        CREATE TABLE IF NOT EXISTS players (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(100) NOT NULL UNIQUE,
            number INT,
            points INT DEFAULT 0,
            round INT DEFAULT 0,
            eliminated TINYINT DEFAULT 0
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS game_state (
            id INT PRIMARY KEY,
            results_ready TINYINT DEFAULT 0,
            next_round_open TINYINT DEFAULT 0,
            current_round INT DEFAULT 0
        )
    """)

    # ensure round_start_time exists
    c.execute("SHOW COLUMNS FROM game_state LIKE 'round_start_time'")
    if not c.fetchone():
        c.execute("ALTER TABLE game_state ADD COLUMN round_start_time DOUBLE DEFAULT 0")

    c.execute("""
        INSERT INTO game_state (id, results_ready, next_round_open, current_round)
        VALUES (1, 0, 0, 1)
        ON DUPLICATE KEY UPDATE id = id
    """)
    c.execute("SHOW COLUMNS FROM game_state LIKE 'result_timer_start'")
    if not c.fetchone():
        c.execute("ALTER TABLE game_state ADD COLUMN result_timer_start DOUBLE DEFAULT 0")
    conn.commit()
    conn.close()

# Call order
init_db()
# (remove ensure_eliminated_column / ensure_player_columns or leave them commented)


def ensure_eliminated_column():
    conn = get_conn()
    c = conn.cursor()
    # Check if column exists
    c.execute("SHOW COLUMNS FROM players LIKE 'eliminated'")
    if not c.fetchone():
        # Column does not exist, so add it
        c.execute("ALTER TABLE players ADD COLUMN eliminated TINYINT DEFAULT 0")
    conn.commit()
    conn.close()
def reset_game_db():
    conn = get_conn()
    c = conn.cursor()

    # Clear all players (or you can TRUNCATE if you prefer hard reset)
    c.execute("DELETE FROM players")

    # Reset game_state table
    c.execute("""
        UPDATE game_state
        SET current_round = 0,
            results_ready = 0,
            result_timer_start = 0,
            next_round_open = 0
        WHERE id = 1
    """)

    conn.commit()
    conn.close()

# Call this at startup
ensure_eliminated_column()
def ensure_player_columns():
    conn = get_conn()
    c = conn.cursor()

    # Add 'round' column if missing
    c.execute("SHOW COLUMNS FROM players LIKE 'round'")
    if not c.fetchone():
        c.execute("ALTER TABLE players ADD COLUMN round INT DEFAULT 0")

    # Add 'eliminated' column if missing
    c.execute("SHOW COLUMNS FROM players LIKE 'eliminated'")
    if not c.fetchone():
        c.execute("ALTER TABLE players ADD COLUMN eliminated TINYINT DEFAULT 0")

    conn.commit()
    conn.close()

# Call this at app start
ensure_player_columns()


def is_accessed_via_ip(request):
    host = request.host.split(':')[0]
    ip_pattern = re.compile(r'^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$')
    return bool(ip_pattern.match(host)) or host == '10.218.97.94'

init_db()
@app.route('/round')
def rounds_page():
   

    # Device routing
    if is_mobile_request(request):
        return redirect(url_for('inputnumber'))   # phone/tablet → input page
    else:
        return render_template('round.html')      # laptop/projector → lobby

@app.route('/')
def home():
    session['round'] = 0
    session['results_ready'] = False
    qr_data = "http://172.31.45.94:5000/names"
    qr_img = qrcode.make(qr_data)
    qr_path = os.path.join("static", "qr_code.png")
    qr_img.save(qr_path)
    return render_template("laptopinterface.html", qr_code=url_for('static', filename='qr_code.png'))
def get_player_count():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM players WHERE eliminated = 0")
    n = c.fetchone()[0]
    conn.close()
    return n

@app.route('/names', methods=['GET','POST'])
def names():
    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()
        if not name: return "Empty name", 400
        cur_round = get_current_round()
        conn = get_conn(); c = conn.cursor()
        c.execute("""
            INSERT INTO players (name, round, eliminated, points, number)
            VALUES (%s,%s,0,0,NULL)
            ON DUPLICATE KEY UPDATE round=VALUES(round), eliminated=0
        """, (name, cur_round))
        conn.commit(); conn.close()
        return redirect(url_for('waiting_room', name=name))
    # GET → show the form
    return render_template('names.html')

import pyttsx3

_tts_engine = None
import threading
_tts_lock = threading.Lock()

def _ensure_tts():
    global _tts_engine
    if _tts_engine is None:
        with _tts_lock:
            if _tts_engine is None:
                _tts_engine = pyttsx3.init()
                # optional: tweak voice / rate:
                # _tts_engine.setProperty('rate', 175)

def speak_lines(lines):
    _ensure_tts()
    def _run():
        with _tts_lock:
            for line in lines:
                _tts_engine.say(line)
            _tts_engine.runAndWait()
    threading.Thread(target=_run, daemon=True).start()
@app.route('/get_players')
def get_players():
    cur_round = get_current_round()
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT name FROM players
        WHERE eliminated = 0 AND (round = %s OR round = 0)
        ORDER BY id ASC
    """, (cur_round,))
    names = [r[0] for r in c.fetchall()]
    conn.close()

    resp = make_response(jsonify({"players": names}))
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return resp

@app.route('/play_commentary', methods=['POST'])
def play_commentary():
    # fetch current players
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT name FROM players WHERE eliminated = 0 ORDER BY id ASC")
    names = [r[0] for r in c.fetchall()]
    conn.close()

    if not names:
        lines = [
            "No players detected yet. Scan the code to join the Justice Game."
        ]
        speak_lines(lines)
        return jsonify({"ok": True, "lines": lines})

    # craft lines
    round_num = session.get('round', 1)
    count_line = f"Players joined: {len(names)}."
    roll_call = ", ".join(names) if len(names) <= 12 else ", ".join(names[:12]) + "…"
    vibe = "Welcome to the Justice Game. Brace yourselves."
    lines = [
        vibe,
        count_line,
        f"Joining today: {roll_call}."
    ]

    speak_lines(lines)
    return jsonify({"ok": True, "lines": lines})

@app.route('/waiting')
def waiting_room():
    global countdown_start
    if is_accessed_via_ip(request):
        if countdown_start is None:
            countdown_start = time.time()

    player_name = request.args.get('name', 'Player')
    session['player_name'] = player_name

    # --- GET THE ROUND AND PASS IT TO THE TEMPLATE ---
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT current_round FROM game_state WHERE id = 1")
    row = c.fetchone()
    current_round = int(row[0]) if row and row[0] else 1
    # -----------------------------------------------

    
    # ❌ REMOVE this line if it still exists:
    # c.execute("UPDATE game_state SET result_timer_start = 0 WHERE id = 1")

    conn.commit()
    conn.close()

    return render_template('waiting.html',
                           player_name=player_name,
                           round=current_round)   # <-- pass round


@app.route('/start_countdown')
def start_countdown():
    global countdown_start
    countdown_start = time.time()
    return "Countdown started"

@app.route('/get_round')
def get_round():
    return jsonify({"round": 1})

@app.route('/get_timer')
def get_timer():
    if countdown_start is None:
        return jsonify({"time_left": None})
    elapsed = time.time() - countdown_start
    time_left = max(0, COUNTDOWN_DURATION - int(elapsed))
    return jsonify({"time_left": time_left})



@app.route('/inputnumber')
def inputnumber():
    conn = get_conn(); c = conn.cursor()
    # Atomically (re)open if closed/missing/expired; otherwise no-op
    c.execute(f"""
        UPDATE game_state
        SET
          next_round_open    = 1,
          results_ready      = 0,
          result_timer_start = 0,
          round_start_time   = IF(
            next_round_open = 0 OR round_start_time <= 0
            OR (UNIX_TIMESTAMP() - round_start_time) >= {TIMER_DURATION},
            UNIX_TIMESTAMP(),
            round_start_time
          )
        WHERE id = 1
    """)
    conn.commit()
    c.execute("SELECT current_round FROM game_state WHERE id=1")
    row = c.fetchone(); conn.close()

    player_name = session.get('player_name') or request.args.get('name','Player')
    return render_template('inputnumber.html',
                           player_name=player_name,
                           round=int(row[0]) if row and row[0] else 1)

@app.route('/resultroom')
def resultroom():
    player_name = request.args.get('name', 'Player')

    conn = get_conn()
    c = conn.cursor()

    # Close inputs
   

    # Start/refresh the shared results timer only when needed
    # - start if timer not started (0)
    # - refresh if someone left it in a 'ready' state
    # - refresh if old timer long expired (stale page reloads)
    c.execute(f"""
        UPDATE game_state
           SET result_timer_start =
                 CASE
                   WHEN result_timer_start = 0
                     OR results_ready = 1
                     OR (UNIX_TIMESTAMP() - result_timer_start) >= {TIMER_DURATION}
                   THEN UNIX_TIMESTAMP()
                   ELSE result_timer_start
                 END,
               results_ready =
                 CASE
                   WHEN result_timer_start = 0
                     OR results_ready = 1
                     OR (UNIX_TIMESTAMP() - result_timer_start) >= {TIMER_DURATION}
                   THEN 0
                   ELSE results_ready
                 END
         WHERE id = 1
    """)
    conn.commit()

    # Current round
    c.execute("SELECT current_round FROM game_state WHERE id = 1")
    row = c.fetchone()
    current_round = int(row[0]) if row and row[0] else 1
    conn.close()

    # Optional provisional table
    try:
        players = fetch_results_from_db()
    except Exception:
        players = []

    return render_template(
        'resultroom.html',
        player_name=player_name,
        round=current_round,
        TIMER_DURATION=TIMER_DURATION,
        players=players
    )

@app.route('/get_sync_timer')
def get_sync_timer():
    conn = get_conn()
    c = conn.cursor()

    c.execute("SELECT result_timer_start FROM game_state WHERE id=1")
    row = c.fetchone()
    conn.close()

    if not row or not row[0]:
        return jsonify({"remaining": TIMER_DURATION, "started": False})

    start_ts = int(row[0])   # already stored as UNIX_TIMESTAMP in your update query
    now_ts = int(time.time())
    elapsed = now_ts - start_ts
    remaining = max(TIMER_DURATION - elapsed, 0)

    return jsonify({"remaining": remaining, "started": True})

@app.route("/start_global_timer", methods=["POST"])
def start_global_timer():
    global global_timer_start
    global_timer_start = time.time()
    return jsonify({"status": "started"})

@app.route("/get_global_timer")
def get_global_timer():
    # Read the gate + the authoritative start time for the *current* round
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT next_round_open, round_start_time FROM game_state WHERE id=1")
    row = c.fetchone()
    conn.close()

    if not row:
        return jsonify({"started": False, "remaining": TIMER_DURATION})

    open_flag, start = row
    if not open_flag or not start or float(start) <= 0:
        # Host hasn't opened inputs or timer not stamped yet
        return jsonify({"started": False, "remaining": TIMER_DURATION})

    elapsed = int(time.time() - float(start))
    remaining = max(TIMER_DURATION - elapsed, 0)
    return jsonify({"started": True, "remaining": remaining})

from flask import redirect, url_for

@app.route('/submit_player_number', methods=['POST'])
def submit_player_number():
    player_name = request.form.get("player_name")
    player_number = request.form.get("player_number")

    if not player_name or not player_number:
        return "Missing player name or number", 400

    try:
        player_number = int(player_number)
        if not (1 <= player_number <= 100):
            return "Number must be between 1 and 100", 400
    except ValueError:
        return "Invalid number", 400

    current_round = get_current_round()  # <-- use DB, not session

    conn = get_conn()
    # ✅ buffered=True ensures all results are consumed
    c = conn.cursor(buffered=True)

    # --- Check if player is eliminated ---
    c.execute("SELECT eliminated FROM players WHERE name=%s", (player_name,))
    row = c.fetchone()
    if row and row[0] == 1:
        conn.close()
        return "You are eliminated and cannot play this round.", 403

    c.execute("""
    INSERT INTO players (name, number, round, eliminated)
    VALUES (%s, %s, %s, 0)
    ON DUPLICATE KEY UPDATE
        number = VALUES(number),
        round  = VALUES(round)
""", (player_name, player_number, current_round))

    conn.commit()
    conn.close()

    # ✅ Redirect to result room once number submitted
    return redirect(url_for('resultroom', name=player_name))


@app.route('/get_results')
def get_results():
    ready = get_results_ready()
    if not ready:
        return jsonify({"ready": False, "players": []})

    rows = fetch_results_from_db()  # returns dicts: name, number, score, status
    players = [{
        "name":   r.get("name"),
        "number": r.get("number"),
        "points": r.get("score"),   # normalize to 'points' for the front-end
        "status": r.get("status")
    } for r in rows]

    return jsonify({"ready": True, "players": players})

@app.before_request
def ensure_round_in_session():
    if 'round' not in session:
        session['round'] = 1


@app.route('/results', methods=['GET'])
def results():
    # --- read state ---
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT current_round, result_timer_start, results_ready FROM game_state WHERE id = 1")
    row = c.fetchone()
    conn.close()

    current_round = int(row[0]) if row and row[0] else 1
    start_s = float(row[1]) if row and row[1] else 0.0
    ready = bool(row[2]) if row else False

    # --- compute if needed (serialize with named lock) ---
    if not ready:
        conn = get_conn()
        c = conn.cursor()
        got = 0
        try:
            # Try to acquire the lock for up to 3s
            c.execute("SELECT GET_LOCK('justice_results_lock', 3)")
            got = c.fetchone()[0] or 0  # 1=got, 0=timeout, NULL=error treated as 0

            if got == 1:
                # Double-check inside the lock (another request may have finished meanwhile)
                c.execute("SELECT results_ready FROM game_state WHERE id = 1")
                ready_now = bool(c.fetchone()[0])
                if not ready_now:
                    gs = GameState()
                    try:
                        # Only compute if game_logic still says not ready
                        if not gs.get_results_ready():
                            res = gs.update_scores_based_on_closest(current_round)
                            # Mark ready regardless (so the page renders results / no participants)
                            gs.set_results_ready(True)
                            ready = True
                        else:
                            ready = True
                    finally:
                        gs.close()
                else:
                    ready = True
            # release if we acquired
            if got == 1:
                c.execute("DO RELEASE_LOCK('justice_results_lock')")
            conn.commit()
        except Exception:
            try:
                if got == 1:
                    c.execute("DO RELEASE_LOCK('justice_results_lock')")
                conn.rollback()
            finally:
                pass
        finally:
            conn.close()

    # --- build data for rendering ---
    target = None
    winners = []
    losers = []
    players = {}

    if ready:
        gs = GameState()
        try:
            players = gs.get_current_results(current_round)  # dict: name -> {"number","points"}
        finally:
            gs.close()

        numbers = [pdata["number"] for pdata in players.values() if pdata["number"] is not None]
        if numbers:
            avg = sum(numbers) / len(numbers)
            target = 0.8 * avg

            def diff(name):
                return (abs(players[name]["number"] - target), name.lower())

            win = min((n for n in players.keys() if players[n]["number"] is not None), key=diff, default=None)
            if win:
                winners = [win]
                losers = sorted([n for n in players.keys() if n != win])

    no_participants = ready and len(players) == 0
    waiting = not ready

    role = "mobile" if is_mobile_request(request) else "laptop"

    return render_template(
        "results.html",
        waiting=waiting,
        no_participants=no_participants,
        target=target,
        players=players,
        winners=winners,
        losers=losers,
        round=current_round,
        role=role
    )


def set_results_ready(value: bool):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE game_state SET results_ready = %s WHERE id = 1", (1 if value else 0,))
    conn.commit()
    conn.close()

def get_results_ready() -> bool:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT results_ready FROM game_state WHERE id = 1")
    row = c.fetchone()
    conn.close()
    return bool(row[0]) if row else False
@app.route('/get_results_ready')
def get_results_ready_route():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT results_ready FROM game_state WHERE id = 1")
    flag = c.fetchone()[0]
    conn.close()
    return jsonify({"results_ready": bool(flag)})


@app.route('/debug_results_flag')
def debug_results_flag():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT results_ready FROM game_state WHERE id = 1")
    flag = c.fetchone()
    conn.close()
    if flag is None:
        return "No game_state record found"
    return f"Results Ready Flag is: {flag[0]}"
@app.route('/results_data')
def results_data():
    conn = get_conn()
    c = conn.cursor(dictionary=True)
    c.execute("SELECT name, number, points FROM players ORDER BY points DESC")
    players = c.fetchall()
    conn.close()
    return jsonify(players)
@app.route('/check_results_ready')
def check_results_ready():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT results_ready FROM game_state WHERE id = 1")
    flag = c.fetchone()[0]
    conn.close()
    return jsonify({"results_ready": bool(flag)})
@app.route('/results_ready_status')
def results_ready_status():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT results_ready FROM game_state WHERE id = 1")
    row = c.fetchone()
    conn.close()
    return jsonify({"ready": bool(row[0]) if row else False})
def start_new_round():
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE game_state SET results_ready = 0 WHERE id = 1")
    c.execute("UPDATE game_state SET current_round = current_round + 1 WHERE id = 1")
    conn.commit()
    conn.close()

def fetch_results_from_db():
    cur_round = get_current_round()
    conn = get_conn()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT name, number, points AS score,
               CASE 
                 WHEN points = (SELECT MAX(points) FROM players WHERE round=%s) THEN 'Winner'
                 ELSE 'Lost'
               END AS status
        FROM players
        WHERE number IS NOT NULL AND round = %s
        ORDER BY points DESC
    """, (cur_round, cur_round))
    players = cursor.fetchall()
    conn.close()
    return players

@app.route('/calculate_results')#calculator endpoint
def calculate_results():
    game_state = GameState()
    if not game_state.get_results_ready():
        game_state.update_scores_based_on_closest()
        game_state.set_results_ready(True)
    game_state.close()
    return jsonify({"results_ready": True})
import subprocess

@app.route('/launch_results')
def launch_results():
    # Launch results.py using Python subprocess
    subprocess.Popen(["python", "results.py"])
    return "Results launched", 200
def reset_game():
    """Clear all previous scores and reset flags in MariaDB."""
    conn = mysql.connector.connect(
        host="localhost",  # or your server IP
        user="root",
        password="TARAZOU",
        port = 3308,  # change to your MySQL 
        database="justice_game"  # change to your database name
    )
    cursor = conn.cursor()

    # Clear all rows
    cursor.execute("TRUNCATE TABLE scores;")  # TRUNCATE resets auto-increment automatically

    conn.commit()
    cursor.close()
    conn.close()
@app.route('/start_game')
def start_game():
    conn = get_conn()
    c = conn.cursor()

    # Clear players
    c.execute("TRUNCATE TABLE players")

    # Reset state
    c.execute("""
        UPDATE game_state 
        SET results_ready = 0, 
            next_round_open = 0, 
            current_round = 1,
            result_timer_start = 0,
            round_start_time = 0
        WHERE id = 1
    """)

    conn.commit()
    conn.close()

    # Reset session
    session.clear()
    session['round'] = 1
    session['results_ready'] = False

    return redirect(url_for('home'))

GAME_STATE = {
    "input_open": False,
    "video_done": False
}

@app.route("/video_done", methods=["POST"])
def video_done():
    GAME_STATE["video_done"] = True
    return "", 204
@app.route("/check_video_done")
def check_video_done():
    return jsonify({"video_done": GAME_STATE["video_done"]})
# This flag controls mobile input availability
MOBILE_INPUT_OPEN = False



@app.route('/check_input')
def check_input():
    return jsonify({"input_open": MOBILE_INPUT_OPEN})
@app.route('/open_input_for_mobiles', methods=['POST'])
def open_input_for_mobiles():
    """
    Opens the input window for the *current* round and restarts the global input timer.
    Use this for Round 1 (and whenever you want to reopen inputs for the current round).
    """
    conn = get_conn()
    c = conn.cursor()
    # Flip open flag, clear results flags, and set a fresh round_start_time
    c.execute("""
        UPDATE game_state
           SET next_round_open = 1,
               results_ready   = 0,
               result_timer_start = 0,
               round_start_time   = UNIX_TIMESTAMP()
         WHERE id = 1
    """)
    conn.commit()
    conn.close()

    # 🔁 Restart the global, round-aware input timer
    start_input_timer_for_current_round()

    # Optional: return a tiny payload for debugging
    return jsonify({"ok": True}), 200


@app.route('/check_next_round_open')
def check_next_round_open():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT next_round_open FROM game_state WHERE id=1")
    row = c.fetchone()
    conn.close()
    return jsonify({"next_round_open": bool(row[0])})

# polling for next round

#cooking lines

import pyttsx3, threading



# local TTS engine
tts = pyttsx3.init()
tts.setProperty("rate", 175)

def speak(text):
    def _run():
        tts.say(text)
        tts.runAndWait()
    threading.Thread(target=_run, daemon=True).start()


def get_current_round():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT current_round FROM game_state WHERE id=1")
    (cur_round,) = c.fetchone()
    conn.close()
    return int(cur_round or 1)
@app.route("/api/result_state")
def api_result_state():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT current_round, result_timer_start, results_ready FROM game_state WHERE id = 1")
    row = c.fetchone()
    conn.close()

    current_round = int(row[0]) if row and row[0] else 1
    start_s = float(row[1]) if row and row[1] else 0.0
    results_ready = bool(row[2]) if row else False

    server_now_ms = int(time.time() * 1000)

    # IMPORTANT: this endpoint tracks the RESULT ROOM countdown,
    # so gate computation by RESULTROOM_DURATION (not TIMER_DURATION).
    if start_s > 0 and not results_ready and (time.time() - start_s) >= RESULTROOM_DURATION:
        gs = GameState()
        try:
            if not gs.get_results_ready():
                r = gs.update_scores_based_on_closest()
                if r.get("had_submissions"):
                    gs.set_results_ready(True)
                    results_ready = True
        finally:
            gs.close()

    return jsonify({
        "round": current_round,
        "result_timer_start_s": start_s,
        "duration_s": RESULTROOM_DURATION,  # <-- use results duration here
        "server_now_ms": server_now_ms,
        "results_ready": results_ready
    })

#next round lines

@app.route("/notify_resultroom_entered", methods=["POST"])
def notify_resultroom_entered():
    conn = get_conn()
    cur = conn.cursor()
    # Start the timer ONLY if it's not already running
    cur.execute("""
        UPDATE game_state
        SET resultroom_entered = 1,
            result_timer_start = CASE
                WHEN result_timer_start = 0 THEN UNIX_TIMESTAMP()
                ELSE result_timer_start
            END,
            results_ready = CASE
                WHEN result_timer_start = 0 THEN 0
                ELSE results_ready
            END
        WHERE id = 1
    """)
    conn.commit()
    conn.close()
    return ("", 204)

@app.route("/next_round", methods=["POST"])
def next_round():
    conn = get_conn()
    cur = conn.cursor()

    # ✅ Optional check: only proceed if results are ready
    cur.execute("SELECT results_ready FROM game_state WHERE id=1")
    (ready,) = cur.fetchone()
    if not ready:
        conn.close()
        return "Results not ready yet", 409

    # ✅ Eliminate players at -10 points
    cur.execute("UPDATE players SET eliminated=1 WHERE points <= -10")

    # ✅ Clear numbers for survivors (so they must input again)
    cur.execute("UPDATE players SET number=NULL WHERE eliminated=0")

    now_s = time.time()

    # ✅ Increment round and reset flags
    cur.execute("""
        UPDATE game_state 
           SET current_round = current_round + 1,
               resultroom_entered = 0,
               result_timer_start = 0,
               results_ready = 0,
               next_round_open = 1,
               round_start_time = %s
         WHERE id = 1
    """, (now_s,))

    conn.commit()
    conn.close()
    start_input_timer_for_current_round()
    # ✅ Sync with session
    session['round'] = session.get('round', 1) + 1
    session['results_ready'] = False

    return ("", 204)
GLOBAL_INPUT_TIMER = {"start": None, "round": None}

def start_input_timer_for_current_round():
    GLOBAL_INPUT_TIMER["start"] = time.time()
    GLOBAL_INPUT_TIMER["round"] = get_current_round()
@app.route("/api/round_state")
def api_round_state():
    conn = get_conn()
    c = conn.cursor(dictionary=True)

    c.execute("""
        SELECT current_round, resultroom_entered, result_timer_start, results_ready, next_round_open
        FROM game_state
        WHERE id=1
    """)
    row = c.fetchone()
    conn.close()

    if not row:
        return {"error": "no game_state row"}, 404

    return row  # Flask will jsonify automatically

@app.route("/api/resultroom_state")
def api_resultroom_state():
    conn = get_conn()
    c = conn.cursor(dictionary=True)

    # get DB row
    c.execute("SELECT result_timer_start FROM game_state WHERE id=1")
    row = c.fetchone()
    conn.close()

    if not row or not row["result_timer_start"]:
        return jsonify({"timer_running": False, "remaining": 0, "server_now_ms": int(time.time()*1000)})

    start_time = int(row["result_timer_start"])   # stored as unix timestamp (seconds or ms, check your setup)
    now = int(time.time())
    elapsed = now - start_time
    remaining = RESULTROOM_DURATION - elapsed

    if remaining <= 0:
        return jsonify({"timer_running": False, "remaining": 0, "server_now_ms": int(time.time()*1000)})
    else:
        return jsonify({
            "timer_running": True,
            "remaining": remaining,
            "server_now_ms": int(time.time()*1000)
        })
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
