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
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
    response.headers.add('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
    return response

WORK_DIR = '/tmp/docai'
os.makedirs(WORK_DIR, exist_ok=True)

# Default fallback clip — pure black
DEFAULT_CLIP_DURATION = 5

print("Flask app created.", flush=True)

# ─────────────────────────────────────────
#  DOWNLOAD WITH RETRY
# ─────────────────────────────────────────
def download_clip(url, path):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://www.pexels.com/'
    }
    for attempt in range(2):
        try:
            print(f"Download attempt {attempt+1}: {url[:50]}", flush=True)
            r = requests.get(url, stream=True, timeout=30, headers=headers)
            if r.status_code == 200:
                with open(path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
                # FIX 4: File validation after download
                if os.path.exists(path) and os.path.getsize(path) > 1000:
                    print(f"Download OK: {os.path.getsize(path)} bytes", flush=True)
                    return path
                else:
                    print(f"Download file too small or missing", flush=True)
            else:
                print(f"Download failed: status {r.status_code}", flush=True)
        except Exception as e:
            print(f"Download error: {str(e)}", flush=True)
        if attempt == 0:
            time.sleep(1)
    print("Both download attempts failed", flush=True)
    return None

# ─────────────────────────────────────────
#  FAST TRIM
# ─────────────────────────────────────────
def fast_trim(input_path, output_path, duration):
    cmd = [
        'ffmpeg', '-i', input_path,
        '-t', str(duration),
        '-vf', 'scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2',
        '-c:v', 'libx264', '-preset', 'ultrafast',
        '-c:a', 'aac',
        '-y', output_path
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=25)
    if result.returncode != 0:
        print("Trim error:", result.stderr.decode()[:100], flush=True)
        return None
    return output_path

# ─────────────────────────────────────────
#  FAST TEXT CLIP
# ─────────────────────────────────────────
def fast_text_clip(text, duration, output_path):
    safe = text.replace("'","").replace('"','').replace(':','').replace(',','')[:50]
    cmd = [
        'ffmpeg', '-f', 'lavfi',
        '-i', f'color=c=black:s=1280x720:d={duration}',
        '-vf', f"drawtext=text='{safe}':fontcolor=white:fontsize=36:x=(w-text_w)/2:y=(h-text_h)/2",
        '-c:v', 'libx264', '-preset', 'ultrafast',
        '-y', output_path
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=15)
    if result.returncode != 0:
        fallback = ['ffmpeg', '-f', 'lavfi', '-i', f'color=c=black:s=1280x720:d={duration}',
                    '-c:v', 'libx264', '-preset', 'ultrafast', '-y', output_path]
        subprocess.run(fallback, capture_output=True, timeout=10)
    return output_path

# ─────────────────────────────────────────
#  FAST INTRO
# ─────────────────────────────────────────
def fast_intro(title, output_path, duration=4):
    safe = title.replace("'","").replace('"','')[:40]
    cmd = [
        'ffmpeg', '-f', 'lavfi',
        '-i', f'color=c=black:s=1280x720:d={duration}',
        '-vf', (f"drawtext=text='{safe}':fontcolor=white:fontsize=52"
                f":x=(w-text_w)/2:y=(h-text_h)/2-20,"
                f"drawtext=text='A Documentary':fontcolor=gray:fontsize=20"
                f":x=(w-text_w)/2:y=(h-text_h)/2+30"),
        '-c:v', 'libx264', '-preset', 'ultrafast',
        '-y', output_path
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=15)
    if result.returncode != 0:
        fallback = ['ffmpeg', '-f', 'lavfi', '-i', f'color=c=black:s=1280x720:d={duration}',
                    '-c:v', 'libx264', '-preset', 'ultrafast', '-y', output_path]
        subprocess.run(fallback, capture_output=True, timeout=10)
    return output_path

# ─────────────────────────────────────────
#  FIX 6: GENERATE BACKGROUND MUSIC TONE
#  Creates a subtle dark ambient tone using FFmpeg
# ─────────────────────────────────────────
def generate_ambient_audio(output_path, duration):
    """Generate a dark cinematic ambient tone using FFmpeg sine waves"""
    cmd = [
        'ffmpeg',
        '-f', 'lavfi',
        # Mix two low sine waves for dark ambient feel
        '-i', f'sine=frequency=55:duration={duration}',
        '-af', 'volume=0.08,aecho=0.8:0.88:60:0.4',
        '-c:a', 'aac', '-b:a', '64k',
        '-y', output_path
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=20)
    if result.returncode != 0:
        print("Ambient audio error:", result.stderr.decode()[:100], flush=True)
        return None
    return output_path

# ─────────────────────────────────────────
#  MIX AUDIO INTO VIDEO
# ─────────────────────────────────────────
def mix_audio(video_path, audio_path, output_path, duration):
    """Mix ambient audio into silent video"""
    cmd = [
        'ffmpeg',
        '-i', video_path,
        '-i', audio_path,
        '-filter_complex', f'[1:a]volume=0.15,atrim=0:{duration}[a];[0:a][a]amix=inputs=2:duration=first[aout]',
        '-map', '0:v',
        '-map', '[aout]',
        '-c:v', 'copy',
        '-c:a', 'aac', '-b:a', '128k',
        '-t', str(duration),
        '-y', output_path
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=30)
    if result.returncode != 0:
        print("Audio mix error:", result.stderr.decode()[:100], flush=True)
        return video_path  # return original if mix fails
    return output_path

# ─────────────────────────────────────────
#  FAST CONCAT
# ─────────────────────────────────────────
def fast_concat(clip_paths, output_path):
    valid = [c for c in clip_paths if os.path.exists(c) and os.path.getsize(c) > 100]
    if not valid:
        print("No valid clips to concat!", flush=True)
        return None
    print(f"Concatenating {len(valid)} valid clips", flush=True)
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

# ─────────────────────────────────────────
#  ROUTES
# ─────────────────────────────────────────
@app.route('/', methods=['GET'])
def index():
    html_path = os.path.join(os.path.dirname(__file__), 'tool.html')
    with open(html_path, 'r') as f:
        html = f.read()
    return Response(html, mimetype='text/html')

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'message': 'DOC-AI Server running'})

