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


def export_html_report(results: List[GenerationResult], output_path: Path) -> None:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    items = []
    for result in results:
        items.append(
            f"""
            <div class='item'>
              <h2>{result.source_video_path.as_posix()}</h2>
              <p><strong>安装方式</strong>: {result.structured_tags.get('安装方式', '')}</p>
              <p><strong>运动模式</strong>: {result.structured_tags.get('运动模式', '')}</p>
              <p><strong>运镜方式</strong>: {result.structured_tags.get('运镜方式', '')}</p>
              <p><strong>光源</strong>: {result.structured_tags.get('光源', '')}</p>
              <p><strong>画面特征</strong>: {', '.join(result.multi_select_tags.get('画面特征', []))}</p>
              <p><strong>影像表达</strong>: {', '.join(result.multi_select_tags.get('影像表达', []))}</p>
              <p><strong>画面描述</strong>: {result.scene_description}</p>
              <p><strong>审核状态</strong>: {result.review_status}</p>
              <p><strong>模型</strong>: {result.provider}/{result.model}</p>
            </div>
            """
        )

    html = f"""
    <html>
      <head>
        <meta charset='utf-8'>
        <title>Video Tagging Report</title>
        <style>
          body {{ font-family: Arial, sans-serif; margin: 24px; }}
          .item {{ border: 1px solid #ddd; padding: 16px; margin-bottom: 16px; border-radius: 8px; }}
          h1, h2 {{ margin-top: 0; }}
        </style>
      </head>
      <body>
        <h1>视频打标汇总报告</h1>
        <p>总视频数: {len(results)}</p>
        <p>成功数: {len(results)}</p>
        {''.join(items)}
      </body>
    </html>
    """
    output_path.write_text(html, encoding="utf-8")
