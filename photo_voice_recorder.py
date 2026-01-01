import json
import os
import re
import shutil
import subprocess
import threading
import queue
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import sounddevice as sd
import soundfile as sf
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QMessageBox,
    QCheckBox,
    QComboBox,
    QFileDialog,
)

STATE_PATH = Path.home() / "PhotoVoiceNotes" / "current_state.json"
RECORDER_STATUS_PATH = STATE_PATH.parent / "recorder_status.json"
ARCHIVE_ROOT = Path(__file__).resolve().parent
VOICE_SESSIONS_ROOT = ARCHIVE_ROOT / "02_WORKING_BUCKETS" / "voice_sessions"
OUT_BASE = VOICE_SESSIONS_ROOT / "recordings"
TRANSCRIPTS_ROOT = VOICE_SESSIONS_ROOT / "transcripts"

SAMPLE_RATE = 48_000
CHANNELS = 1
SUBTYPE = "PCM_16"
DEFAULT_WHISPER_MODEL = os.environ.get("VOICE_WHISPER_MODEL", "base")

try:
    import whisper  # type: ignore
except ImportError:  # pragma: no cover
    whisper = None

try:
    from apple_speech import AppleSpeechRecognizer
except Exception:  # pragma: no cover
    AppleSpeechRecognizer = None


def safe_name(value: str, max_len: int = 140) -> str:
    filtered = re.sub(r"[^\w\-\.@:]+", "_", value.strip())
    return filtered[:max_len] if len(filtered) > max_len else filtered


def write_recorder_status(payload: Dict[str, object]) -> None:
    RECORDER_STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2)
    temp_path = RECORDER_STATUS_PATH.with_suffix(".tmp")
    temp_path.write_text(encoded, encoding="utf-8")
    os.replace(temp_path, RECORDER_STATUS_PATH)


@dataclass
class Snapshot:
    bucketId: str
    imageId: str
    variant: Optional[str] = None
    path: Optional[str] = None
    timestamp: Optional[float] = None
    sessionId: Optional[str] = None
    noteFlag: bool = False

    @staticmethod
    def from_dict(payload: dict) -> "Snapshot":
        return Snapshot(
            bucketId=str(payload.get("bucketId", "")),
            imageId=str(payload.get("imageId", "")),
            variant=payload.get("variant"),
            path=payload.get("path"),
            timestamp=payload.get("timestamp"),
            sessionId=payload.get("sessionId"),
            noteFlag=bool(payload.get("noteFlag", False)),
        )

    def key(self) -> str:
        session = self.sessionId or ""
        return f"{session}::{self.bucketId}::{self.imageId}"


@dataclass
class TranscriptionTask:
    kind: str
    speaker: str
    session_dir: Optional[Path] = None
    audio_path: Optional[Path] = None


_WHISPER_MODEL_LOCK = threading.Lock()
_WHISPER_MODEL_CACHE: Dict[str, object] = {}


def get_whisper_model() -> object:
    if whisper is None:
        raise RuntimeError("Whisper is not available.")
    with _WHISPER_MODEL_LOCK:
        cached = _WHISPER_MODEL_CACHE.get("model")
        cached_name = _WHISPER_MODEL_CACHE.get("name")
        if cached is not None and cached_name == DEFAULT_WHISPER_MODEL:
            return cached
        model = whisper.load_model(DEFAULT_WHISPER_MODEL)
        _WHISPER_MODEL_CACHE["model"] = model
        _WHISPER_MODEL_CACHE["name"] = DEFAULT_WHISPER_MODEL
        return model


def load_clip_meta(audio_path: Path) -> Optional[dict]:
    meta_path = audio_path.with_suffix(".json")
    if not meta_path.exists():
        return None
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_transcript_file(audio_path: Path, text: str) -> None:
    if not text:
        return
    txt_path = audio_path.with_suffix(".txt")
    try:
        txt_path.write_text(text.strip() + "\n", encoding="utf-8")
    except OSError:
        pass


def transcribe_clip(audio_path: Path, speaker: str) -> bool:
    if not audio_path.exists():
        return False
    meta = load_clip_meta(audio_path)
    if not meta or not meta.get("bucketId"):
        return False
    model = get_whisper_model()
    try:
        result = model.transcribe(str(audio_path), fp16=False)
    except Exception:  # pragma: no cover
        return False
    text = (result.get("text") or "").strip()
    if not text:
        return False
    bucket_prefix = str(meta["bucketId"])
    image_id = meta.get("imageId") or ""
    transcripts = {bucket_prefix: [(image_id, text)]}
    apply_voice_transcripts(transcripts, speaker, meta.get("sessionId"))
    write_transcript_file(audio_path, text)
    return True


