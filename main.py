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
CORS(app, origins="*", allow_headers=["Content-Type"], methods=["GET", "POST", "OPTIONS"])

@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
    response.headers.add('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
    return response

WORK_DIR = '/tmp/docai'
os.makedirs(WORK_DIR, exist_ok=True)

print("Flask app created. Registering routes...", flush=True)

CUTTING_RULES = {
    'tense':     {'clip_duration': 2, 'zoom': 1.06},
    'emotional': {'clip_duration': 4, 'zoom': 1.02},
    'evidence':  {'clip_duration': 5, 'zoom': 1.0},
    'timestamp': {'clip_duration': 4, 'zoom': 1.0},
    'neutral':   {'clip_duration': 3, 'zoom': 1.03},
}

def get_base_filter(scene_type):
    base = (
        "scale=1280:720:force_original_aspect_ratio=decrease,"
        "pad=1280:720:(ow-iw)/2:(oh-ih)/2,"
        "eq=contrast=1.15:brightness=-0.02:saturation=0.9,"
        "vignette=PI/4"
    )
    if scene_type == 'tense':
        return (
            base + ","
            "curves=r='0/0 0.5/0.45 1/1':g='0/0 0.5/0.5 1/0.95':b='0/0 0.5/0.55 1/0.85',"
            "noise=alls=8:allf=t+u"
        )
    elif scene_type == 'emotional':
        return (
            base + ","
            "eq=saturation=0.5:contrast=1.1:brightness=-0.03,"
            "curves=r='0/0 1/0.95':g='0/0 1/0.92':b='0/0 1/0.88'"
        )
    elif scene_type == 'evidence':
        return (
            base + ","
            "curves=r='0/0 1/0.85':g='0/0 1/0.9':b='0/0 1/1.05',"
            "eq=contrast=1.2:saturation=0.7"
        )
    else:
        return (
            base + ","
            "curves=r='0/0 0.5/0.52 1/1':g='0/0 0.5/0.49 1/0.96':b='0/0 0.5/0.48 1/0.88'"
        )

def download_clip(url, path):
    print(f"Downloading: {url[:60]}...", flush=True)
    r = requests.get(url, stream=True, timeout=60)
    with open(path, 'wb') as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)
    return path

