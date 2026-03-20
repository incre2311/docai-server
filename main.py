import sys
import os
import time
import uuid
import subprocess
import requests
from flask import Flask, request, jsonify, send_file, Response
from flask_cors import CORS

print("DOC-AI Server initializing...", flush=True)
sys.stdout.flush()

app = Flask(__name__)
CORS(app, origins="*", allow_headers=["Content-Type"], methods=["GET", "POST", "OPTIONS"])

@app.after_request
def after_request(response):
    response.headers.add(‘Access-Control-Allow-Origin’, ‘*’)
    response.headers.add(‘Access-Control-Allow-Headers’, ‘Content-Type’)
    response.headers.add(‘Access-Control-Allow-Methods’, ‘GET, POST, OPTIONS’)
    return response

WORK_DIR = ‘/tmp/docai’
os.makedirs(WORK_DIR, exist_ok=True)
print(“Flask app created.”, flush=True)

# ─────────────────────────────────────────

# DOWNLOAD WITH RETRY

# ─────────────────────────────────────────

def download_clip(url, path):
headers = {
‘User-Agent’: ‘Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36’,
‘Referer’: ‘https://www.pexels.com/’
}
for attempt in range(2):
try:
print(f"Download attempt {attempt+1}: {url[:50]}", flush=True)
r = requests.get(url, stream=True, timeout=30, headers=headers)
if r.status_code == 200:
with open(path, ‘wb’) as f:
for chunk in r.iter_content(chunk_size=8192):
f.write(chunk)
if os.path.exists(path) and os.path.getsize(path) > 1000:
print(f"Download OK: {os.path.getsize(path)} bytes", flush=True)
return path
print(f"Download failed: status {r.status_code}", flush=True)
except Exception as e:
print(f"Download error: {str(e)}", flush=True)
if attempt == 0:
time.sleep(1)
return None

# ─────────────────────────────────────────

# FAST TRIM — just cut to duration, no effects

# ─────────────────────────────────────────

def fast_trim(input_path, output_path, duration):
cmd = [
‘ffmpeg’, ‘-i’, input_path,
‘-t’, str(duration),
‘-vf’, ‘scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2’,
‘-c:v’, ‘libx264’, ‘-preset’, ‘ultrafast’,
‘-c:a’, ‘aac’,
‘-y’, output_path
]
result = subprocess.run(cmd, capture_output=True, timeout=25)
if result.returncode != 0:
print("Trim error:", result.stderr.decode()[:100], flush=True)
return None
return output_path

# ─────────────────────────────────────────

# FAST TEXT CLIP — black screen with text

# ─────────────────────────────────────────

