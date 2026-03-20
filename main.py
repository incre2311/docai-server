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
#  WIKIPEDIA: Download image by URL
# ─────────────────────────────────────────
def download_image_as_clip(image_url, output_path, duration):
    """Download a Wikipedia/news image and convert it to a video clip with Ken Burns"""
    img_path = output_path.replace('.mp4', '_img.jpg')
    try:
        headers = {'User-Agent': 'Mozilla/5.0 DocAI/1.0'}
        r = requests.get(image_url, timeout=20, headers=headers)
        if r.status_code == 200:
            with open(img_path, 'wb') as f:
                f.write(r.content)
            if os.path.getsize(img_path) > 1000:
                # Convert image to video with slow Ken Burns zoom
                frames = int(duration * 25)
                cmd = [
                    'ffmpeg',
                    '-loop', '1',
                    '-i', img_path,
                    '-vf', (
                        f'scale=8000:-1,'
                        f'zoompan=z=\'min(zoom+0.0008,1.3)\':d={frames}'
                        f':x=\'iw/2-(iw/zoom/2)\':y=\'ih/2-(ih/zoom/2)\':s=1280x720:fps=25,'
                        f'setsar=1'
                    ),
                    '-t', str(duration),
                    '-c:v', 'libx264', '-preset', 'ultrafast',
                    '-pix_fmt', 'yuv420p',
                    '-y', output_path
                ]
                result = subprocess.run(cmd, capture_output=True, timeout=30)
                if result.returncode == 0:
                    print(f"Image to clip OK: {image_url[:40]}", flush=True)
                    return output_path
    except Exception as e:
        print(f"Image clip error: {str(e)}", flush=True)
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
#  TEXT CLIP with optional overlay text
# ─────────────────────────────────────────
def fast_text_clip(text, duration, output_path, overlay=None):
    safe = text.replace("'","").replace('"','').replace(':','').replace(',','')[:50]
    if overlay:
        # Show overlay text (news headline / evidence)
        safe_overlay = overlay.replace("'","").replace('"','').replace(':','').replace(',','')[:80]
        vf = (
            f"drawtext=text='{safe_overlay}':fontcolor=white:fontsize=32"
            f":x=(w-text_w)/2:y=(h-text_h)/2"
            f":box=1:boxcolor=black@0.7:boxborderw=15"
        )
    else:
        vf = (
            f"drawtext=text='{safe}':fontcolor=white:fontsize=36"
            f":x=(w-text_w)/2:y=(h-text_h)/2"
        )
    cmd = [
        'ffmpeg', '-f', 'lavfi',
        '-i', f'color=c=black:s=1280x720:d={duration}',
        '-vf', vf,
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
#  INTRO
# ─────────────────────────────────────────
def fast_intro(title, output_path, duration=4):
    safe = title.replace("'","").replace('"','')[:40]
    cmd = [
        'ffmpeg', '-f', 'lavfi',
        '-i', f'color=c=black:s=1280x720:d={duration}',
        '-vf', (
            f"drawtext=text='{safe}':fontcolor=white:fontsize=52"
            f":x=(w-text_w)/2:y=(h-text_h)/2-20,"
            f"drawtext=text='A Documentary':fontcolor=gray:fontsize=20"
            f":x=(w-text_w)/2:y=(h-text_h)/2+30"
        ),
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
#  BETTER AMBIENT AUDIO — dark cinematic tone
# ─────────────────────────────────────────
def generate_ambient_audio(output_path, duration):
    """Generate dark cinematic ambient audio — two layered tones"""
    cmd = [
        'ffmpeg',
        '-f', 'lavfi',
        '-i', f'sine=frequency=60:duration={duration}',
        '-f', 'lavfi',
        '-i', f'sine=frequency=80:duration={duration}',
        '-filter_complex',
        '[0:a]volume=0.06[a1];[1:a]volume=0.04[a2];[a1][a2]amix=inputs=2[aout]',
        '-map', '[aout]',
        '-c:a', 'aac', '-b:a', '64k',
        '-y', output_path
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=20)
    if result.returncode != 0:
        # Simple fallback tone
        fallback = [
            'ffmpeg', '-f', 'lavfi',
            '-i', f'sine=frequency=55:duration={duration}',
            '-af', 'volume=0.05',
            '-c:a', 'aac', '-b:a', '64k',
            '-y', output_path
        ]
        result2 = subprocess.run(fallback, capture_output=True, timeout=15)
        if result2.returncode != 0:
            return None
    return output_path

# ─────────────────────────────────────────
#  MIX NARRATION AUDIO PER SCENE
# ─────────────────────────────────────────
def mix_narration_into_clip(video_path, narration_url, output_path, duration):
    """Download narration audio from URL and mix into video clip"""
    narration_path = video_path.replace('.mp4', '_narration.mp3')
    try:
        r = requests.get(narration_url, timeout=20)
        if r.status_code == 200:
            with open(narration_path, 'wb') as f:
                f.write(r.content)
            cmd = [
                'ffmpeg',
                '-i', video_path,
                '-i', narration_path,
                '-filter_complex',
                '[1:a]volume=1.0[narr];[0:a]volume=0.1[bg];[narr][bg]amix=inputs=2:duration=first[aout]',
                '-map', '0:v',
                '-map', '[aout]',
                '-c:v', 'copy',
                '-c:a', 'aac',
                '-t', str(duration),
                '-y', output_path
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=30)
            if result.returncode == 0:
                print(f"Narration mixed OK", flush=True)
                return output_path
    except Exception as e:
        print(f"Narration mix error: {str(e)}", flush=True)
    return video_path

# ─────────────────────────────────────────
#  MIX AMBIENT AUDIO INTO FINAL VIDEO
# ─────────────────────────────────────────
def mix_ambient_into_final(video_path, audio_path, output_path, duration):
    cmd = [
        'ffmpeg',
        '-i', video_path,
        '-i', audio_path,
        '-filter_complex',
        f'[1:a]volume=0.12,atrim=0:{duration}[amb];[0:a][amb]amix=inputs=2:duration=first[aout]',
        '-map', '0:v',
        '-map', '[aout]',
        '-c:v', 'copy',
        '-c:a', 'aac', '-b:a', '128k',
        '-t', str(duration),
        '-y', output_path
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=30)
    if result.returncode != 0:
        print("Ambient mix error:", result.stderr.decode()[:100], flush=True)
        return video_path
    return output_path

# ─────────────────────────────────────────
#  FAST CONCAT
# ─────────────────────────────────────────
def fast_concat(clip_paths, output_path):
    valid = [c for c in clip_paths if os.path.exists(c) and os.path.getsize(c) > 100]
    if not valid:
        print("No valid clips!", flush=True)
        return None
    print(f"Concatenating {len(valid)} clips", flush=True)
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
        print(f"RENDER - {len(scenes)} scenes - {title}", flush=True)

        if not scenes:
            return jsonify({'error': 'No scenes provided'}), 400

        job_dir = os.path.join(WORK_DIR, job_id)
        os.makedirs(job_dir, exist_ok=True)
        all_clips = []
        used_urls = set()

        # INTRO
        intro_path = os.path.join(job_dir, '00_intro.mp4')
        fast_intro(title, intro_path, duration=4)
        if os.path.exists(intro_path):
            all_clips.append(intro_path)

        total_duration = 4  # intro

        # SCENES
        for i, scene in enumerate(scenes):
            scene_type = scene.get('type', 'neutral')
            duration = max(3, min(scene.get('duration', 5), 20))
            footage_url = scene.get('footageUrl')
            image_url = scene.get('imageUrl')
            timestamp_text = scene.get('timestampText', f'Scene {i+1}')
            narration_text = scene.get('narrationText', f'Scene {i+1}')
            narration_url = scene.get('narrationUrl')
            overlay = scene.get('overlay')
            order = scene.get('order', i + 1)

            print(f"Scene {order}/{len(scenes)} [{scene_type}] {duration}s", flush=True)

            processed_path = os.path.join(job_dir, f'scene_{str(order).zfill(2)}.mp4')
            final_scene_path = os.path.join(job_dir, f'final_scene_{str(order).zfill(2)}.mp4')

            if scene_type == 'timestamp':
                # Timestamp — text overlay always
                fast_text_clip(timestamp_text, duration, processed_path)

            elif footage_url and footage_url not in used_urls:
                # Video footage available
                raw_path = os.path.join(job_dir, f'raw_{str(order).zfill(2)}.mp4')
                dl = download_clip(footage_url, raw_path)
                if dl and os.path.exists(raw_path) and os.path.getsize(raw_path) > 1000:
                    result = fast_trim(raw_path, processed_path, duration)
                    if result:
                        used_urls.add(footage_url)
                    else:
                        fast_text_clip(narration_text[:50], duration, processed_path, overlay=overlay)
                else:
                    fast_text_clip(narration_text[:50], duration, processed_path, overlay=overlay)

            elif image_url:
                # Wikipedia/news image — convert to Ken Burns clip
                img_clip = download_image_as_clip(image_url, processed_path, duration)
                if not img_clip:
                    fast_text_clip(narration_text[:50], duration, processed_path, overlay=overlay)

            elif overlay:
                # Google News headline or Claude research overlay
                fast_text_clip(overlay[:80], duration, processed_path, overlay=overlay)

            else:
                # Pure text fallback
                fast_text_clip(narration_text[:50], duration, processed_path)

            # Mix narration audio into scene if available
            if os.path.exists(processed_path) and narration_url:
                mix_result = mix_narration_into_clip(
                    processed_path, narration_url, final_scene_path, duration
                )
                clip_to_use = final_scene_path if os.path.exists(final_scene_path) else processed_path
            else:
                clip_to_use = processed_path

            if os.path.exists(clip_to_use) and os.path.getsize(clip_to_use) > 100:
                all_clips.append(clip_to_use)
                total_duration += duration
                print(f"Scene {order} OK", flush=True)
            else:
                # Emergency fallback
                print(f"Scene {order} FAILED - emergency fallback", flush=True)
                fast_text_clip(f'Scene {order}', duration, processed_path)
                if os.path.exists(processed_path):
                    all_clips.append(processed_path)
                    total_duration += duration

        # OUTRO
        outro_path = os.path.join(job_dir, 'outro.mp4')
        fast_text_clip('', 3, outro_path)
        if os.path.exists(outro_path):
            all_clips.append(outro_path)
            total_duration += 3

        # CONCAT
        output_path = os.path.join(job_dir, f'documentary_{job_id}.mp4')
        concat_result = fast_concat(all_clips, output_path)
        if not concat_result or not os.path.exists(output_path):
            return jsonify({'error': 'Concat failed'}), 500

        # ADD AMBIENT AUDIO to final video
        audio_path = os.path.join(job_dir, 'ambient.aac')
        final_path = os.path.join(job_dir, f'final_{job_id}.mp4')
        audio_result = generate_ambient_audio(audio_path, total_duration)
        if audio_result and os.path.exists(audio_path):
            mixed = mix_ambient_into_final(output_path, audio_path, final_path, total_duration)
            if mixed != output_path and os.path.exists(final_path):
                output_path = final_path
                print("Ambient audio mixed OK", flush=True)

        size_mb = os.path.getsize(output_path) / 1024 / 1024
        print(f"RENDER COMPLETE - {size_mb:.1f}MB - {total_duration}s", flush=True)

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
