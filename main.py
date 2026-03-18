import sys
import os
import uuid
import subprocess
import requests
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS

print("DOC·AI Server initializing...", flush=True)
sys.stdout.flush()

app = Flask(__name__)
CORS(app)

WORK_DIR = '/tmp/docai'
os.makedirs(WORK_DIR, exist_ok=True)

print("Flask app created. Registering routes...", flush=True)

def download_clip(url, path):
    r = requests.get(url, stream=True, timeout=60)
    with open(path, 'wb') as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)
    return path

def trim_clip(input_path, output_path, duration):
    cmd = [
        'ffmpeg', '-i', input_path,
        '-t', str(duration),
        '-c:v', 'libx264',
        '-c:a', 'aac',
        '-y', output_path
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        print("FFmpeg trim error:", result.stderr.decode(), flush=True)
    return output_path

def create_text_clip(text, duration, output_path):
    safe_text = text.replace("'", "").replace(":", "").replace(",", "")
    cmd = [
        'ffmpeg',
        '-f', 'lavfi',
        '-i', f'color=c=black:s=1280x720:d={duration}',
        '-vf', f"drawtext=text='{safe_text}':fontcolor=white:fontsize=40:x=(w-text_w)/2:y=(h-text_h)/2",
        '-c:v', 'libx264',
        '-y', output_path
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        print("FFmpeg text error:", result.stderr.decode(), flush=True)
    return output_path

def concat_clips(clip_paths, output_path):
    list_path = os.path.join(WORK_DIR, 'concat_list.txt')
    with open(list_path, 'w') as f:
        for clip in clip_paths:
            f.write(f"file '{clip}'\n")
    cmd = [
        'ffmpeg',
        '-f', 'concat',
        '-safe', '0',
        '-i', list_path,
        '-c:v', 'libx264',
        '-c:a', 'aac',
        '-y', output_path
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        print("FFmpeg concat error:", result.stderr.decode(), flush=True)
    return output_path

@app.route('/health', methods=['GET'])
def health():
    print("Health check called", flush=True)
    return jsonify({'status': 'ok', 'message': 'DOC·AI Server running'})

@app.route('/render', methods=['POST'])
def render():
    try:
        data = request.get_json()
        job_id = data.get('jobId', str(uuid.uuid4()))
        scenes = data.get('scenes', [])
        print(f"Render job {job_id} started with {len(scenes)} scenes", flush=True)

        if not scenes:
            return jsonify({'error': 'No scenes provided'}), 400

        job_dir = os.path.join(WORK_DIR, job_id)
        os.makedirs(job_dir, exist_ok=True)
        processed_clips = []

        for i, scene in enumerate(scenes):
            scene_type = scene.get('type', 'neutral')
            duration = scene.get('duration', 5)
            footage_url = scene.get('footageUrl')
            timestamp_text = scene.get('timestampText', f'Scene {i+1}')
            order = scene.get('order', i + 1)

            print(f"Processing scene {order}/{len(scenes)}", flush=True)
            trimmed_path = os.path.join(job_dir, f'scene_{str(order).zfill(2)}.mp4')

            if scene_type == 'timestamp':
                create_text_clip(timestamp_text, duration, trimmed_path)
            elif footage_url:
                raw_path = os.path.join(job_dir, f'raw_{str(order).zfill(2)}.mp4')
                download_clip(footage_url, raw_path)
                trim_clip(raw_path, trimmed_path, duration)
            else:
                create_text_clip(f'Scene {order} - Add Grok Image', duration, trimmed_path)

            processed_clips.append(trimmed_path)

        output_path = os.path.join(job_dir, f'documentary_{job_id}.mp4')
        concat_clips(processed_clips, output_path)
        print(f"Render complete: {output_path}", flush=True)

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

