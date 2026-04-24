from pathlib import Path
from typing import List

from video_tagging_assistant.models import GenerationResult


def export_review_list(results: List[GenerationResult], output_path: Path) -> None:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    sections = []
    for index, result in enumerate(results, start=1):
        single_lines = [f"{key}: {value}" for key, value in result.structured_tags.items()]
        multi_lines = [f"{key}: {', '.join(values)}" for key, values in result.multi_select_tags.items()]
        fallback_lines = []
        if not single_lines and not multi_lines:
            fallback_lines = [
                f"建议简介: {result.summary_text}",
                f"建议标签: {', '.join(result.tags)}",
                f"备注: {result.notes}",
            ]

        sections.append(
            "\n".join(
                [
                    f"## 条目 {index}",
                    f"视频路径: {result.source_video_path.as_posix()}",
                    *single_lines,
                    *multi_lines,
                    *fallback_lines,
                    f"画面描述: {result.scene_description}",
                    f"审核状态: {result.review_status}",
                    f"模型: {result.provider}/{result.model}",
                ]
            )
        )

    output_path.write_text("\n\n---\n\n".join(sections) + "\n", encoding="utf-8")
