import sys
import os
import time
import uuid
import subprocess
import requests
from flask import Flask, request, jsonify, send_file, Response
from flask_cors import CORS

print("DOC-AI Server initializing...", flush=True)
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

def download_clip(url, path):
    try:
        r = requests.get(url, stream=True, timeout=10,
            headers={'User-Agent':'Mozilla/5.0','Referer':'https://www.pexels.com/'})
        if r.status_code == 200:
            with open(path, 'wb') as f:
                for chunk in r.iter_content(8192): f.write(chunk)
            if os.path.exists(path) and os.path.getsize(path) > 1000:
                return path
    except Exception as e:
        print(f"DL error: {e}", flush=True)
    return None

def make_video_from_clip(input_path, output_path, duration):
    # FIX 2: -t BEFORE -i to correctly trim duration
    cmd = ['ffmpeg', '-t', str(duration), '-i', input_path,
           '-vf', 'scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2',
           '-c:v', 'libx264', '-preset', 'ultrafast', '-c:a', 'aac',
           '-avoid_negative_ts', 'make_zero', '-y', output_path]
    r = subprocess.run(cmd, capture_output=True, timeout=20)
    return output_path if r.returncode == 0 and os.path.exists(output_path) else None

def make_image_clip(image_url, output_path, duration):
    img = output_path + '.jpg'
    try:
        r = requests.get(image_url, timeout=8, headers={'User-Agent':'Mozilla/5.0'})
        if r.status_code == 200:
            open(img, 'wb').write(r.content)
            frames = int(duration * 25)
            cmd = ['ffmpeg', '-loop', '1', '-t', str(duration), '-i', img,
                   '-vf', f'scale=8000:-1,zoompan=z=\'min(zoom+0.001,1.3)\':d={frames}:x=\'iw/2-(iw/zoom/2)\':y=\'ih/2-(ih/zoom/2)\':s=1280x720:fps=25,setsar=1',
                   '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', '-y', output_path]
            r2 = subprocess.run(cmd, capture_output=True, timeout=25)
            if r2.returncode == 0: return output_path
    except: pass
    return None

def make_text_clip(text, duration, output_path):
    safe = str(text).replace("'","").replace('"','').replace(':','').replace(',','')[:55]
    cmd = ['ffmpeg', '-f', 'lavfi', '-i', f'color=c=black:s=1280x720:d={duration}',
           '-vf', f"drawtext=text='{safe}':fontcolor=white:fontsize=36:x=(w-text_w)/2:y=(h-text_h)/2:box=1:boxcolor=black@0.4:boxborderw=12",
           '-c:v', 'libx264', '-preset', 'ultrafast', '-y', output_path]
    r = subprocess.run(cmd, capture_output=True, timeout=10)
    if r.returncode != 0:
        subprocess.run(['ffmpeg','-f','lavfi','-i',f'color=c=black:s=1280x720:d={duration}',
                       '-c:v','libx264','-preset','ultrafast','-y',output_path], capture_output=True, timeout=8)
    return output_path

def make_timestamp_clip(text, duration, output_path):
    # FIX 7: Special timestamp styling — centered large white text
    safe = str(text).replace("'","").replace('"','').replace(',','')[:60]
    cmd = ['ffmpeg', '-f', 'lavfi', '-i', f'color=c=black:s=1280x720:d={duration}',
           '-vf', f"drawtext=text='{safe}':fontcolor=white:fontsize=48:x=(w-text_w)/2:y=(h-text_h)/2:box=1:boxcolor=black@0.0:boxborderw=20,fade=t=in:st=0:d=0.4,fade=t=out:st={max(0,duration-0.4):.1f}:d=0.4",
           '-c:v', 'libx264', '-preset', 'ultrafast', '-y', output_path]
    r = subprocess.run(cmd, capture_output=True, timeout=10)
    if r.returncode != 0:
        make_text_clip(safe, duration, output_path)
    return output_path

def make_intro(title, output_path):
    safe = title.replace("'","").replace('"','')[:40]
    cmd = ['ffmpeg', '-f', 'lavfi', '-i', 'color=c=black:s=1280x720:d=3',
           '-vf', f"drawtext=text='{safe}':fontcolor=white:fontsize=52:x=(w-text_w)/2:y=(h-text_h)/2-20,drawtext=text='A Documentary':fontcolor=gray:fontsize=22:x=(w-text_w)/2:y=(h-text_h)/2+30",
           '-c:v', 'libx264', '-preset', 'ultrafast', '-y', output_path]
    r = subprocess.run(cmd, capture_output=True, timeout=10)
    if r.returncode != 0:
        subprocess.run(['ffmpeg','-f','lavfi','-i','color=c=black:s=1280x720:d=3',
                       '-c:v','libx264','-preset','ultrafast','-y',output_path], capture_output=True, timeout=8)
    return output_path

def add_music(video_path, output_path, duration):
    music_urls = [
        "https://cdn.pixabay.com/audio/2022/10/16/audio_127819a22a.mp3",
        "https://cdn.pixabay.com/audio/2022/08/23/audio_d16737dc28.mp3",
    ]
    music_path = output_path + '_music.mp3'
    for url in music_urls:
        try:
            r = requests.get(url, timeout=8)
            if r.status_code == 200 and len(r.content) > 5000:
                open(music_path, 'wb').write(r.content)
                cmd = ['ffmpeg', '-i', video_path, '-stream_loop', '-1', '-i', music_path,
                       '-filter_complex', '[1:a]volume=0.10[m];[0:a][m]amix=inputs=2:duration=first[aout]',
                       '-map', '0:v', '-map', '[aout]',
                       '-c:v', 'copy', '-c:a', 'aac',
                       '-t', str(duration), '-y', output_path]
                r2 = subprocess.run(cmd, capture_output=True, timeout=20)
                if r2.returncode == 0: return output_path
        except: continue
    return video_path

