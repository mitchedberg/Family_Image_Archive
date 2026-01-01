import threading
from typing import Optional


class AppleSpeechError(RuntimeError):
    pass


class AppleSpeechRecognizer:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._text = ""
        self._error: Optional[str] = None
        self._running = False
        self._frameworks_loaded = False
        self._SFSpeechRecognizer = None
        self._SFSpeechAudioBufferRecognitionRequest = None
        self._AVAudioEngine = None
        self._engine = None
        self._request = None
        self._task = None
        self._tap_installed = False

    def is_running(self) -> bool:
        return self._running

    def get_text(self) -> str:
        with self._lock:
            return self._text

    def get_error(self) -> Optional[str]:
        with self._lock:
            return self._error

    def clear_error(self) -> None:
        with self._lock:
            self._error = None

    def start(self) -> bool:
        if self._running:
            return True
        try:
            self._load_frameworks()
            self._ensure_authorized()
        except AppleSpeechError as exc:
            self._set_error(str(exc))
            return False
        recognizer = self._SFSpeechRecognizer.alloc().init()
        if recognizer is None or not recognizer.isAvailable():
            self._set_error("Speech recognizer unavailable.")
            return False
        request = self._SFSpeechAudioBufferRecognitionRequest.alloc().init()
        request.setShouldReportPartialResults_(True)
        engine = self._AVAudioEngine.alloc().init()
        input_node = engine.inputNode()
        format_ = input_node.outputFormatForBus_(0)

        def tap_handler(buffer, when):
            try:
                request.appendAudioPCMBuffer_(buffer)
            except Exception as exc:
                self._set_error(f"Audio buffer error: {exc}")

        input_node.installTapOnBus_bufferSize_format_block_(0, 1024, format_, tap_handler)
        self._tap_installed = True

        def result_handler(result, error):
            if error:
                self._set_error(str(error))
                return
            if result:
                text = str(result.bestTranscription().formattedString())
                with self._lock:
                    self._text = text

        self._task = recognizer.recognitionTaskWithRequest_resultHandler_(request, result_handler)
        engine.prepare()
        started = engine.startAndReturnError_(None)
        if isinstance(started, tuple):
            ok, err = started
            if not ok:
                self._set_error(f"Audio engine failed: {err}")
                self._cleanup_engine(engine)
                return False
        elif not started:
            self._set_error("Audio engine failed to start.")
            self._cleanup_engine(engine)
            return False

        self._engine = engine
        self._request = request
        self._running = True
        with self._lock:
            self._text = ""
            self._error = None
        return True

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._task is not None:
            try:
                self._task.cancel()
            except Exception:
                pass
        if self._request is not None:
            try:
                self._request.endAudio()
            except Exception:
                pass
        if self._engine is not None:
            self._cleanup_engine(self._engine)
        self._task = None
        self._request = None
        self._engine = None

    def _cleanup_engine(self, engine) -> None:
        try:
            if self._tap_installed:
                engine.inputNode().removeTapOnBus_(0)
        except Exception:
            pass
        try:
            engine.stop()
        except Exception:
            pass
        self._tap_installed = False

    def _set_error(self, message: str) -> None:
        with self._lock:
            self._error = message

    def _load_frameworks(self) -> None:
        if self._frameworks_loaded:
            return
        try:
            import objc  # noqa: F401
            from AVFoundation import AVAudioEngine
            from Speech import SFSpeechRecognizer, SFSpeechAudioBufferRecognitionRequest
        except Exception as exc:
            raise AppleSpeechError("Apple Speech framework not available.") from exc
        self._SFSpeechRecognizer = SFSpeechRecognizer
        self._SFSpeechAudioBufferRecognitionRequest = SFSpeechAudioBufferRecognitionRequest
        self._AVAudioEngine = AVAudioEngine
        self._frameworks_loaded = True

    def _ensure_authorized(self) -> None:
        status = self._SFSpeechRecognizer.authorizationStatus()
        if int(status) == 3:
            return
        if int(status) == 0:
            event = threading.Event()
            result_holder = {"status": status}

            def handler(new_status):
                result_holder["status"] = new_status
                event.set()

            self._SFSpeechRecognizer.requestAuthorization_(handler)
            event.wait(timeout=5)
            status = result_holder.get("status", status)
        if int(status) != 3:
            raise AppleSpeechError("Apple Speech not authorized. Enable Speech Recognition for this app.")
