from flask import Flask, request, send_file, render_template, jsonify
import yt_dlp
import os
import subprocess
import uuid
import re

app = Flask(__name__)
STATUS_FILE = "status.txt"

def update_status(message):
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        f.write(message)

def trim_video(input_file, start_time, end_time, output_file):
    try:
        update_status("Converting video...")
        subprocess.run([
            'ffmpeg',
            '-ss', start_time,
            '-to', end_time,
            '-i', input_file,
            '-vf', 'scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2',
            '-c:v', 'libx264',
            '-preset', 'fast',
            '-crf', '23',
            '-c:a', 'aac',
            output_file
        ], check=True)
        update_status("Trimming complete...")
    except subprocess.CalledProcessError as e:
        update_status(f"Error during trimming: {e}")
        raise Exception("Error during trimming video.")

def mmss_to_seconds(mmss):
    try:
        parts = mmss.split(':')
        if len(parts) == 2:
            minutes = int(parts[0])
            seconds = int(parts[1])
            return str(minutes * 60 + seconds)
        return mmss
    except Exception as e:
        raise ValueError(f"Invalid time format: {mmss}") from e

def validate_url(url):
    youtube_pattern = r'https?://(www\.)?youtube\.com/watch\?v=[\w-]+'
    if not re.match(youtube_pattern, url):
        raise ValueError("Invalid YouTube URL.")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/status')
def get_status():
    if os.path.exists(STATUS_FILE):
        with open(STATUS_FILE, encoding="utf-8") as f:
            return jsonify({'status': f.read()})
    return jsonify({'status': 'Idle'})

@app.route('/download', methods=['POST'])
def download():
    try:
        data = request.json
        url = data['url']
        mode = data['mode']
        start_time_raw = data.get('start_time', '0:00')
        end_time_raw = data.get('end_time', '0:30')
        include_captions = data.get('include_captions', False)

        # Validate URL format
        validate_url(url)

        update_status("Downloading video...")

        start_time = mmss_to_seconds(start_time_raw)
        end_time = mmss_to_seconds(end_time_raw)

        download_dir = 'downloads'
        os.makedirs(download_dir, exist_ok=True)

        filename_uuid = str(uuid.uuid4())
        output_path = f'{download_dir}/{filename_uuid}.%(ext)s'
        ydl_opts = {
            'format': 'best',
            'writesubtitles': include_captions,
            'subtitleslangs': ['en', 'pt', 'es'],
            'outtmpl': output_path,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                downloaded_file = ydl.prepare_filename(info)
        except yt_dlp.utils.DownloadError as e:
            update_status(f"Error downloading video: {e}")
            return jsonify({'status': 'Error downloading video.'}), 500

        if mode == 'full':
            update_status("✅ Done!")
            return send_file(downloaded_file, as_attachment=True)

        trimmed_file = f'{download_dir}/{filename_uuid}_clip.mp4'
        try:
            trim_video(downloaded_file, start_time, end_time, trimmed_file)
        except Exception as e:
            update_status(f"Error trimming video: {str(e)}")
            return jsonify({'status': 'Error trimming video.'}), 500

        # Optionally burn subtitles if file exists
        if include_captions:
            subtitle_path = downloaded_file.rsplit('.', 1)[0] + ".en.vtt"
            if not os.path.exists(subtitle_path):
                subtitle_path = downloaded_file.rsplit('.', 1)[0] + ".pt.vtt"
            if not os.path.exists(subtitle_path):
                subtitle_path = downloaded_file.rsplit('.', 1)[0] + ".es.vtt"
            if os.path.exists(subtitle_path):
                update_status("Burning subtitles...")
                output_file = f'{download_dir}/{filename_uuid}_final.mp4'
                try:
                    subprocess.run([
                        'ffmpeg', '-y',
                        '-i', trimmed_file,
                        '-vf', f"subtitles={subtitle_path}",
                        '-c:a', 'copy',
                        output_file
                    ], check=True)
                    trimmed_file = output_file
                except subprocess.CalledProcessError as e:
                    update_status(f"Error burning subtitles: {e}")
                    return jsonify({'status': 'Error burning subtitles.'}), 500

        update_status("✅ Done!")
        return send_file(trimmed_file, as_attachment=True)
    
    except ValueError as ve:
        return jsonify({'status': f"Input error: {str(ve)}"}), 400
    except Exception as e:
        update_status(f"Unexpected error: {str(e)}")
        return jsonify({'status': 'Unexpected error occurred.'}), 500

if __name__ == '__main__':
    app.run(debug=True)