def trim_clip(input_path, output_path, duration, scene_type='neutral'):
    vf = get_base_filter(scene_type)
    cmd = [
        'ffmpeg', '-i', input_path,
        '-t', str(duration),
        '-vf', vf,
        '-c:v', 'libx264', '-c:a', 'aac',
        '-y', output_path
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        print("Trim error:", result.stderr.decode()[:200], flush=True)
        fallback = ['ffmpeg', '-i', input_path, '-t', str(duration),
                    '-vf', 'scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2',
                    '-c:v', 'libx264', '-c:a', 'aac', '-y', output_path]
        subprocess.run(fallback, capture_output=True)
    return output_path

def apply_kenburns(input_path, output_path, duration, zoom_factor=1.03, scene_type='neutral'):
    frames = int(duration * 25)
    zoom_per_frame = (zoom_factor - 1.0) / max(frames, 1)
    vf = (
        f"scale=8000:-1,"
        f"zoompan=z='min(zoom+{zoom_per_frame:.6f},1.5)'"
        f":d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1280x720:fps=25,"
        f"setsar=1,"
        f"eq=contrast=1.15:brightness=-0.02:saturation=0.9,"
        f"vignette=PI/4"
    )
    cmd = [
        'ffmpeg', '-i', input_path,
        '-vf', vf,
        '-t', str(duration),
        '-c:v', 'libx264', '-c:a', 'aac',
        '-y', output_path
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        print("KenBurns error:", result.stderr.decode()[:200], flush=True)
        return trim_clip(input_path, output_path, duration, scene_type)
    return output_path

def add_fade(input_path, output_path, duration, fade_duration=0.4):
    fade_out_start = max(0, duration - fade_duration)
    vf = (
        f"fade=t=in:st=0:d={fade_duration},"
        f"fade=t=out:st={fade_out_start:.2f}:d={fade_duration}"
    )
    cmd = [
        'ffmpeg', '-i', input_path,
        '-vf', vf,
        '-c:v', 'libx264', '-c:a', 'aac',
        '-y', output_path
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        return input_path
    return output_path

def apply_cutting_rules(input_path, output_path, scene_duration, scene_type):
    rules = CUTTING_RULES.get(scene_type, CUTTING_RULES['neutral'])
    cut_duration = rules['clip_duration']
    zoom = rules['zoom']
    num_cuts = max(1, int(scene_duration / cut_duration))
    actual_cut_dur = scene_duration / num_cuts
    print(f"Cutting [{scene_type}] into {num_cuts} x {actual_cut_dur:.1f}s cuts", flush=True)

    if num_cuts <= 1:
        return apply_kenburns(input_path, output_path, scene_duration, zoom, scene_type)

    probe_cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                 '-of', 'default=noprint_wrappers=1:nokey=1', input_path]
    probe = subprocess.run(probe_cmd, capture_output=True, text=True)
    try:
        input_duration = float(probe.stdout.strip())
    except:
        input_duration = scene_duration

    cut_files = []
    job_dir = os.path.dirname(output_path)
    vf = get_base_filter(scene_type)

    for i in range(num_cuts):
        start_time = (i * (input_duration / num_cuts)) % max(input_duration - actual_cut_dur, 0.1)
        cut_path = os.path.join(job_dir, f'cut_{os.path.basename(output_path)}_{i}.mp4')
        if scene_type == 'tense':
            cut_vf = vf + ",scale=iw*1.03:ih*1.03,crop=1280:720"
        else:
            cut_vf = vf
        cut_cmd = [
            'ffmpeg', '-ss', str(start_time), '-i', input_path,
            '-t', str(actual_cut_dur),
            '-vf', cut_vf,
            '-c:v', 'libx264', '-c:a', 'aac', '-y', cut_path
        ]
        result = subprocess.run(cut_cmd, capture_output=True)
        if result.returncode == 0:
            cut_files.append(cut_path)

    if not cut_files:
        return trim_clip(input_path, output_path, scene_duration, scene_type)

    if len(cut_files) == 1:
        os.rename(cut_files[0], output_path)
        return output_path

    list_path = os.path.join(job_dir, f'cuts_list_{os.path.basename(output_path)}.txt')
    with open(list_path, 'w') as f:
        for cf in cut_files:
            f.write(f"file '{cf}'\n")

    concat_cmd = [
        'ffmpeg', '-f', 'concat', '-safe', '0', '-i', list_path,
        '-c:v', 'libx264', '-c:a', 'aac',
        '-t', str(scene_duration), '-y', output_path
    ]
    result = subprocess.run(concat_cmd, capture_output=True)
    if result.returncode != 0:
        return trim_clip(input_path, output_path, scene_duration, scene_type)

    for cf in cut_files:
        try: os.remove(cf)
        except: pass

    return output_path

def create_text_clip(text, duration, output_path, style='timestamp'):
    safe_text = text.replace("'", "").replace('"', '').replace(':', ' ').replace(',', '')[:60]
    if style == 'timestamp':
        vf = (
            f"drawtext=text='{safe_text}':fontcolor=white:fontsize=52"
            f":x=(w-text_w)/2:y=(h-text_h)/2"
            f":alpha='if(lt(t,0.5),t/0.5,if(lt(t,{max(0,duration-0.5):.1f}),1,({duration}-t)/0.5))',"
            f"vignette=PI/4"
        )
    else:
        vf = (
            f"drawtext=text='{safe_text}':fontcolor=white:fontsize=32"
            f":x=(w-text_w)/2:y=(h-text_h)/2"
            f":box=1:boxcolor=black@0.5:boxborderw=10,"
            f"vignette=PI/4"
        )
    cmd = [
        'ffmpeg', '-f', 'lavfi',
        '-i', f'color=c=black:s=1280x720:d={duration}',
        '-vf', vf, '-c:v', 'libx264', '-y', output_path
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        fallback = ['ffmpeg', '-f', 'lavfi', '-i', f'color=c=black:s=1280x720:d={duration}',
                    '-c:v', 'libx264', '-y', output_path]
        subprocess.run(fallback, capture_output=True)
    return output_path

def create_intro(title, output_path, duration=5):
    safe_title = title.replace("'", "").replace('"', '')[:50]
    fade_out = max(0, duration - 1)
    vf = (
        f"drawtext=text='{safe_title}':fontcolor=white:fontsize=60"
        f":x=(w-text_w)/2:y=(h-text_h)/2-30"
        f":alpha='if(lt(t,1.5),t/1.5,if(lt(t,{fade_out}),1,({duration}-t)))',"
        f"drawtext=text='A Documentary':fontcolor=gray:fontsize=24"
        f":x=(w-text_w)/2:y=(h-text_h)/2+40"
        f":alpha='if(lt(t,2),0,if(lt(t,3),(t-2),1))',"
        f"vignette=PI/3"
    )
    cmd = [
        'ffmpeg', '-f', 'lavfi',
        '-i', f'color=c=black:s=1280x720:d={duration}',
        '-vf', vf, '-c:v', 'libx264', '-y', output_path
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        fallback = ['ffmpeg', '-f', 'lavfi', '-i', f'color=c=black:s=1280x720:d={duration}',
                    '-c:v', 'libx264', '-y', output_path]
        subprocess.run(fallback, capture_output=True)
    return output_path

def create_outro(output_path, duration=4):
    cmd = [
        'ffmpeg', '-f', 'lavfi',
        '-i', f'color=c=black:s=1280x720:d={duration}',
        '-c:v', 'libx264', '-y', output_path
    ]
    subprocess.run(cmd, capture_output=True)
    return output_path

def concat_clips(clip_paths, output_path):
    list_path = os.path.join(WORK_DIR, 'concat_list.txt')
    with open(list_path, 'w') as f:
        for clip in clip_paths:
            f.write(f"file '{clip}'\n")
    cmd = [
        'ffmpeg', '-f', 'concat', '-safe', '0', '-i', list_path,
        '-c:v', 'libx264', '-c:a', 'aac',
        '-movflags', '+faststart',
        '-y', output_path
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        print("Concat error:", result.stderr.decode()[:300], flush=True)
    return output_path

@app.route('/health', methods=['GET'])
def health():
    print("Health check", flush=True)
    return jsonify({'status': 'ok', 'message': 'DOC·AI Server running'})

@app.route('/render', methods=['POST', 'OPTIONS'])
def render():
    if request.method == 'OPTIONS':
        return '', 200
    try:
        data = request.get_json()
        job_id = data.get('jobId', str(uuid.uuid4()))
        scenes = data.get('scenes', [])
        title = data.get('title', 'Documentary')
        print(f"Render job {job_id} — {len(scenes)} scenes — {title}", flush=True)

        if not scenes:
            return jsonify({'error': 'No scenes provided'}), 400

        job_dir = os.path.join(WORK_DIR, job_id)
        os.makedirs(job_dir, exist_ok=True)
        all_clips = []

        intro_path = os.path.join(job_dir, '00_intro.mp4')
        create_intro(title, intro_path, duration=5)
        all_clips.append(intro_path)

        for i, scene in enumerate(scenes):
            scene_type = scene.get('type', 'neutral')
            duration = max(3, scene.get('duration', 5))
            footage_url = scene.get('footageUrl')
            timestamp_text = scene.get('timestampText', f'Scene {i+1}')
            order = scene.get('order', i + 1)
            print(f"Scene {order}/{len(scenes)} [{scene_type}] {duration}s", flush=True)

            processed_path = os.path.join(job_dir, f'scene_{str(order).zfill(2)}.mp4')
            faded_path = os.path.join(job_dir, f'faded_{str(order).zfill(2)}.mp4')

            if scene_type == 'timestamp':
                create_text_clip(timestamp_text, duration, processed_path, style='timestamp')
            elif footage_url:
                raw_path = os.path.join(job_dir, f'raw_{str(order).zfill(2)}.mp4')
                download_clip(footage_url, raw_path)
                apply_cutting_rules(raw_path, processed_path, duration, scene_type)
            else:
                narration = scene.get('narrationText', f'Scene {order}')[:60]
                create_text_clip(narration, duration, processed_path, style='placeholder')

            add_fade(processed_path, faded_path, duration, fade_duration=0.4)
            all_clips.append(faded_path if os.path.exists(faded_path) else processed_path)

        outro_path = os.path.join(job_dir, 'outro.mp4')
        create_outro(outro_path, duration=4)
        all_clips.append(outro_path)

        output_path = os.path.join(job_dir, f'documentary_{job_id}.mp4')
        print(f"Concatenating {len(all_clips)} clips...", flush=True)
        concat_clips(all_clips, output_path)
        print(f"Render complete!", flush=True)

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