class AudioSession:
    def __init__(self) -> None:
        self.stream: Optional[sd.InputStream] = None
        self.sndfile: Optional[sf.SoundFile] = None
        self.mode = "segmented"
        self.subject = "me"
        self.session_dir: Optional[Path] = None
        self.last_session_dir: Optional[Path] = None
        self.session_start_monotonic: Optional[float] = None
        self.markers_fp = None
        self.current_snapshot: Optional[Snapshot] = None
        self.recording = False
        self.audio_profile: Dict[str, object] = {"codec": "aac", "bitrate": 128000}
        self.current_clip_path: Optional[Path] = None
        self.device_index: Optional[int] = None

    def start(
        self,
        mode: str,
        subject: str,
        initial_snapshot: Optional[Snapshot],
        audio_profile: Optional[Dict[str, object]] = None,
        device_index: Optional[int] = None,
    ) -> None:
        if self.recording:
            return
        self.mode = mode
        self.subject = subject or "me"
        self.audio_profile = audio_profile or {"codec": "aac", "bitrate": 128000}
        self.device_index = device_index
        session_ts = time.strftime("%Y%m%d_%H%M%S")
        session_name = f"{safe_name(self.subject)}_{session_ts}"
        self.session_dir = OUT_BASE / mode / session_name
        self.session_dir.mkdir(parents=True, exist_ok=True)
        meta = {
            "created_epoch": time.time(),
            "mode": self.mode,
            "subject": self.subject,
            "uiSessionId": initial_snapshot.sessionId if initial_snapshot else None,
            "audio_profile": self.audio_profile,
        }
        (self.session_dir / "session_meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.session_start_monotonic = time.monotonic()
        if self.mode == "continuous":
            markers_path = self.session_dir / "markers.jsonl"
            self.markers_fp = open(markers_path, "a", encoding="utf-8")
        self.current_snapshot = initial_snapshot
        self._open_file_for_snapshot(initial_snapshot)
        self.stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="float32",
            callback=self._on_audio,
            blocksize=0,
            device=self.device_index,
        )
        self.stream.start()
        self.recording = True
        if self.mode == "continuous" and initial_snapshot:
            self._write_marker(initial_snapshot)

    def stop(self) -> Tuple[Optional[Path], Optional[Path]]:
        if not self.recording:
            return None, None
        session_dir = self.session_dir
        try:
            if self.stream:
                self.stream.stop()
                self.stream.close()
        finally:
            self.stream = None
        final_clip = self._close_current_file()
        if self.markers_fp:
            self.markers_fp.flush()
            self.markers_fp.close()
            self.markers_fp = None
        self.recording = False
        self.current_snapshot = None
        self.last_session_dir = session_dir
        self.session_dir = None
        self.session_start_monotonic = None
        self.device_index = None
        return session_dir, final_clip

    def on_state_change(self, snapshot: Snapshot) -> Optional[Path]:
        if not snapshot.bucketId or not snapshot.imageId:
            return None
        if not self.recording:
            self.current_snapshot = snapshot
            return None
        if self.current_snapshot and snapshot.key() == self.current_snapshot.key():
            if self.mode == "continuous" and snapshot.noteFlag:
                self._write_marker(snapshot)
            return None
        self.current_snapshot = snapshot
        if self.mode == "segmented":
            finished = self._close_current_file()
            self._open_file_for_snapshot(snapshot)
            return finished
        else:
            self._write_marker(snapshot)
        return None

    def _elapsed_ms(self) -> int:
        if self.session_start_monotonic is None:
            return 0
        return int((time.monotonic() - self.session_start_monotonic) * 1000)

    def _write_marker(self, snapshot: Snapshot) -> None:
        if not self.markers_fp:
            return
        record = {
            "ms": self._elapsed_ms(),
            "sessionId": snapshot.sessionId,
            "bucketId": snapshot.bucketId,
            "imageId": snapshot.imageId,
            "variant": snapshot.variant,
            "path": snapshot.path,
            "noteFlag": bool(snapshot.noteFlag),
        }
        self.markers_fp.write(json.dumps(record, ensure_ascii=False) + "\n")
        self.markers_fp.flush()

    def _open_file_for_snapshot(self, snapshot: Optional[Snapshot]) -> None:
        if self.mode == "continuous":
            wav_path = self.session_dir / "session.wav"
            self.sndfile = sf.SoundFile(
                wav_path,
                mode="w",
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                subtype=SUBTYPE,
            )
            self.current_clip_path = wav_path
            return
        bucket = safe_name(snapshot.bucketId) if snapshot else "NO_BUCKET"
        image = safe_name(snapshot.imageId) if snapshot else "NO_IMAGE"
        ts = time.strftime("%Y%m%d_%H%M%S")
        outdir = self.session_dir / bucket / image
        outdir.mkdir(parents=True, exist_ok=True)
        wav_path = outdir / f"{ts}.wav"
        meta = {
            "bucketId": snapshot.bucketId if snapshot else None,
            "imageId": snapshot.imageId if snapshot else None,
            "variant": snapshot.variant if snapshot else None,
            "path": snapshot.path if snapshot else None,
            "sessionId": snapshot.sessionId if snapshot else None,
            "noteFlag": bool(snapshot.noteFlag) if snapshot else False,
            "started_epoch": time.time(),
        }
        (outdir / f"{ts}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        if snapshot and snapshot.noteFlag:
            (outdir / f"{ts}_FLAG.txt").write_text("noteFlag=true\n", encoding="utf-8")
        self.sndfile = sf.SoundFile(
            wav_path,
            mode="w",
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            subtype=SUBTYPE,
        )
        self.current_clip_path = wav_path

    def _close_current_file(self) -> Optional[Path]:
        if self.sndfile:
            self.sndfile.flush()
            self.sndfile.close()
            self.sndfile = None
            finished = self.current_clip_path
            self.current_clip_path = None
            if finished:
                return self._process_finished_clip(finished)
        return None

    def _on_audio(self, indata, frames, time_info, status) -> None:
        if status:
            # status is informational; ignore for now
            pass
        if not self.sndfile:
            return
        self.sndfile.write(indata.copy())

    def _process_finished_clip(self, wav_path: Path) -> Optional[Path]:
        profile = self.audio_profile or {}
        codec = str(profile.get("codec") or "aac").lower()
        if codec not in {"aac", "alac"}:
            return wav_path
        if shutil.which("afconvert") is None:
            return wav_path
        target = wav_path.with_suffix(".m4a")
        cmd = ["afconvert", "-f", "m4af"]
        if codec == "aac":
            bitrate = int(profile.get("bitrate") or 128000)
            cmd.extend(["-d", "aac", "-b", str(bitrate)])
        else:
            cmd.extend(["-d", "alac"])
        cmd.extend([str(wav_path), str(target)])
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            wav_path.unlink(missing_ok=True)
            return target
        except subprocess.CalledProcessError:
            return wav_path


class RecorderUI(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Photo Voice Recorder")
        self.bucket_label = QLabel("NO BUCKET")
        self.bucket_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.bucket_label.setStyleSheet("font-size: 16px; font-weight: bold; padding: 4px; color: #555;")
        self.state_label = QLabel("State: (waiting)")
        self.state_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.subject = QLineEdit("me")
        self.subject.setPlaceholderText("speaker tag (e.g., mom/dad/me)")
        self.btn_start = QPushButton("Record")
        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setEnabled(False)
        self.chk_segmented = QCheckBox("Segmented")
        self.chk_segmented.setChecked(True)
        self.chk_continuous = QCheckBox("Continuous")
        self.chk_auto_start = QCheckBox("Auto-start on first snapshot")
        self.chk_live_dictation = QCheckBox("Apple live dictation")
        self.chk_whisper_photo = QCheckBox("Whisper per-photo")
        self.chk_whisper_session = QCheckBox("Whisper full-session")
        self.chk_whisper_session.setChecked(True)
        self.audio_format_box = QComboBox()
        self.audio_format_box.addItems(["AAC 128 kbps (m4a)", "Apple Lossless (m4a)"])
        self.mic_box = QComboBox()
        self.mic_info_label = QLabel("Mic: System default")
        self.mic_info_label.setMinimumWidth(220)
        self._mic_devices: Dict[int, dict] = {}
        self._mic_signature: Optional[Tuple[Optional[int], Tuple[Tuple[int, str, int, int], ...]]] = None
        self._mic_initialized = False
        self._populate_mic_choices()
        self.mic_box.currentIndexChanged.connect(self._refresh_mic_label)
        self.mic_refresh_timer = QTimer()
        self.mic_refresh_timer.setInterval(3000)
        self.mic_refresh_timer.timeout.connect(self._refresh_mic_choices)
        self.mic_refresh_timer.start()
        self.status_indicator = QLabel("IDLE")
        self.status_indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._update_indicator(False)
        self.btn_transcribe_old = QPushButton("Transcribe Older Session…")

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Modes:"))
        mode_row.addWidget(self.chk_segmented)
        mode_row.addWidget(self.chk_continuous)
        mode_row.addStretch()

        controls_row = QHBoxLayout()
        controls_row.addWidget(QLabel("Speaker:"))
        controls_row.addWidget(self.subject)
        controls_row.addWidget(QLabel("Audio:"))
        controls_row.addWidget(self.audio_format_box)
        controls_row.addWidget(QLabel("Mic:"))
        controls_row.addWidget(self.mic_box)
        controls_row.addWidget(self.mic_info_label)
        controls_row.addWidget(self.status_indicator)
        controls_row.addWidget(self.btn_start)
        controls_row.addWidget(self.btn_stop)

        manage_row = QHBoxLayout()
        manage_row.addWidget(self.chk_auto_start)
        manage_row.addStretch()
        manage_row.addWidget(self.btn_transcribe_old)

        transcribe_row = QHBoxLayout()
        transcribe_row.addWidget(QLabel("Transcription:"))
        transcribe_row.addWidget(self.chk_live_dictation)
        transcribe_row.addWidget(self.chk_whisper_photo)
        transcribe_row.addWidget(self.chk_whisper_session)
        transcribe_row.addStretch()

        layout = QVBoxLayout()
        layout.addLayout(mode_row)
        layout.addLayout(controls_row)
        layout.addLayout(manage_row)
        layout.addLayout(transcribe_row)
        layout.addWidget(self.bucket_label)
        layout.addWidget(self.state_label)
        self.live_dictation_label = QLabel("Live dictation: (disabled)")
        self.live_dictation_label.setWordWrap(True)
        self.live_dictation_label.setStyleSheet("color: #444; font-size: 12px;")
        layout.addWidget(self.live_dictation_label)
        self.setLayout(layout)
        self.sessions = {mode: AudioSession() for mode in ("segmented", "continuous")}
        self.recording_modes: set[str] = set()
        self.last_state_mtime = 0.0
        self.last_snapshot: Optional[Snapshot] = None
        self.timer = QTimer()
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.poll_state_file)
        self.timer.start()
        self.btn_start.clicked.connect(self.start_recording)
        self.btn_stop.clicked.connect(self.stop_recording)
        self.btn_transcribe_old.clicked.connect(self.transcribe_existing_session)
        self.chk_live_dictation.toggled.connect(self._sync_live_dictation)
        self._emit_recorder_state()

        self.transcription_queue = queue.Queue()
        self.transcription_thread = threading.Thread(target=self._transcription_worker, daemon=True)
        self.transcription_thread.start()

        self.apple_dictation = AppleSpeechRecognizer() if AppleSpeechRecognizer else None
        self._dictation_starting = False
        if self.apple_dictation is None:
            self.chk_live_dictation.setEnabled(False)
            self.live_dictation_label.setText("Live dictation: unavailable (Speech framework missing)")

        self.dictation_timer = QTimer()
        self.dictation_timer.setInterval(200)
        self.dictation_timer.timeout.connect(self._refresh_live_dictation)
        self.dictation_timer.start()

    def _transcription_worker(self) -> None:
        while True:
            task = self.transcription_queue.get()
            if task is None:
                self.transcription_queue.task_done()
                break
            try:
                if task.kind == "session":
                    self._run_session_transcription(task)
                elif task.kind == "clip":
                    self._run_clip_transcription(task)
            except Exception as exc:
                print(f"Worker loop error: {exc}")
            finally:
                self.transcription_queue.task_done()

    def _queue_session_transcription(self, session_dir: Path, speaker: str) -> None:
        self.transcription_queue.put(
            TranscriptionTask(kind="session", session_dir=session_dir, speaker=speaker)
        )

    def _queue_clip_transcription(self, audio_path: Path, speaker: str) -> None:
        self.transcription_queue.put(
            TranscriptionTask(kind="clip", audio_path=audio_path, speaker=speaker)
        )

    def _run_session_transcription(self, task: TranscriptionTask) -> None:
        session_dir = task.session_dir
        if not session_dir or not session_dir.exists():
            return
        if whisper is None:
            print("Whisper unavailable; skipping session transcription.")
            return
        try:
            transcriber = SessionTranscriber(session_dir, task.speaker)
            transcriber.run()
        except Exception as exc:
            print(f"Transcription error for {session_dir}: {exc}")

    def _run_clip_transcription(self, task: TranscriptionTask) -> None:
        audio_path = task.audio_path
        if not audio_path or not audio_path.exists():
            return
        if whisper is None:
            print("Whisper unavailable; skipping clip transcription.")
            return
        try:
            transcribe_clip(audio_path, task.speaker)
        except Exception as exc:
            print(f"Clip transcription error for {audio_path}: {exc}")

    def _sync_live_dictation(self) -> None:
        if self.apple_dictation is None:
            return
        if not self.chk_live_dictation.isChecked():
            self._stop_live_dictation()
            return
        if self.recording_modes:
            self._start_live_dictation()
        else:
            self._stop_live_dictation()

    def _start_live_dictation(self) -> None:
        if self.apple_dictation is None or self.apple_dictation.is_running():
            return
        if self._dictation_starting:
            return
        self._dictation_starting = True

        def runner() -> None:
            try:
                self.apple_dictation.clear_error()
                self.apple_dictation.start()
            finally:
                self._dictation_starting = False

        threading.Thread(target=runner, daemon=True).start()

    def _stop_live_dictation(self) -> None:
        if self.apple_dictation is None:
            return
        if self.apple_dictation.is_running():
            self.apple_dictation.stop()

    def _refresh_live_dictation(self) -> None:
        if self.apple_dictation is None:
            return
        if not self.chk_live_dictation.isChecked():
            self.live_dictation_label.setText("Live dictation: (disabled)")
            return
        if not self.recording_modes:
            self.live_dictation_label.setText("Live dictation: ready (start recording)")
            return
        error = self.apple_dictation.get_error()
        if error:
            self.live_dictation_label.setText(f"Live dictation: {error}")
            return
        text = self.apple_dictation.get_text()
        if text:
            self.live_dictation_label.setText(f"Live dictation: {text}")
        else:
            self.live_dictation_label.setText("Live dictation: listening...")

    def poll_state_file(self) -> None:
        try:
            stat = STATE_PATH.stat()
        except FileNotFoundError:
            self.state_label.setText(f"State: waiting for {STATE_PATH}")
            return
        if stat.st_mtime <= self.last_state_mtime:
            return
        self.last_state_mtime = stat.st_mtime
        try:
            payload = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            snapshot = Snapshot.from_dict(payload)
        except Exception as exc:
            self.state_label.setText(f"State: invalid JSON ({exc})")
            return
        if not snapshot.bucketId or not snapshot.imageId:
            self.state_label.setText("State: no active bucket")
            self.bucket_label.setText("NO BUCKET")
            self.bucket_label.setStyleSheet("font-size: 16px; font-weight: bold; padding: 4px; color: #555;")
            return

        hue = sum(ord(c) for c in snapshot.bucketId) % 360
        # HSL(hue, 70%, 80%) approx HSL(hue, 178, 204) in Qt (0-255 range)
        self.bucket_label.setText(snapshot.bucketId)
        self.bucket_label.setStyleSheet(
            f"font-size: 24px; font-weight: bold; padding: 10px; border-radius: 6px; "
            f"background-color: hsl({hue}, 178, 204); color: #222;"
        )

        flag_note = "  [FLAG]" if snapshot.noteFlag else ""
        session_line = snapshot.sessionId or "(no sessionId)"
        self.state_label.setText(
            f"Session: {session_line}{flag_note}\n"
            f"State: {snapshot.bucketId} · {snapshot.imageId} ({snapshot.path or ''})"
        )
        self.last_snapshot = snapshot
        speaker = self.subject.text().strip() or "me"
        for mode, session in self.sessions.items():
            finished_clip = session.on_state_change(snapshot)
            if (
                finished_clip
                and mode == "segmented"
                and self.chk_whisper_photo.isChecked()
            ):
                self._queue_clip_transcription(finished_clip, speaker)
        if (
            self.chk_auto_start.isChecked()
            and not self.recording_modes
            and snapshot.bucketId
            and snapshot.imageId
        ):
            self.start_recording(auto_trigger=True)
        if self.recording_modes:
            self._emit_recorder_state()

    def start_recording(self, auto_trigger: bool = False) -> None:
        if self.recording_modes:
            return
        selected = self._selected_modes()
        if not selected:
            QMessageBox.warning(self, "Select a mode", "Enable at least one mode (segmented or continuous).")
            return
        subject = self.subject.text().strip() or "me"
        profile = self._current_audio_profile()
        device_index = self._selected_device_index()
        try:
            for mode in selected:
                self.sessions[mode].start(
                    mode=mode,
                    subject=subject,
                    initial_snapshot=self.last_snapshot,
                    audio_profile=profile,
                    device_index=device_index,
                )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Recording failed",
                f"{exc}\n\nIf macOS blocks audio input, enable microphone access for Terminal / this app.",
            )
            return
        self.recording_modes = selected
        self._update_indicator(True)
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self._emit_recorder_state()
        self._sync_live_dictation()
        if auto_trigger:
            self.state_label.setText(self.state_label.text() + "\n(Auto-started)")

    def stop_recording(self) -> None:
        completed: List[Tuple[str, Optional[Path], Optional[Path]]] = []
        for mode in list(self.recording_modes):
            session_dir, last_clip = self.sessions[mode].stop()
            completed.append((mode, session_dir, last_clip))
        self.recording_modes.clear()
        self._update_indicator(False)
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self._emit_recorder_state()
        self._stop_live_dictation()
        speaker = self.subject.text().strip() or "me"
        for mode, session_dir, last_clip in completed:
            if mode != "segmented":
                continue
            if self.chk_whisper_photo.isChecked() and last_clip:
                self._queue_clip_transcription(last_clip, speaker)
            if self.chk_whisper_session.isChecked() and session_dir:
                self._queue_session_transcription(session_dir, speaker)

    def _selected_modes(self) -> set[str]:
        modes: set[str] = set()
        if self.chk_segmented.isChecked():
            modes.add("segmented")
        if self.chk_continuous.isChecked():
            modes.add("continuous")
        return modes

    def _current_audio_profile(self) -> Dict[str, object]:
        option = getattr(self, "audio_format_box", None)
        if option:
            text = option.currentText().lower()
            if "lossless" in text:
                return {"codec": "alac"}
        return {"codec": "aac", "bitrate": 128000}

    def _update_indicator(self, armed: bool) -> None:
        if armed:
            self.status_indicator.setText("ARMED")
            self.status_indicator.setStyleSheet("background:#b71c1c;color:#fff;padding:0.3rem 0.6rem;")
        else:
            self.status_indicator.setText("IDLE")
            self.status_indicator.setStyleSheet("background:#555;color:#eee;padding:0.3rem 0.6rem;")

    def transcribe_existing_session(self) -> None:
        base = (OUT_BASE / "segmented").expanduser()
        legacy = Path.home() / "PhotoVoiceNotes" / "recordings" / "segmented"
        if not base.exists() and legacy.exists():
            base = legacy
        base.mkdir(parents=True, exist_ok=True)
        selected = QFileDialog.getExistingDirectory(
            self,
            "Select segmented session to transcribe",
            str(base),
            QFileDialog.Option.ShowDirsOnly,
        )
        if not selected:
            return
        session_path = Path(selected)
        if not session_path.exists():
            QMessageBox.warning(self, "Not found", f"{session_path} does not exist.")
            return
        speaker = self.subject.text().strip() or "me"
        self._transcribe_session(session_path, speaker, confirm=False)

    def _maybe_transcribe_session(self, session_dir: Path, speaker: str) -> None:
        if session_dir is None:
            return
        if not session_dir.exists():
            return
        self._transcribe_session(session_dir, speaker, confirm=True)

    def _transcribe_session(self, session_dir: Path, speaker: str, confirm: bool) -> None:
        if whisper is None:
            QMessageBox.information(
                self,
                "Whisper unavailable",
                "Install openai-whisper (pip install openai-whisper) to enable automatic transcription.",
            )
            return
        if not session_dir.exists():
            return
        if confirm:
            decision = QMessageBox.question(
                self,
                "Transcribe session?",
                f"Transcribe audio in {session_dir.name} with Whisper and attach transcripts to bucket notes?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if decision != QMessageBox.StandardButton.Yes:
                return
        QApplication.setOverrideCursor(Qt.CursorShape.BusyCursor)
        try:
            transcriber = SessionTranscriber(session_dir, speaker)
            summary = transcriber.run()
        except Exception as exc:  # pragma: no cover
            QMessageBox.critical(self, "Transcription failed", str(exc))
            summary = ""
        finally:
            QApplication.restoreOverrideCursor()
        if summary:
            QMessageBox.information(self, "Transcription complete", summary)

    def _selected_device_index(self) -> Optional[int]:
        if not hasattr(self, "mic_box"):
            return None
        data = self.mic_box.currentData()
        return int(data) if isinstance(data, int) and data >= 0 else None

    def _default_input_device(self) -> Optional[int]:
        try:
            default_device = sd.default.device
        except Exception:
            return None
        if isinstance(default_device, (list, tuple)):
            return default_device[0] if default_device else None
        if isinstance(default_device, int):
            return default_device
        return None

    def _populate_mic_choices(self) -> None:
        self._mic_initialized = False
        self._refresh_mic_choices(force=True)

    def _mic_device_signature(self, devices: List[dict]) -> Tuple[Optional[int], Tuple[Tuple[int, str, int, int], ...]]:
        default_index = self._default_input_device()
        inputs: List[Tuple[int, str, int, int]] = []
        for idx, device in enumerate(devices):
            if device.get("max_input_channels", 0) <= 0:
                continue
            name = device.get("name") or ""
            channels = int(device.get("max_input_channels") or 0)
            samplerate = int(device.get("default_samplerate") or 0)
            inputs.append((idx, name, channels, samplerate))
        return default_index, tuple(inputs)

    def _refresh_mic_choices(self, force: bool = False) -> None:
        try:
            devices = sd.query_devices()
        except Exception:
            if force:
                self.mic_info_label.setText("Mic: system default (enumeration failed)")
            return
        signature = self._mic_device_signature(devices)
        if not force and signature == self._mic_signature:
            return
        self._mic_signature = signature
        previous_selection = self._selected_device_index()
        preferred_index = previous_selection
        if previous_selection is None and not self._mic_initialized:
            preferred_index = signature[0]
        self._mic_devices = {}
        self.mic_box.blockSignals(True)
        self.mic_box.clear()
        self.mic_box.addItem("System default", None)
        selected_combo_index = 0
        for idx, device in enumerate(devices):
            if device.get("max_input_channels", 0) <= 0:
                continue
            label = device.get("name") or f"Device {idx}"
            display = f"{label} (#{idx})"
            self.mic_box.addItem(display, idx)
            self._mic_devices[idx] = device
            if preferred_index is not None and idx == preferred_index:
                selected_combo_index = self.mic_box.count() - 1
        if preferred_index is not None and preferred_index not in self._mic_devices:
            selected_combo_index = 0
        self.mic_box.setCurrentIndex(selected_combo_index)
        self.mic_box.blockSignals(False)
        self._mic_initialized = True
        self._refresh_mic_label()

    def _refresh_mic_label(self) -> None:
        idx = self._selected_device_index()
        if idx is None:
            default_idx = self._default_input_device()
            device = None
            if default_idx is not None:
                device = self._mic_devices.get(default_idx)
                if not device:
                    try:
                        device = sd.query_devices(default_idx)
                    except Exception:
                        device = None
            if device:
                label = device.get("name") or f"Device #{default_idx}"
                channels = device.get("max_input_channels") or 0
                samplerate = device.get("default_samplerate")
                parts = [label, f"#{default_idx}"]
                if channels:
                    parts.append(f"{channels}ch")
                if samplerate:
                    parts.append(f"{int(samplerate)} Hz")
                parts.append("system default")
                self.mic_info_label.setText("Mic: " + " · ".join(parts))
            else:
                self.mic_info_label.setText("Mic: system default input")
            return
        device = self._mic_devices.get(idx)
        if not device:
            self.mic_info_label.setText(f"Mic: Device #{idx}")
            return
        label = device.get("name") or f"Device #{idx}"
        channels = device.get("max_input_channels") or 0
        samplerate = device.get("default_samplerate")
        parts = [label, f"#{idx}"]
        if channels:
            parts.append(f"{channels}ch")
        if samplerate:
            parts.append(f"{int(samplerate)} Hz")
        self.mic_info_label.setText("Mic: " + " · ".join(parts))

    def _emit_recorder_state(self) -> None:
        snapshot = self.last_snapshot if self.recording_modes else None
        payload = {
            "recording": bool(self.recording_modes),
            "sessionId": snapshot.sessionId if snapshot else None,
            "bucketId": snapshot.bucketId if snapshot else None,
            "imageId": snapshot.imageId if snapshot else None,
            "modes": sorted(self.recording_modes),
            "subject": self.subject.text().strip() or "me",
            "updated_at": datetime.utcnow().isoformat() + "Z",
        }
        try:
            write_recorder_status(payload)
        except OSError:
            pass


class SessionTranscriber:
    def __init__(self, session_dir: Path, speaker: str) -> None:
        self.session_dir = Path(session_dir)
        self.speaker = speaker
        self.model = None

    def run(self) -> str:
        audio_files: List[Path] = []
        for pattern in ("*.m4a", "*.wav"):
            audio_files.extend(sorted(self.session_dir.rglob(pattern)))
        if not audio_files:
            return "No audio clips to transcribe."
        try:
            self.model = get_whisper_model()
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(f"Failed to load Whisper model '{DEFAULT_WHISPER_MODEL}': {exc}") from exc
        transcripts: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
        session_id = None
        processed = 0
        for audio_path in audio_files:
            meta = load_clip_meta(audio_path)
            if not meta or not meta.get("bucketId"):
                continue
            session_id = session_id or meta.get("sessionId")
            text = self._transcribe_file(audio_path)
            if not text:
                continue
            image_id = meta.get("imageId") or ""
            transcripts[str(meta["bucketId"])].append((image_id, text))
            processed += 1
            write_transcript_file(audio_path, text)
        if not processed:
            return "No usable clips to transcribe."
        applied = apply_voice_transcripts(transcripts, self.speaker, session_id)
        return f"Transcribed {processed} clip(s) into {applied} bucket note(s)."

    def _transcribe_file(self, wav_path: Path) -> str:
        assert self.model is not None
        try:
            result = self.model.transcribe(str(wav_path), fp16=False)
        except Exception:  # pragma: no cover
            return ""
        return (result.get("text") or "").strip()


def apply_voice_transcripts(
    transcripts: Dict[str, List[Tuple[str, str]]],
    speaker: str,
    session_id: Optional[str],
) -> int:
    applied = 0
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    created_at = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    for bucket_prefix, entries in transcripts.items():
        structured_entries: List[Dict[str, str]] = []
        text_lines: List[str] = []
        for image_id, text in entries:
            if not text:
                continue
            label = image_id or "image"
            structured_entries.append({"image_id": label, "text": text})
            text_lines.append(f"{label}: {text}")
        if not structured_entries:
            continue
        header = f"Voice transcript {stamp} · {speaker}"
        if session_id:
            header += f" · Session {session_id}"
        block = header + "\n" + "\n".join(text_lines)
        record = {
            "id": f"{bucket_prefix}-{int(time.time() * 1000)}",
            "speaker": speaker,
            "session_id": session_id,
            "created_at": created_at,
            "entries": structured_entries,
            "note_block": block,
        }
        if store_voice_transcript(bucket_prefix, record):
            applied += 1
    return applied


def store_voice_transcript(bucket_prefix: str, record: Dict[str, object]) -> bool:
    transcript_id = str(record.get("id") or f"{bucket_prefix}-{int(time.time() * 1000)}")
    record["id"] = transcript_id
    bucket_dir = TRANSCRIPTS_ROOT / bucket_prefix
    bucket_dir.mkdir(parents=True, exist_ok=True)
    safe_id = safe_name(transcript_id, max_len=200) or f"{int(time.time() * 1000)}"
    target = bucket_dir / f"{safe_id}.json"
    if target.exists():
        return False
    try:
        target.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        return False
    return True


def main() -> None:
    VOICE_SESSIONS_ROOT.mkdir(parents=True, exist_ok=True)
    OUT_BASE.mkdir(parents=True, exist_ok=True)
    TRANSCRIPTS_ROOT.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    ui = RecorderUI()
    ui.resize(1100, 230)
    ui.show()
    app.exec()


if __name__ == "__main__":
    main()
