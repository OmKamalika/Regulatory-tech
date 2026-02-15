"""
Frame extraction service using FFmpeg and OpenCV for scene change detection.
"""
import cv2
import ffmpeg
import os
import logging
from typing import List, Tuple
from dataclasses import dataclass
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class ExtractedFrame:
    """Data class for extracted frame information"""
    frame_number: int
    timestamp: float  # in seconds
    file_path: str
    is_scene_change: bool = False


class FrameExtractor:
    """
    Extracts frames from videos using FFmpeg and OpenCV.
    Supports both fixed FPS extraction and scene change detection.
    """

    def __init__(self, fps: int = None, enable_scene_detection: bool = True):
        self.fps = fps or settings.FRAME_EXTRACTION_FPS
        self.enable_scene_detection = enable_scene_detection
        logger.info(f"Initialized FrameExtractor (fps={self.fps}, scene_detection={self.enable_scene_detection})")

    def extract_frames(
        self,
        video_path: str,
        output_dir: str,
        max_frames: int = None
    ) -> List[ExtractedFrame]:
        """
        Extract frames from video.

        Args:
            video_path: Path to input video file
            output_dir: Directory to save extracted frames
            max_frames: Maximum number of frames to extract (None = unlimited)

        Returns:
            List of ExtractedFrame objects
        """
        os.makedirs(output_dir, exist_ok=True)
        logger.info(f"Extracting frames from {video_path}")

        extracted_frames = []

        if self.enable_scene_detection:
            # Use scene change detection
            extracted_frames = self._extract_with_scene_detection(video_path, output_dir, max_frames)
        else:
            # Use fixed FPS extraction
            extracted_frames = self._extract_fixed_fps(video_path, output_dir, max_frames)

        logger.info(f"Extracted {len(extracted_frames)} frames")
        return extracted_frames

    def _extract_fixed_fps(
        self,
        video_path: str,
        output_dir: str,
        max_frames: int = None
    ) -> List[ExtractedFrame]:
        """Extract frames at fixed FPS intervals"""
        extracted_frames = []

        try:
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                raise ValueError(f"Could not open video file: {video_path}")

            # Get video properties
            original_fps = cap.get(cv2.CAP_PROP_FPS)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

            logger.info(f"Video FPS: {original_fps}, Total frames: {total_frames}")

            # Calculate frame interval
            frame_interval = int(original_fps / self.fps)
            frame_count = 0
            extracted_count = 0

            while True:
                ret, frame = cap.read()
                if not ret:
                    break

                # Extract frame at interval
                if frame_count % frame_interval == 0:
                    timestamp = frame_count / original_fps
                    output_path = os.path.join(output_dir, f"frame_{extracted_count:06d}.jpg")

                    # Save frame
                    cv2.imwrite(output_path, frame, [cv2.IMWRITE_JPEG_QUALITY, 90])

                    extracted_frames.append(ExtractedFrame(
                        frame_number=frame_count,
                        timestamp=timestamp,
                        file_path=output_path
                    ))

                    extracted_count += 1

                    if max_frames and extracted_count >= max_frames:
                        break

                frame_count += 1

            cap.release()

        except Exception as e:
            logger.error(f"Error extracting frames: {e}")
            raise

        return extracted_frames

    def _extract_with_scene_detection(
        self,
        video_path: str,
        output_dir: str,
        max_frames: int = None
    ) -> List[ExtractedFrame]:
        """
        Extract frames using scene change detection.
        Combines fixed FPS with scene changes for better coverage.
        """
        extracted_frames = []

        try:
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                raise ValueError(f"Could not open video file: {video_path}")

            # Get video properties
            original_fps = cap.get(cv2.CAP_PROP_FPS)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

            logger.info(f"Detecting scenes in video (FPS: {original_fps}, Frames: {total_frames})")

            frame_interval = int(original_fps / self.fps)
            frame_count = 0
            extracted_count = 0
            prev_frame = None
            scene_threshold = 30.0  # Scene change threshold

            while True:
                ret, frame = cap.read()
                if not ret:
                    break

                is_scene_change = False

                # Check for scene change
                if prev_frame is not None:
                    # Calculate frame difference (resize current frame for comparison)
                    current_frame_resized = cv2.resize(frame, (320, 240))
                    diff = cv2.absdiff(prev_frame, current_frame_resized)
                    mean_diff = diff.mean()

                    if mean_diff > scene_threshold:
                        is_scene_change = True
                        logger.debug(f"Scene change detected at frame {frame_count} (diff={mean_diff:.2f})")

                # Extract frame if it's a scene change or at interval
                should_extract = is_scene_change or (frame_count % frame_interval == 0)

                if should_extract:
                    timestamp = frame_count / original_fps
                    output_path = os.path.join(output_dir, f"frame_{extracted_count:06d}.jpg")

                    # Save frame
                    cv2.imwrite(output_path, frame, [cv2.IMWRITE_JPEG_QUALITY, 90])

                    extracted_frames.append(ExtractedFrame(
                        frame_number=frame_count,
                        timestamp=timestamp,
                        file_path=output_path,
                        is_scene_change=is_scene_change
                    ))

                    extracted_count += 1

                    if max_frames and extracted_count >= max_frames:
                        break

                # Store frame for next comparison (resize for efficiency)
                prev_frame = cv2.resize(frame, (320, 240))
                frame_count += 1

            cap.release()

        except Exception as e:
            logger.error(f"Error in scene detection: {e}")
            raise

        return extracted_frames

    def get_video_info(self, video_path: str) -> dict:
        """
        Get video metadata using FFmpeg.

        Returns:
            Dictionary with video information
        """
        try:
            probe = ffmpeg.probe(video_path)
            video_info = next(s for s in probe['streams'] if s['codec_type'] == 'video')
            audio_streams = [s for s in probe['streams'] if s['codec_type'] == 'audio']

            return {
                'duration': float(probe['format']['duration']),
                'format': probe['format']['format_name'],
                'size': int(probe['format']['size']),
                'width': int(video_info['width']),
                'height': int(video_info['height']),
                'fps': eval(video_info['r_frame_rate']),  # Converts "30/1" to 30.0
                'codec': video_info['codec_name'],
                'has_audio': len(audio_streams) > 0,
                'audio_codec': audio_streams[0]['codec_name'] if audio_streams else None
            }
        except Exception as e:
            logger.error(f"Error getting video info: {e}")
            raise

    def extract_audio(self, video_path: str, output_path: str) -> str:
        """
        Extract audio track from video.

        Args:
            video_path: Path to input video
            output_path: Path for output audio file (should be .wav or .mp3)

        Returns:
            Path to extracted audio file
        """
        try:
            logger.info(f"Extracting audio from {video_path}")

            # Extract audio using ffmpeg
            stream = ffmpeg.input(video_path)
            stream = ffmpeg.output(stream.audio, output_path, acodec='pcm_s16le', ac=1, ar='16000')
            ffmpeg.run(stream, overwrite_output=True, capture_stdout=True, capture_stderr=True)

            logger.info(f"Audio extracted to {output_path}")
            return output_path

        except ffmpeg.Error as e:
            logger.error(f"FFmpeg error: {e.stderr.decode()}")
            raise
        except Exception as e:
            logger.error(f"Error extracting audio: {e}")
            raise
