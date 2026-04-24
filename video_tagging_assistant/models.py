from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class VideoTask:
    source_video_path: Path
    relative_path: Path
    file_name: str
    case_id: Optional[str] = None
    mode: Optional[str] = None
    device_info: Optional[str] = None
    status: str = "pending"


@dataclass
class CompressedArtifact:
    source_video_path: Path
    compressed_video_path: Path
    duration: Optional[float] = None
    resolution: Optional[str] = None
    size_bytes: Optional[int] = None
    compression_profile: Optional[str] = None


@dataclass
class PromptContext:
    source_video_path: Path
    compressed_video_path: Path
    parsed_metadata: Dict[str, Any]
    template_fields: Dict[str, Any]
    prompt_payload: Dict[str, Any]
    context_warnings: List[str] = field(default_factory=list)


@dataclass
class GenerationResult:
    source_video_path: Path
    summary_text: str = ""
    tags: List[str] = field(default_factory=list)
    notes: str = ""
    structured_tags: Dict[str, str] = field(default_factory=dict)
    multi_select_tags: Dict[str, List[str]] = field(default_factory=dict)
    scene_description: str = ""
    provider: str = ""
    model: str = ""
    raw_response_excerpt: str = ""
    review_status: str = "unreviewed"
