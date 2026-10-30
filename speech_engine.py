
"""Local microphone transcription for Quick Note using faster-whisper.

The model preloads on a background thread when the app starts.
Audio capture and transcription also run in a background thread.
Tkinter receives status and text messages through a queue.
"""
from __future__ import annotations

import queue
import threading
from typing import Any

import numpy as np


class SpeechEngine:
    SAMPLE_RATE = 16000
    CHUNK_SECONDS = 3

    def __init__(self, model_size: str = "large-v3-turbo"):
        self.model_size = model_size
        self.messages: queue.Queue[tuple[Any, ...]] = queue.Queue()
        self._audio_queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=120)

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

        # Model loading is independent of microphone listening.
        self._model_lock = threading.Lock()
        self._model_ready = threading.Event()
        self._model_thread: threading.Thread | None = None
        self._model = None
        self._device_label = None
        self._model_error = None

    def preload(self) -> bool:
        """Start loading Whisper in the background, only once."""
        with self._model_lock:
            if self._model_ready.is_set():
                return False

            if (
                self._model_thread is not None
                and self._model_thread.is_alive()
            ):
                return False

            self._model_thread = threading.Thread(
                target=self._load_model,
                name="QuickNoteWhisperPreload",
                daemon=True,
            )
            self._model_thread.start()
            return True

    def _load_model(self) -> None:
        """Load Whisper on a worker thread, preferring the GPU."""
        try:
            self._send(
                "status",
                "Preloading Whisper in the background… "
                "the first launch may download the model."
            )

            from faster_whisper import WhisperModel

            try:
                model = WhisperModel(
                    self.model_size,
                    device="cuda",
                    compute_type="float16",
                )
                device_label = "RTX GPU"

            except Exception as gpu_error:
                self._send(
                    "status",
                    "GPU unavailable; trying CPU instead: "
                    + str(gpu_error)[:100],
                )

                model = WhisperModel(
                    self.model_size,
                    device="cpu",
                    compute_type="int8",
                )
                device_label = "CPU"

            self._model = model
            self._device_label = device_label
            self._send(
                "status",
                f"Whisper ready on {device_label}; waiting for Speak."
            )

        except Exception as error:
            self._model_error = (
                f"{type(error).__name__}: {error}"
            )

        finally:
            self._model_ready.set()

    def start(self) -> bool:
        """Start microphone transcription using the preloaded model."""
        # Also supports starting speech if preload was not called earlier.
        self.preload()

        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False

            self._stop_event.clear()

            while True:
                try:
                    self._audio_queue.get_nowait()
                except queue.Empty:
                    break

            self._thread = threading.Thread(
                target=self._run,
                name="QuickNoteSpeech",
                daemon=True,
            )
            self._thread.start()
            return True

    def stop(self) -> None:
        self._stop_event.set()

    def _send(self, *message: Any) -> None:
        self.messages.put(tuple(message))

    def _run(self) -> None:
        stream = None

        try:
            if not self._model_ready.is_set():
                self._send(
                    "status",
                    "Waiting for Whisper to finish loading…"
                )

            # Wait without blocking Tkinter. Stop can cancel the wait.
            while not self._model_ready.wait(timeout=0.1):
                if self._stop_event.is_set():
                    self._send("stopped")
                    return

            if self._stop_event.is_set():
                self._send("stopped")
                return

            if self._model_error:
                raise RuntimeError(self._model_error)

            model = self._model
            device_label = self._device_label

            if model is None:
                raise RuntimeError("Whisper model was not loaded.")

            import sounddevice as sd

            def audio_callback(
                indata, frames, time_info, status
            ):
                if self._stop_event.is_set():
                    return

                block = indata[:, 0].copy()

                try:
                    self._audio_queue.put_nowait(block)
                except queue.Full:
                    try:
                        self._audio_queue.get_nowait()
                    except queue.Empty:
                        pass

                    try:
                        self._audio_queue.put_nowait(block)
                    except queue.Full:
                        pass

            stream = sd.InputStream(
                samplerate=self.SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=1600,
                callback=audio_callback,
            )
            stream.start()

            self._send(
                "status",
                f"Listening on {device_label}; "
                "detecting language automatically…"
            )

            chunk_samples = int(
                self.SAMPLE_RATE * self.CHUNK_SECONDS
            )
            audio_parts: list[np.ndarray] = []
            buffered_samples = 0

            while not self._stop_event.is_set():
                try:
                    block = self._audio_queue.get(timeout=0.1)
                    audio_parts.append(block)
                    buffered_samples += len(block)
                except queue.Empty:
                    continue

                if buffered_samples < chunk_samples:
                    continue

                audio = np.concatenate(audio_parts)
                chunk = audio[:chunk_samples].astype(
                    np.float32, copy=False
                )
                remainder = audio[chunk_samples:]

                audio_parts = [remainder] if len(remainder) else []
                buffered_samples = len(remainder)

                try:
                    segments, info = model.transcribe(
                        chunk,
                        language=None,
                        task="transcribe",
                        beam_size=1,
                        best_of=1,
                        temperature=0,
                        condition_on_previous_text=False,
                        vad_filter=True,
                        vad_parameters={
                            "min_silence_duration_ms": 400
                        },
                    )

                    recognised = " ".join(
                        segment.text.strip()
                        for segment in segments
                    ).strip()

                    language = (
                        getattr(info, "language", None) or "unknown"
                    )

                    if recognised:
                        self._send("text", recognised, language)
                    else:
                        self._send(
                            "status",
                            f"Listening on {device_label}; "
                            "language detection is automatic…"
                        )

                except Exception as error:
                    self._send(
                        "status",
                        "Transcription hiccup; continuing: "
                        + str(error)[:120],
                    )

            self._send("stopped")

        except Exception as error:
            self._send(
                "error",
                f"{type(error).__name__}: {error}"
            )

        finally:
            if stream is not None:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass
