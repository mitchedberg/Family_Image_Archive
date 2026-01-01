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
        self.realtime_transcription_enabled = False
        self.transcription_queue: Optional[queue.Queue] = None

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

    def stop(self) -> Optional[Path]:
        if not self.recording:
            return None
        session_dir = self.session_dir
        try:
            if self.stream:
                self.stream.stop()
                self.stream.close()
        finally:
            self.stream = None
        self._close_current_file()
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
        return session_dir

    def on_state_change(self, snapshot: Snapshot) -> None:
        if not snapshot.bucketId or not snapshot.imageId:
            return
        if not self.recording:
            self.current_snapshot = snapshot
            return
        if self.current_snapshot and snapshot.key() == self.current_snapshot.key():
            if self.mode == "continuous" and snapshot.noteFlag:
                self._write_marker(snapshot)
            return
        self.current_snapshot = snapshot
        if self.mode == "segmented":
            self._close_current_file()
            self._open_file_for_snapshot(snapshot)
        else:
            self._write_marker(snapshot)

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

    def _close_current_file(self) -> None:
        if self.sndfile:
            self.sndfile.flush()
            self.sndfile.close()
            self.sndfile = None
            finished = self.current_clip_path
            self.current_clip_path = None
            if finished:
                self._process_finished_clip(finished)
                # Queue for real-time transcription if enabled and in segmented mode
                if (
                    self.mode == "segmented"
                    and self.realtime_transcription_enabled
                    and self.transcription_queue is not None
                ):
                    self._queue_clip_for_transcription(finished)

    def _on_audio(self, indata, frames, time_info, status) -> None:
        if status:
            # status is informational; ignore for now
            pass
        if not self.sndfile:
            return
        self.sndfile.write(indata.copy())

    def _process_finished_clip(self, wav_path: Path) -> None:
        profile = self.audio_profile or {}
        codec = str(profile.get("codec") or "aac").lower()
        if codec not in {"aac", "alac"}:
            return
        if shutil.which("afconvert") is None:
            return
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
        except subprocess.CalledProcessError:
            return

    def _queue_clip_for_transcription(self, clip_path: Path) -> None:
        """Queue a single clip for real-time transcription."""
        if not self.transcription_queue or not self.session_dir:
            return
        # Queue individual clip with its metadata
        self.transcription_queue.put(("clip", clip_path, self.subject))


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
        self.chk_realtime_transcribe = QCheckBox("Real-time transcription")
        self.chk_realtime_transcribe.setChecked(False)
        self.chk_realtime_transcribe.setToolTip("Enable background transcription as you move between images")
        self.audio_format_box = QComboBox()
        self.audio_format_box.addItems(["AAC 128 kbps (m4a)", "Apple Lossless (m4a)"])
        self.mic_box = QComboBox()
        self.mic_info_label = QLabel("Mic: System default")
        self.mic_info_label.setMinimumWidth(220)
        self._mic_devices: Dict[int, dict] = {}
        self._populate_mic_choices()
        self.mic_box.currentIndexChanged.connect(self._refresh_mic_label)
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
        manage_row.addWidget(self.chk_realtime_transcribe)
        manage_row.addStretch()
        manage_row.addWidget(self.btn_transcribe_old)

        layout = QVBoxLayout()
        layout.addLayout(mode_row)
        layout.addLayout(controls_row)
        layout.addLayout(manage_row)
        layout.addWidget(self.bucket_label)
        layout.addWidget(self.state_label)
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
        self._emit_recorder_state()
        
        self.transcription_queue = queue.Queue()
        self.transcription_thread = threading.Thread(target=self._transcription_worker, daemon=True)
        self.transcription_thread.start()

    def _transcription_worker(self) -> None:
        while True:
            try:
                task = self.transcription_queue.get()
                if task is None:
                    break

                # Handle both session-level and clip-level transcription
                if isinstance(task, tuple) and len(task) >= 2:
                    if task[0] == "clip":
                        # Real-time clip transcription: ("clip", clip_path, speaker)
                        _, clip_path, speaker = task
                        if not clip_path or not Path(clip_path).exists():
                            self.transcription_queue.task_done()
                            continue
                        try:
                            self._transcribe_single_clip(clip_path, speaker)
                        except Exception as e:
                            print(f"Transcription error for clip {clip_path}: {e}")
                    else:
                        # Session-level transcription: (session_dir, speaker)
                        session_dir, speaker = task
                        if not session_dir or not session_dir.exists():
                            self.transcription_queue.task_done()
                            continue
                        try:
                            transcriber = SessionTranscriber(session_dir, speaker)
                            transcriber.run()
                        except Exception as e:
                            print(f"Transcription error for {session_dir}: {e}")

                self.transcription_queue.task_done()
            except Exception as e:
                print(f"Worker loop error: {e}")

    def _transcribe_single_clip(self, clip_path: Path, speaker: str) -> None:
        """Transcribe a single clip and store the result."""
        if whisper is None:
            return

        clip_path = Path(clip_path)

        # Guard: Skip if already transcribed
        txt_path = clip_path.with_suffix(".txt")
        if txt_path.exists():
            return

        # Load metadata
        meta_path = clip_path.with_suffix(".json")
        if not meta_path.exists():
            return

        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            return

        bucket_id = meta.get("bucketId")
        if not bucket_id:
            return

        # Transcribe the clip
        try:
            model = whisper.load_model(DEFAULT_WHISPER_MODEL)
            result = model.transcribe(str(clip_path), fp16=False)
            text = (result.get("text") or "").strip()
        except Exception:
            return

        if not text:
            return

        # Write transcript file alongside the clip
        try:
            txt_path.write_text(text + "\n", encoding="utf-8")
        except OSError:
            return

        # Store in bucket transcript store
        image_id = meta.get("imageId") or ""
        session_id = meta.get("sessionId")
        transcripts = {bucket_id: [(image_id, text)]}
        apply_voice_transcripts(transcripts, speaker, session_id)

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
        for session in self.sessions.values():
            session.on_state_change(snapshot)
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

        # Enable real-time transcription on sessions if toggled
        realtime_enabled = self.chk_realtime_transcribe.isChecked()
        for mode in selected:
            self.sessions[mode].realtime_transcription_enabled = realtime_enabled
            self.sessions[mode].transcription_queue = self.transcription_queue

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
        if auto_trigger:
            self.state_label.setText(self.state_label.text() + "\n(Auto-started)")

    def stop_recording(self) -> None:
        completed: List[Tuple[str, Optional[Path]]] = []
        for mode in list(self.recording_modes):
            path = self.sessions[mode].stop()
            completed.append((mode, path))
        self.recording_modes.clear()
        self._update_indicator(False)
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self._emit_recorder_state()
        speaker = self.subject.text().strip() or "me"
        for mode, path in completed:
            if mode == "segmented" and path:
                # Queue for background transcription instead of blocking
                self.transcription_queue.put((path, speaker))

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
        self._mic_devices = {}
        self.mic_box.clear()
        self.mic_box.addItem("System default", None)
        try:
            devices = sd.query_devices()
        except Exception:
            self.mic_info_label.setText("Mic: system default (enumeration failed)")
            return
        default_index = self._default_input_device()
        selected_combo_index = 0
        for idx, device in enumerate(devices):
            if device.get("max_input_channels", 0) <= 0:
                continue
            label = device.get("name") or f"Device {idx}"
            display = f"{label} (#{idx})"
            self.mic_box.addItem(display, idx)
            self._mic_devices[idx] = device
            if default_index is not None and idx == default_index:
                selected_combo_index = self.mic_box.count() - 1
        self.mic_box.setCurrentIndex(selected_combo_index)
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
            self.model = whisper.load_model(DEFAULT_WHISPER_MODEL)
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(f"Failed to load Whisper model '{DEFAULT_WHISPER_MODEL}': {exc}") from exc
        transcripts: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
        session_id = None
        processed = 0
        for audio_path in audio_files:
            meta = self._load_clip_meta(audio_path)
            if not meta or not meta.get("bucketId"):
                continue
            session_id = session_id or meta.get("sessionId")
            text = self._transcribe_file(audio_path)
            if not text:
                continue
            image_id = meta.get("imageId") or ""
            transcripts[str(meta["bucketId"])].append((image_id, text))
            processed += 1
            self._write_transcript_file(audio_path, text)
        if not processed:
            return "No usable clips to transcribe."
        applied = apply_voice_transcripts(transcripts, self.speaker, session_id)
        return f"Transcribed {processed} clip(s) into {applied} bucket note(s)."

    def _load_clip_meta(self, wav_path: Path) -> Optional[dict]:
        meta_path = wav_path.with_suffix(".json")
        if not meta_path.exists():
            return None
        try:
            return json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _transcribe_file(self, wav_path: Path) -> str:
        assert self.model is not None
        # Guard: Skip if already transcribed
        txt_path = wav_path.with_suffix(".txt")
        if txt_path.exists():
            try:
                return txt_path.read_text(encoding="utf-8").strip()
            except Exception:
                pass
        try:
            result = self.model.transcribe(str(wav_path), fp16=False)
        except Exception:  # pragma: no cover
            return ""
        return (result.get("text") or "").strip()

    def _write_transcript_file(self, wav_path: Path, text: str) -> None:
        if not text:
            return
        txt_path = wav_path.with_suffix(".txt")
        try:
            txt_path.write_text(text.strip() + "\n", encoding="utf-8")
        except OSError:
            pass


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
    ui.resize(1100, 140)
    ui.show()
    app.exec()


if __name__ == "__main__":
    main()