@app.route('/render', methods=['POST', 'OPTIONS'])
def render():
    if request.method == 'OPTIONS':
        return '', 200
    try:
        data = request.get_json()
        job_id = data.get('jobId', str(uuid.uuid4()))
        scenes = data.get('scenes', [])
        title = data.get('title', 'Documentary')
        print(f"RENDER START - {len(scenes)} scenes - {title}", flush=True)

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
        used_urls = set()  # FIX 1: Track used URLs to prevent repeats

        for i, scene in enumerate(scenes):
            scene_type = scene.get('type', 'neutral')
            duration = max(3, min(scene.get('duration', 5), 20))
            footage_url = scene.get('footageUrl')
            timestamp_text = scene.get('timestampText', f'Scene {i+1}')
            narration_text = scene.get('narrationText', f'Scene {i+1}')
            order = scene.get('order', i + 1)

            print(f"Scene {order}/{len(scenes)} [{scene_type}] {duration}s", flush=True)

            # FIX 1: Unique path per scene using both job_id and order
            processed_path = os.path.join(job_dir, f'scene_{job_id[:8]}_{str(order).zfill(2)}.mp4')

            if scene_type == 'timestamp':
                fast_text_clip(timestamp_text, duration, processed_path)

            elif footage_url:
                # FIX 1: Skip if same URL already used
                if footage_url in used_urls:
                    print(f"Scene {order}: URL already used, using text fallback", flush=True)
                    fast_text_clip(narration_text[:50], duration, processed_path)
                else:
                    # FIX 3: Force download before processing
                    raw_path = os.path.join(job_dir, f'raw_{job_id[:8]}_{str(order).zfill(2)}.mp4')
                    dl = download_clip(footage_url, raw_path)

                    # FIX 4: Validate file exists and has content
                    if dl and os.path.exists(raw_path) and os.path.getsize(raw_path) > 1000:
                        result = fast_trim(raw_path, processed_path, duration)
                        if result:
                            used_urls.add(footage_url)
                        else:
                            # FIX 2: Use text fallback instead of skipping
                            fast_text_clip(narration_text[:50], duration, processed_path)
                    else:
                        print(f"Scene {order}: Download failed - using text fallback", flush=True)
                        fast_text_clip(narration_text[:50], duration, processed_path)
            else:
                # FIX 2: Never skip - always create something
                fast_text_clip(narration_text[:50], duration, processed_path)

            if os.path.exists(processed_path) and os.path.getsize(processed_path) > 100:
                all_clips.append(processed_path)
                print(f"Scene {order} done OK", flush=True)
            else:
                print(f"Scene {order} FAILED - creating emergency fallback", flush=True)
                fast_text_clip(f'Scene {order}', duration, processed_path)
                if os.path.exists(processed_path):
                    all_clips.append(processed_path)

        # OUTRO
        outro_path = os.path.join(job_dir, 'outro.mp4')
        fast_text_clip('', 3, outro_path)
        if os.path.exists(outro_path):
            all_clips.append(outro_path)

        # FINAL CONCAT
        output_path = os.path.join(job_dir, f'documentary_{job_id}.mp4')
        print(f"Concatenating {len(all_clips)} clips...", flush=True)
        concat_result = fast_concat(all_clips, output_path)

        if not concat_result or not os.path.exists(output_path):
            return jsonify({'error': 'Concat failed - no clips rendered'}), 500

        # FIX 6: Add ambient background audio
        total_duration = sum([max(3, min(s.get('duration', 5), 20)) for s in scenes]) + 7
        audio_path = os.path.join(job_dir, 'ambient.aac')
        final_path = os.path.join(job_dir, f'final_{job_id}.mp4')

        audio_result = generate_ambient_audio(audio_path, total_duration)
        if audio_result and os.path.exists(audio_path):
            mix_result = mix_audio(output_path, audio_path, final_path, total_duration)
            if mix_result != output_path and os.path.exists(final_path):
                output_path = final_path
                print("Audio mixed successfully", flush=True)

        size_mb = os.path.getsize(output_path) / 1024 / 1024
        print(f"RENDER COMPLETE - {size_mb:.1f}MB", flush=True)

        return send_file(
            output_path,
            mimetype='video/mp4',
            as_attachment=True,
            download_name=f'documentary_{job_id}.mp4'
        )

    except Exception as e:
        print(f"Render error: {str(e)}", flush=True)
        return jsonify({'error': str(e)}), 500

print("Routes registered. Starting server...", flush=True)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    print(f"Starting on port {port}", flush=True)
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
