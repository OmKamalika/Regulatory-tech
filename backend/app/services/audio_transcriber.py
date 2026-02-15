"""
Audio transcription service using OpenAI Whisper (local model).
"""
import whisper
import logging
from typing import List, Optional
from dataclasses import dataclass

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class TranscriptionSegment:
    """Data class for transcription segment"""
    start: float  # in seconds
    end: float
    text: str
    confidence: Optional[float] = None


class AudioTranscriber:
    """
    Transcribes audio using Whisper model running locally.
    Supports multiple model sizes: tiny, small, medium, large
    """

    def __init__(self, model_size: str = None):
        self.model_size = model_size or settings.WHISPER_MODEL
        logger.info(f"Loading Whisper model: {self.model_size}")

        try:
            self.model = whisper.load_model(self.model_size)
            logger.info(f"Whisper model '{self.model_size}' loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load Whisper model: {e}")
            raise

    def transcribe(
        self,
        audio_path: str,
        language: str = "en",
        return_timestamps: bool = True
    ) -> dict:
        """
        Transcribe audio file.

        Args:
            audio_path: Path to audio file
            language: Language code (default: "en")
            return_timestamps: Whether to return word-level timestamps

        Returns:
            Dictionary containing transcription results
        """
        logger.info(f"Transcribing audio: {audio_path}")

        try:
            result = self.model.transcribe(
                audio_path,
                language=language,
                task="transcribe",
                verbose=False,
                word_timestamps=return_timestamps
            )

            logger.info(f"Transcription completed. Language: {result.get('language', 'unknown')}")
            return result

        except Exception as e:
            logger.error(f"Error transcribing audio: {e}")
            raise

    def get_segments(self, audio_path: str, language: str = "en") -> List[TranscriptionSegment]:
        """
        Get transcription segments with timestamps.

        Args:
            audio_path: Path to audio file
            language: Language code

        Returns:
            List of TranscriptionSegment objects
        """
        result = self.transcribe(audio_path, language=language)

        segments = []
        for segment in result.get("segments", []):
            segments.append(TranscriptionSegment(
                start=segment["start"],
                end=segment["end"],
                text=segment["text"].strip(),
                confidence=segment.get("confidence")
            ))

        return segments

    def get_full_text(self, audio_path: str, language: str = "en") -> str:
        """
        Get full transcription text without timestamps.

        Args:
            audio_path: Path to audio file
            language: Language code

        Returns:
            Complete transcription text
        """
        result = self.transcribe(audio_path, language=language)
        return result.get("text", "").strip()

    def detect_language(self, audio_path: str) -> dict:
        """
        Detect language of audio file.

        Args:
            audio_path: Path to audio file

        Returns:
            Dictionary with language detection results
        """
        logger.info(f"Detecting language for: {audio_path}")

        try:
            # Load audio and pad/trim to 30 seconds
            audio = whisper.load_audio(audio_path)
            audio = whisper.pad_or_trim(audio)

            # Make log-Mel spectrogram
            mel = whisper.log_mel_spectrogram(audio).to(self.model.device)

            # Detect language
            _, probs = self.model.detect_language(mel)

            # Get top 3 languages
            top_langs = sorted(probs.items(), key=lambda x: x[1], reverse=True)[:3]

            result = {
                "detected_language": max(probs, key=probs.get),
                "confidence": probs[max(probs, key=probs.get)],
                "top_languages": {lang: prob for lang, prob in top_langs}
            }

            logger.info(f"Detected language: {result['detected_language']} (confidence: {result['confidence']:.2f})")
            return result

        except Exception as e:
            logger.error(f"Error detecting language: {e}")
            raise

    def transcribe_with_speaker_diarization(
        self,
        audio_path: str,
        language: str = "en"
    ) -> List[dict]:
        """
        Transcribe with basic speaker diarization.
        Note: This is a simplified version. For production, consider using
        pyannote.audio or similar libraries for better speaker diarization.

        Args:
            audio_path: Path to audio file
            language: Language code

        Returns:
            List of segments with speaker information
        """
        result = self.transcribe(audio_path, language=language)

        # Simple speaker diarization based on pauses
        segments_with_speakers = []
        current_speaker = 1
        last_end = 0

        for segment in result.get("segments", []):
            # If there's a significant pause (>2 seconds), assume speaker change
            if segment["start"] - last_end > 2.0:
                current_speaker = 2 if current_speaker == 1 else 1

            segments_with_speakers.append({
                "start": segment["start"],
                "end": segment["end"],
                "text": segment["text"].strip(),
                "speaker": f"Speaker {current_speaker}",
                "confidence": segment.get("confidence")
            })

            last_end = segment["end"]

        return segments_with_speakers

    def get_model_info(self) -> dict:
        """Get information about the loaded Whisper model"""
        return {
            "model_size": self.model_size,
            "device": str(self.model.device),
            "is_multilingual": self.model.is_multilingual
        }
