"""
Flask application handling API routing and bridging the frontend to OpenCV tracking.
"""
import os
import time
import uuid
from flask import Flask, Response, jsonify, render_template, request
from werkzeug.utils import secure_filename
from detector import (
    generate_live_stream, live_state, TEST_REGISTRY, process_video_file,
    get_required_duration, get_video_duration_seconds,
)
from benchmarks import build_profile

app = Flask(__name__)

UPLOAD_DIR = os.path.join(app.root_path, 'static', 'uploads')
os.makedirs(UPLOAD_DIR, exist_ok=True)
ALLOWED_VIDEO_EXTENSIONS = {'mp4', 'mov', 'avi', 'webm', 'mkv', 'm4v'}


def _is_allowed_video(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_VIDEO_EXTENSIONS

# User stats (Global). 
user_stats = {
    "running_spot": {"score": 0, "reps": 0},
    "high_knees": {"score": 0, "reps": 0},
    "jump": {"score": 0, "best_cm": 0},
    "pushup": {"score": 0, "reps": 0},
    "plank": {"score": 0, "reps": 0},
}


@app.route('/')
def index():
    """Serves the main frontend dashboard."""
    return render_template('index.html')


@app.route('/video_feed')
def video_feed():
    """Streams the OpenCV video feed using multipart replacement."""
    
    # If a feed already exists (e.g. from a page refresh), force it to terminate
    # before spinning up a new one so they don't fight over webcam access.
    if live_state.stream_active:
        live_state.is_streaming = False
        start_wait = time.time()
        # Wait up to 2 seconds for the old camera thread to release hardware
        while live_state.stream_active and time.time() - start_wait < 2.0:
            time.sleep(0.1)
            
    return Response(
        generate_live_stream(), 
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )


@app.route('/set_mode', methods=['POST'])
def set_mode():
    """Changes the active fitness test mode."""
    data = request.json or {}
    mode = data.get("mode", "high_knees")
    
    if mode not in TEST_REGISTRY:
        return jsonify({"status": "error", "message": f"Unknown mode '{mode}'"}), 400
        
    live_state.set_test(mode)
    return jsonify({"status": "initialized", "mode": mode})


@app.route('/start_test', methods=['POST'])
def start_test():
    """Triggers the active test to begin tracking."""
    live_state.start_test()
    return jsonify({"status": "started", "snapshot": live_state.snapshot()})


@app.route('/restart_test', methods=['POST'])
def restart_test():
    """Resets the currently active test data."""
    live_state.restart_test()
    return jsonify({"status": "restarted", "snapshot": live_state.snapshot()})


@app.route('/upload_video', methods=['POST'])
def upload_video():
    """Processes an uploaded video file end-to-end (instead of the live webcam)
    and returns the final score, a URL to the annotated replay, and a
    per-frame timeline the frontend uses to sync the rep counter to
    playback instead of showing one frozen final number."""
    file = request.files.get('video')
    mode = request.form.get('mode', 'high_knees')

    if not file or file.filename == '':
        return jsonify({"status": "error", "message": "No video file provided"}), 400
    if not _is_allowed_video(file.filename):
        return jsonify({"status": "error", "message": "Unsupported video format"}), 400
    if mode not in TEST_REGISTRY:
        return jsonify({"status": "error", "message": f"Unknown mode '{mode}'"}), 400

    uid = uuid.uuid4().hex
    upload_path = os.path.join(UPLOAD_DIR, f"{uid}_{secure_filename(file.filename)}")
    file.save(upload_path)

    # Reject clips that are too short for the selected test before running
    # them through the (expensive) pose-tracking pipeline. If the duration
    # can't be determined (unusual codec/container), skip the check and let
    # process_video_file surface any real problem instead.
    required_duration = get_required_duration(mode)
    if required_duration:
        video_duration = get_video_duration_seconds(upload_path)
        if video_duration is not None and video_duration < required_duration:
            os.remove(upload_path)
            return jsonify({
                "status": "error",
                "message": (
                    f"This clip is too short for the {mode.replace('_', ' ')} test — "
                    f"it needs to be at least {required_duration:.0f}s long, but this "
                    f"video is only {video_duration:.1f}s."
                ),
            }), 400

    # No extension here — process_video_file picks whichever codec actually
    # works on this machine and appends the matching extension itself.
    output_base_path = os.path.join(UPLOAD_DIR, f"annotated_{uid}")

    try:
        result = process_video_file(upload_path, output_base_path, mode)
    except Exception as e:
        return jsonify({"status": "error", "message": f"Could not process video: {e}"}), 500
    finally:
        if os.path.exists(upload_path):
            os.remove(upload_path)

    output_filename = os.path.basename(result["output_path"])
    return jsonify({
        "status": "processed",
        "video_url": f"/static/uploads/{output_filename}",
        "timeline": result["timeline"],
        **result["final"],
    })


@app.route('/delete_video', methods=['POST'])
def delete_video():
    """Deletes a previously generated annotated replay from static/uploads.
    The frontend calls this once a replay is no longer needed — a new
    upload replaces it, the user switches events, or leaves upload mode —
    so processed clips don't pile up on disk indefinitely."""
    data = request.json or {}
    filename = secure_filename(data.get("filename", ""))

    # Only ever delete files this app generated itself.
    if not filename.startswith("annotated_"):
        return jsonify({"status": "error", "message": "Invalid filename"}), 400

    path = os.path.join(UPLOAD_DIR, filename)
    if os.path.exists(path):
        os.remove(path)
    return jsonify({"status": "deleted"})


@app.route('/live_stats')
def live_stats():
    """
    Returns real-time telemetry from the OpenCV processing thread.
    Also acts as a heartbeat check to keep the webcam stream alive.
    """
    live_state.ping()
    return jsonify(live_state.snapshot())


@app.route('/save_score', methods=['POST'])
def save_score():
    """Commits the current session's score to the local user_stats dictionary.
    Accepts an optional JSON snapshot (used after an uploaded-video result,
    which lives client-side rather than in `live_state`); falls back to the
    live webcam telemetry when no snapshot is provided."""
    posted = request.json or {}
    snap = posted if posted.get("test") else live_state.snapshot()
    test = snap.get("test")

    if test == "jump":
        user_stats["jump"] = {
            "score": snap.get("score", 0),
            "best_cm": snap.get("best_jump_cm", 0),
        }
    elif test in user_stats:
        user_stats[test] = {
            "score": snap.get("score", 0),
            "reps": snap.get("reps", 0),
        }

    return jsonify({"status": "saved", "saved_data": user_stats})


@app.route('/generate_profile', methods=['GET'])
def generate_profile():
    """Generates an athletic profile: best-fit sport (weighted across all
    five tests), a specific position within that sport, a player archetype
    built from the athlete's standout metric, and a percentile rank for
    each test against approximate population benchmarks."""
    metrics = {
        "running_spot": user_stats["running_spot"]["score"],
        "high_knees": user_stats["high_knees"]["score"],
        "jump": user_stats["jump"]["score"],
        "pushup": user_stats["pushup"]["score"],
        "plank": user_stats["plank"]["score"],
    }
    jump_cm = user_stats["jump"]["best_cm"]

    profile = build_profile(metrics, jump_cm)

    return jsonify({
        "sport": profile["sport"],
        "position": profile["position"],
        "archetype": profile["archetype"],
        "archetype_desc": profile["archetype_desc"],
        "skills": profile["skills"],
        "run_stat": metrics["running_spot"],
        "knee_stat": metrics["high_knees"],
        "jump_stat": jump_cm,
        "jump_score": metrics["jump"],
        "pushup_stat": metrics["pushup"],
        "plank_stat": metrics["plank"],
        "percentiles": profile["percentiles"],
    })


if __name__ == '__main__':
    # Initial setup
    live_state.set_test("running_spot")

    HOST = '127.0.0.1'
    PORT = 5001

    print(f"\n🚀 Combine AI Dashboard is live! Open your browser and go to:")
    print(f"👉 http://{HOST}:{PORT}\n")

    # threaded=True so a slow, blocking /upload_video request can't stall the
    # live MJPEG stream or the /live_stats poll for other concurrent requests.
    app.run(host=HOST, port=PORT, debug=False, threaded=True)