def concat_all(clips, output_path):
    valid = [c for c in clips if os.path.exists(c) and os.path.getsize(c) > 100]
    if not valid: return None
    list_path = os.path.join(WORK_DIR, 'list.txt')
    with open(list_path, 'w') as f:
        for c in valid: f.write(f"file '{c}'\n")
    cmd = ['ffmpeg', '-f', 'concat', '-safe', '0', '-i', list_path,
           '-c:v', 'libx264', '-preset', 'ultrafast', '-c:a', 'aac',
           '-movflags', '+faststart', '-y', output_path]
    r = subprocess.run(cmd, capture_output=True, timeout=45)
    return output_path if r.returncode == 0 else None

@app.route('/')
def index():
    p = os.path.join(os.path.dirname(__file__), 'tool.html')
    return Response(open(p).read(), mimetype='text/html')

@app.route('/health')
def health():
    return jsonify({'status':'ok','message':'DOC-AI Server running'})

@app.route('/rss')
def rss_proxy():
    url = request.args.get('url','')
    if not url: return jsonify({'error':'No URL'}), 400
    try:
        r = requests.get(url, timeout=10, headers={'User-Agent':'Mozilla/5.0 DocAI/1.0'})
        return Response(r.content, mimetype='application/xml',
                       headers={'Access-Control-Allow-Origin':'*'})
    except Exception as e:
        return jsonify({'error':str(e)}), 500

@app.route('/render', methods=['POST','OPTIONS'])
def render():
    if request.method == 'OPTIONS': return '',200
    try:
        data = request.get_json()
        job_id = data.get('jobId', str(uuid.uuid4()))
        scenes = data.get('scenes', [])
        title = data.get('title', 'Documentary')

        # FIX 6: Limit to 20 scenes but process FAST
        if len(scenes) > 20:
            print(f"Trimming {len(scenes)} to 20 scenes", flush=True)
            scenes = scenes[:20]

        print(f"RENDER {job_id[:8]} - {len(scenes)} scenes", flush=True)
        if not scenes: return jsonify({'error':'No scenes'}), 400

        job_dir = os.path.join(WORK_DIR, job_id)
        os.makedirs(job_dir, exist_ok=True)
        clips = []
        total_dur = 3

        # INTRO
        intro = os.path.join(job_dir, '00_intro.mp4')
        make_intro(title, intro)
        if os.path.exists(intro): clips.append(intro)

        # SCENES
        for i, scene in enumerate(scenes):
            stype = scene.get('type', 'neutral')
            # FIX 2: Use exact duration from scene
            dur = max(2, min(int(scene.get('duration', 4)), 12))
            url = scene.get('footageUrl')
            img_url = scene.get('imageUrl')
            ts_text = scene.get('timestampText', '')
            narr = scene.get('narrationText', f'Scene {i+1}')
            overlay = scene.get('overlay')
            order = i + 1  # FIX 4: Always sequential

            print(f"S{order}/{len(scenes)} [{stype}] {dur}s url={'Y' if url else 'N'}", flush=True)
            out = os.path.join(job_dir, f's{str(order).zfill(2)}.mp4')

            # FIX 7: Timestamp scenes get special treatment
            if stype == 'timestamp':
                make_timestamp_clip(ts_text or narr, dur, out)

            elif url:
                raw = os.path.join(job_dir, f'r{str(order).zfill(2)}.mp4')
                dl = download_clip(url, raw)
                if dl:
                    result = make_video_from_clip(raw, out, dur)
                    if not result:
                        make_text_clip(narr[:50], dur, out)
                else:
                    make_text_clip(narr[:50], dur, out)

            elif img_url:
                result = make_image_clip(img_url, out, dur)
                if not result:
                    make_text_clip(overlay or narr[:50], dur, out)

            elif overlay:
                make_text_clip(overlay[:60], dur, out)

            else:
                make_text_clip(narr[:50], dur, out)

            if os.path.exists(out) and os.path.getsize(out) > 100:
                clips.append(out)
                total_dur += dur
                print(f"S{order} OK ({dur}s)", flush=True)
            else:
                # Emergency fallback
                make_text_clip(f'Scene {order}', dur, out)
                if os.path.exists(out):
                    clips.append(out)
                    total_dur += dur

        # OUTRO
        outro = os.path.join(job_dir, 'outro.mp4')
        make_text_clip('', 2, outro)
        if os.path.exists(outro):
            clips.append(outro)
            total_dur += 2

        # CONCAT
        raw_out = os.path.join(job_dir, f'raw_{job_id[:8]}.mp4')
        result = concat_all(clips, raw_out)
        if not result:
            return jsonify({'error':'Concat failed'}), 500

        # MUSIC
        final_out = os.path.join(job_dir, f'final_{job_id[:8]}.mp4')
        output_path = add_music(raw_out, final_out, total_dur)
        if not os.path.exists(output_path):
            output_path = raw_out

        mb = os.path.getsize(output_path)/1024/1024
        print(f"DONE {mb:.1f}MB {total_dur}s", flush=True)

        return send_file(output_path, mimetype='video/mp4', as_attachment=True,
                        download_name=f'documentary_{job_id[:8]}.mp4')
    except Exception as e:
        print(f"ERROR: {e}", flush=True)
        return jsonify({'error':str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    print(f"Port {port}", flush=True)
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
