"""
test_media_pipeline.py - Automated tests for VoiceGuard media normalization pipeline.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))


@pytest.fixture(scope="session")
def ffmpeg_exe():
    from backend.audio.preprocessor import _get_ffmpeg_executable
    try:
        exe = _get_ffmpeg_executable()
    except RuntimeError:
        pytest.skip("FFmpeg not available - skipping media tests")
    return exe


def _create_audio(ffmpeg_exe, fmt, extra_args=None):
    fd, path = tempfile.mkstemp(suffix=f".{fmt}")
    os.close(fd)
    cmd = [ffmpeg_exe, "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=2"]
    if extra_args:
        cmd.extend(extra_args)
    cmd.append(path)
    r = subprocess.run(cmd, capture_output=True, timeout=30)
    if r.returncode != 0:
        os.unlink(path)
        pytest.skip(f"Cannot create test {fmt}: {r.stderr.decode()[:200]}")
    return path


def _create_video(ffmpeg_exe, fmt, codec_args, with_audio=True):
    fd, path = tempfile.mkstemp(suffix=f".{fmt}")
    os.close(fd)
    cmd = [ffmpeg_exe, "-y"]
    if with_audio:
        cmd += ["-f", "lavfi", "-i", "sine=frequency=440:duration=3"]
    cmd += ["-f", "lavfi", "-i", "color=c=black:size=320x240:duration=3"]
    cmd += codec_args
    if not with_audio:
        cmd += ["-an"]
    cmd += ["-shortest", path]
    r = subprocess.run(cmd, capture_output=True, timeout=60)
    if r.returncode != 0:
        os.unlink(path)
        pytest.skip(f"Cannot create test {fmt}: {r.stderr.decode()[:200]}")
    return path


class TestNormalizeToMp3:
    def test_mp3_passthrough(self, ffmpeg_exe):
        path = _create_audio(ffmpeg_exe, "mp3", ["-acodec", "libmp3lame"])
        try:
            from backend.audio.preprocessor import normalize_to_mp3
            result = normalize_to_mp3(path)
            assert result == path, "MP3 should not be re-encoded"
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_wav_to_mp3(self, ffmpeg_exe):
        path = _create_audio(ffmpeg_exe, "wav")
        result = None
        try:
            from backend.audio.preprocessor import normalize_to_mp3
            result = normalize_to_mp3(path)
            assert result != path
            assert os.path.exists(result)
            assert os.path.getsize(result) > 0
            assert result.endswith(".mp3")
        finally:
            if os.path.exists(path):
                os.unlink(path)
            if result and result != path and os.path.exists(result):
                os.unlink(result)

    def test_flac_to_mp3(self, ffmpeg_exe):
        path = _create_audio(ffmpeg_exe, "flac", ["-acodec", "flac"])
        result = None
        try:
            from backend.audio.preprocessor import normalize_to_mp3
            result = normalize_to_mp3(path)
            assert result != path
            assert os.path.getsize(result) > 0
        finally:
            if os.path.exists(path):
                os.unlink(path)
            if result and result != path and os.path.exists(result):
                os.unlink(result)

    def test_m4a_to_mp3(self, ffmpeg_exe):
        path = _create_audio(ffmpeg_exe, "m4a", ["-acodec", "aac"])
        result = None
        try:
            from backend.audio.preprocessor import normalize_to_mp3
            result = normalize_to_mp3(path)
            assert result != path
            assert os.path.getsize(result) > 0
        finally:
            if os.path.exists(path):
                os.unlink(path)
            if result and result != path and os.path.exists(result):
                os.unlink(result)

    def test_mp4_audio_extraction(self, ffmpeg_exe):
        path = _create_video(ffmpeg_exe, "mp4", ["-c:v", "libx264", "-c:a", "aac"])
        result = None
        try:
            from backend.audio.preprocessor import normalize_to_mp3
            result = normalize_to_mp3(path)
            assert result != path
            assert os.path.exists(result)
            assert os.path.getsize(result) > 0
            assert result.endswith(".mp3")
        finally:
            if os.path.exists(path):
                os.unlink(path)
            if result and result != path and os.path.exists(result):
                os.unlink(result)

    def test_mkv_audio_extraction(self, ffmpeg_exe):
        path = _create_video(ffmpeg_exe, "mkv", ["-c:v", "libx264", "-c:a", "aac"])
        result = None
        try:
            from backend.audio.preprocessor import normalize_to_mp3
            result = normalize_to_mp3(path)
            assert result != path
            assert os.path.getsize(result) > 0
        finally:
            if os.path.exists(path):
                os.unlink(path)
            if result and result != path and os.path.exists(result):
                os.unlink(result)

    def test_no_audio_video_raises(self, ffmpeg_exe):
        path = _create_video(ffmpeg_exe, "mp4", ["-c:v", "libx264"], with_audio=False)
        try:
            from backend.audio.preprocessor import normalize_to_mp3
            with pytest.raises(ValueError):
                normalize_to_mp3(path)
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_corrupt_file_raises(self, ffmpeg_exe):
        fd, path = tempfile.mkstemp(suffix=".mp4")
        os.close(fd)
        with open(path, "wb") as f:
            f.write(b"THIS IS NOT A VALID MEDIA FILE GARBAGE DATA XYZ123")
        try:
            from backend.audio.preprocessor import normalize_to_mp3
            with pytest.raises(ValueError):
                normalize_to_mp3(path)
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_empty_file_raises(self, ffmpeg_exe):
        fd, path = tempfile.mkstemp(suffix=".mp4")
        os.close(fd)
        try:
            from backend.audio.preprocessor import normalize_to_mp3
            with pytest.raises((ValueError, RuntimeError)):
                normalize_to_mp3(path)
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_output_sample_rate(self, ffmpeg_exe):
        try:
            import soundfile as sf
        except ImportError:
            pytest.skip("soundfile not available")
        path = _create_audio(ffmpeg_exe, "wav")
        result = None
        try:
            from backend.audio.preprocessor import normalize_to_mp3
            result = normalize_to_mp3(path)
            info = sf.info(result)
            assert info.samplerate == 16000, f"Expected 16000 Hz, got {info.samplerate}"
            assert info.channels == 1, f"Expected mono, got {info.channels} channels"
        finally:
            if os.path.exists(path):
                os.unlink(path)
            if result and result != path and os.path.exists(result):
                os.unlink(result)

    def test_cleanup_on_corrupt_input(self, ffmpeg_exe):
        fd, path = tempfile.mkstemp(suffix=".avi")
        os.close(fd)
        with open(path, "wb") as f:
            f.write(b"GARBAGE JUNK DATA NOT A MEDIA FILE")
        tmp_dir = tempfile.gettempdir()
        before_mp3s = set(f for f in os.listdir(tmp_dir) if f.endswith(".mp3"))
        try:
            from backend.audio.preprocessor import normalize_to_mp3
            try:
                normalize_to_mp3(path)
            except (ValueError, RuntimeError):
                pass
        finally:
            if os.path.exists(path):
                os.unlink(path)
        after_mp3s = set(f for f in os.listdir(tmp_dir) if f.endswith(".mp3"))
        leaked = after_mp3s - before_mp3s
        assert not leaked, f"Leaked temp MP3 files: {leaked}"


class TestFFmpegCapability:


    def test_ffmpeg_discovery_finds_binary(self, ffmpeg_exe):
        assert os.path.isfile(ffmpeg_exe), f"Discovered FFmpeg does not exist: {ffmpeg_exe}"


class TestConcurrentUploads:
    def test_concurrent_normalization_isolation(self, ffmpeg_exe):
        from backend.audio.preprocessor import normalize_to_mp3
        paths = [_create_audio(ffmpeg_exe, "wav") for _ in range(3)]
        results = {}
        errors = {}

        def run_normalize(idx, path):
            try:
                results[idx] = normalize_to_mp3(path)
            except Exception as exc:
                errors[idx] = str(exc)

        threads = [threading.Thread(target=run_normalize, args=(i, p)) for i, p in enumerate(paths)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        for p in paths:
            if os.path.exists(p):
                os.unlink(p)
        for r in results.values():
            if r and os.path.exists(r):
                os.unlink(r)

        assert not errors, f"Conversion errors: {errors}"
        assert len(results) == 3
        result_paths = list(results.values())
        assert len(set(result_paths)) == len(result_paths), "Concurrent results share temp files!"