def fast_text_clip(text, duration, output_path):
safe = text.replace("’","").replace(’"','').replace(’:’,’’).replace(’,’,’’)[:50]
cmd = [
‘ffmpeg’, ‘-f’, ‘lavfi’,
‘-i’, f’color=c=black:s=1280x720:d={duration}’,
‘-vf’, f”drawtext=text=’{safe}’:fontcolor=white:fontsize=40:x=(w-text_w)/2:y=(h-text_h)/2”,
‘-c:v’, ‘libx264’, ‘-preset’, ‘ultrafast’,
‘-y’, output_path
]
result = subprocess.run(cmd, capture_output=True, timeout=15)
if result.returncode != 0:
# Ultra fallback — pure black clip
fallback = [‘ffmpeg’, ‘-f’, ‘lavfi’, ‘-i’, f’color=c=black:s=1280x720:d={duration}’,
‘-c:v’, ‘libx264’, ‘-preset’, ‘ultrafast’, ‘-y’, output_path]
subprocess.run(fallback, capture_output=True, timeout=10)
return output_path

# ─────────────────────────────────────────

# FAST INTRO

# ─────────────────────────────────────────

def fast_intro(title, output_path, duration=4):
safe = title.replace("'","").replace(’"’,’’)[:40]
cmd = [
‘ffmpeg’, ‘-f’, ‘lavfi’,
‘-i’, f’color=c=black:s=1280x720:d={duration}’,
‘-vf’, (f"drawtext=text=’{safe}’:fontcolor=white:fontsize=56"
f":x=(w-text_w)/2:y=(h-text_h)/2-20,"
f"drawtext=text=‘A Documentary’:fontcolor=gray:fontsize=22"
f":x=(w-text_w)/2:y=(h-text_h)/2+30"),
‘-c:v’, ‘libx264’, ‘-preset’, ‘ultrafast’,
‘-y’, output_path
]
result = subprocess.run(cmd, capture_output=True, timeout=15)
if result.returncode != 0:
fallback = [‘ffmpeg’, ‘-f’, ‘lavfi’, ‘-i’, f’color=c=black:s=1280x720:d={duration}’,
‘-c:v’, ‘libx264’, ‘-preset’, ‘ultrafast’, ‘-y’, output_path]
subprocess.run(fallback, capture_output=True, timeout=10)
return output_path

# ─────────────────────────────────────────

# FAST CONCAT

# ─────────────────────────────────────────

def fast_concat(clip_paths, output_path):
# Filter only existing clips
valid = [c for c in clip_paths if os.path.exists(c) and os.path.getsize(c) > 100]
if not valid:
print("No valid clips to concat!", flush=True)
return None

```
list_path = os.path.join(WORK_DIR, 'concat_list.txt')
with open(list_path, 'w') as f:
    for clip in valid:
        f.write(f"file '{clip}'\n")

cmd = [
    'ffmpeg', '-f', 'concat', '-safe', '0', '-i', list_path,
    '-c:v', 'libx264', '-preset', 'ultrafast',
    '-c:a', 'aac',
    '-movflags', '+faststart',
    '-y', output_path
]
result = subprocess.run(cmd, capture_output=True, timeout=60)
if result.returncode != 0:
    print("Concat error:", result.stderr.decode()[:200], flush=True)
    return None
return output_path
```

# ─────────────────────────────────────────

# ROUTES

# ─────────────────────────────────────────

@app.route(’/’, methods=[‘GET’])
def index():
html_path = os.path.join(os.path.dirname(__file__), ‘tool.html’)
with open(html_path, ‘r’) as f:
html = f.read()
return Response(html, mimetype=‘text/html’)

@app.route(’/health’, methods=[‘GET’])
def health():
return jsonify({‘status’: ‘ok’, ‘message’: ‘DOC·AI Server running’})

@app.route(’/render’, methods=[‘POST’, ‘OPTIONS’])
def render():
if request.method == ‘OPTIONS’:
return ‘’, 200
try:
data = request.get_json()
job_id = data.get(‘jobId’, str(uuid.uuid4()))
scenes = data.get(‘scenes’, [])
title = data.get(‘title’, ‘Documentary’)
print(f"RENDER START — {len(scenes)} scenes — {title}", flush=True)

```
    if not scenes:
        return jsonify({'error': 'No scenes provided'}), 400

    job_dir = os.path.join(WORK_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)
    all_clips = []

    # INTRO
    intro_path = os.path.join(job_dir, '00_intro.mp4')
    fast_intro(title, intro_path, duration=4)
    if os.path.exists(intro_path):
        all_clips.append(intro_path)

    # SCENES
    for i, scene in enumerate(scenes):
        scene_type = scene.get('type', 'neutral')
        duration = max(3, min(scene.get('duration', 5), 30))  # cap at 30s per scene
        footage_url = scene.get('footageUrl')
        timestamp_text = scene.get('timestampText', f'Scene {i+1}')
        narration_text = scene.get('narrationText', f'Scene {i+1}')
        order = scene.get('order', i + 1)

        print(f"Scene {order}/{len(scenes)} [{scene_type}] {duration}s", flush=True)
        processed_path = os.path.join(job_dir, f'scene_{str(order).zfill(2)}.mp4')

        if scene_type == 'timestamp':
            fast_text_clip(timestamp_text, duration, processed_path)

        elif footage_url:
            raw_path = os.path.join(job_dir, f'raw_{str(order).zfill(2)}.mp4')
            dl = download_clip(footage_url, raw_path)
            if dl:
                result = fast_trim(raw_path, processed_path, duration)
                if not result:
                    fast_text_clip(narration_text[:50], duration, processed_path)
            else:
                fast_text_clip(narration_text[:50], duration, processed_path)
        else:
            fast_text_clip(narration_text[:50], duration, processed_path)

        if os.path.exists(processed_path):
            all_clips.append(processed_path)
            print(f"Scene {order} done ✓", flush=True)
        else:
            print(f"Scene {order} FAILED", flush=True)

    # OUTRO
    outro_path = os.path.join(job_dir, 'outro.mp4')
    fast_text_clip('', 3, outro_path)
    if os.path.exists(outro_path):
        all_clips.append(outro_path)

    # FINAL CONCAT
    output_path = os.path.join(job_dir, f'documentary_{job_id}.mp4')
    print(f"Concatenating {len(all_clips)} clips...", flush=True)
    result = fast_concat(all_clips, output_path)

    if not result or not os.path.exists(output_path):
        return jsonify({'error': 'Concat failed'}), 500

    size_mb = os.path.getsize(output_path) / 1024 / 1024
    print(f"RENDER COMPLETE — {size_mb:.1f}MB", flush=True)

    return send_file(
        output_path,
        mimetype='video/mp4',
        as_attachment=True,
        download_name=f'documentary_{job_id}.mp4'
    )

except Exception as e:
    print(f"Render error: {str(e)}", flush=True)
    return jsonify({'error': str(e)}), 500
```

print("Routes registered. Starting server…", flush=True)

if **name** == ‘**main**’:
port = int(os.environ.get(‘PORT’, 8080))
print(f"Starting on port {port}", flush=True)
app.run(host=‘0.0.0.0’, port=port, debug=False, threaded=True)
