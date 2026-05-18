import re
import sys
import os
import subprocess
import time
import tempfile
from pathlib import Path

import wave

from funasr_onnx import SenseVoiceSmall
from funasr import AutoModel

# --- config ---
MODEL_DIR = r"C:\Users\bryan\.cache\modelscope\hub\models\iic\SenseVoiceSmall"
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# ffmpeg lives at personal_tools/ffmpeg/, one level up from the script
FFMPEG_DIR = os.path.join(os.path.dirname(_SCRIPT_DIR), "ffmpeg")
if not os.path.isdir(FFMPEG_DIR):
    raise FileNotFoundError(f"ffmpeg not found at {FFMPEG_DIR}")
# --------------


def extract_bvid(url: str) -> str:
    m = re.search(r"(BV[a-zA-Z0-9]+)", url)
    return m.group(1) if m else url


def download_audio(url: str, output_dir: str) -> str:
    """Download audio from Bilibili video, return path to mp3 file."""
    bvid = extract_bvid(url)
    out_template = os.path.join(output_dir, f"{bvid}.%(ext)s")

    ffmpeg_path = os.path.join(FFMPEG_DIR, "ffmpeg.exe")

    cmd = [
        "yt-dlp",
        "-x", "--audio-format", "mp3",
        "--ffmpeg-location", FFMPEG_DIR,
        "-o", out_template,
        "--no-playlist",
        url,
    ]
    print(f"[INFO] 下载音频: {url}")
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        # fallback: download best audio without mp3 conversion
        out_template = os.path.join(output_dir, f"{bvid}.%(ext)s")
        cmd = [
            "yt-dlp",
            "-f", "bestaudio",
            "--ffmpeg-location", FFMPEG_DIR,
            "-o", out_template,
            "--no-playlist",
            url,
        ]
        subprocess.run(cmd, check=True)
        # find the downloaded file
        for f in os.listdir(output_dir):
            if f.startswith(bvid) and not f.endswith(".mp3") and not f.endswith(".wav"):
                m4a_path = os.path.join(output_dir, f)
                wav_path = os.path.join(output_dir, f"{bvid}.wav")
                ffmpeg_exe = os.path.join(FFMPEG_DIR, "ffmpeg.exe")
                subprocess.run(
                    [ffmpeg_exe, "-y", "-i", m4a_path, "-ar", "16000", "-ac", "1", wav_path],
                    check=True,
                )
                os.remove(m4a_path)
                return wav_path

    audio_path = os.path.join(output_dir, f"{bvid}.mp3")
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    # convert mp3 to 16kHz mono wav for ONNX model
    wav_path = os.path.join(output_dir, f"{bvid}.wav")
    ffmpeg_exe = os.path.join(FFMPEG_DIR, "ffmpeg.exe")
    subprocess.run(
        [ffmpeg_exe, "-y", "-i", audio_path, "-ar", "16000", "-ac", "1", wav_path],
        check=True,
    )
    os.remove(audio_path)
    return wav_path


def _get_audio_duration(wav_path: str) -> float:
    with wave.open(wav_path, "r") as wf:
        frames = wf.getnframes()
        rate = wf.getframerate()
        return frames / rate


def transcribe(audio_path: str, output_dir: str) -> str:
    """Transcribe audio, using VAD-split for long audio or ONNX for short."""
    duration = _get_audio_duration(audio_path)
    print(f"[INFO] 音频时长: {duration:.0f}s ({duration/60:.1f}min)")

    if duration < 600:  # under 10 min: use ONNX
        print(f"[INFO] 使用 ONNX 模型 (短音频)")
        t0 = time.time()
        model = SenseVoiceSmall(
            MODEL_DIR, batch_size=1, quantize=True, device="cpu",
        )
        print(f"[INFO] 模型就绪 ({time.time() - t0:.1f}s)")
        t0 = time.time()
        result = model(audio_path, language="zh")
        elapsed = time.time() - t0
        text = result[0] if isinstance(result[0], str) else result[0].get("text", "")
        print(f"[INFO] 转录完成 ({elapsed:.1f}s, {len(text)} chars)")
        return text

    # long audio: use PyTorch AutoModel with VAD
    print(f"[INFO] 使用 PyTorch + VAD 模型 (长音频)")
    t0 = time.time()
    model = AutoModel(
        model=MODEL_DIR,
        vad_model="fsmn-vad",
        vad_kwargs={"max_single_segment_time": 300},
        device="cpu",
        disable_update=True,
    )
    print(f"[INFO] 模型就绪 ({time.time() - t0:.1f}s)")

    t0 = time.time()
    res = model.generate(
        input=audio_path,
        language="zh",
        batch_size_s=300,
        merge_vad=True,
    )
    elapsed = time.time() - t0

    text = res[0]["text"] if res else ""
    print(f"[INFO] 转录完成 ({elapsed:.1f}s, {len(text)} chars)")
    return text


def clean_text(text: str) -> str:
    """Remove SenseVoice special tokens."""
    text = re.sub(r"<\|[^|]+\|>", "", text)
    return text.strip()


def main():
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} <bilibili_video_url>")
        sys.exit(1)

    url = sys.argv[1]
    bvid = extract_bvid(url)
    print(f"[INFO] BV: {bvid}")

    with tempfile.TemporaryDirectory() as tmpdir:
        audio_path = download_audio(url, tmpdir)
        print(f"[INFO] 音频: {os.path.basename(audio_path)} ({os.path.getsize(audio_path)/1024/1024:.1f}MB)")

        text = transcribe(audio_path, tmpdir)
        text = clean_text(text)

        out_file = os.path.join(os.getcwd(), f"{bvid}.txt")
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(text)

        print(f"\n{'='*60}")
        print(text[:500])
        if len(text) > 500:
            print(f"... ({len(text)} chars total)")
        print(f"{'='*60}")
        print(f"[INFO] 已保存到: {out_file}")


if __name__ == "__main__":
    main()
