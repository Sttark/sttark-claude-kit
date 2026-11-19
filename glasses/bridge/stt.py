"""Speech to text on this Mac, with whisper.cpp (Homebrew `whisper-cpp`) and a local model. Nothing leaves the Mac.

Audio in: raw PCM, 16-bit little-endian, 16 kHz, mono (what the G2 glasses' microphone gives the app).
"""
import os
import shutil
import struct
import subprocess
import tempfile
import threading

MODEL_DIR = os.path.expanduser('~/Library/Application Support/Sttark Kit Glasses/models')
MODEL = os.environ.get('G2_WHISPER_MODEL') or os.path.join(MODEL_DIR, 'ggml-base.en.bin')
MODEL_URL = 'https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin'
RATE = 16000
MAX_SECONDS = 300

_lock = threading.Lock()


class STTUnavailable(Exception):
    pass


def whisper_cli():
    for p in (os.environ.get('G2_WHISPER_CLI'), shutil.which('whisper-cli'), '/opt/homebrew/bin/whisper-cli',
              '/usr/local/bin/whisper-cli'):
        if p and os.access(p, os.X_OK):
            return p
    return None


def status():
    """What is missing, or '' when speech to text is ready."""
    if not whisper_cli():
        return 'whisper.cpp is not installed: brew install whisper-cpp'
    if not os.path.exists(MODEL):
        return f'the speech model is missing: curl -L -o "{MODEL}" {MODEL_URL}'
    return ''


def wav(pcm, rate=RATE):
    """A WAV file's bytes around raw 16-bit mono PCM."""
    n = len(pcm) - len(pcm) % 2
    return (b'RIFF' + struct.pack('<I', 36 + n) + b'WAVE' + b'fmt ' +
            struct.pack('<IHHIIHH', 16, 1, 1, rate, rate * 2, 2, 16) + b'data' + struct.pack('<I', n) + pcm[:n])


def transcribe(pcm, language='en'):
    missing = status()
    if missing:
        raise STTUnavailable(missing)
    if len(pcm) < RATE // 5:  # under 0.1 s: nothing was said
        return ''
    if len(pcm) > RATE * 2 * MAX_SECONDS:
        raise ValueError(f'audio over {MAX_SECONDS} seconds')
    fd, path = tempfile.mkstemp(prefix='g2-stt-', suffix='.wav')
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(wav(pcm))
        with _lock:  # one at a time: it uses the GPU
            r = subprocess.run([whisper_cli(), '-m', MODEL, '-f', path, '-nt', '-np', '-l', language],
                               capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            raise STTUnavailable('whisper-cli failed: ' + (r.stderr or '').strip()[-300:])
        text = ' '.join(line.strip() for line in r.stdout.splitlines() if line.strip())
        # whisper marks silence and noise with [BLANK_AUDIO], (wind blowing) and the like
        for mark in ('[BLANK_AUDIO]', '[ Silence ]', '[silence]', '(silence)'):
            text = text.replace(mark, '')
        return ' '.join(text.split())
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
