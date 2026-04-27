from pathlib import Path

from video_tagging_assistant.models import GenerationResult
from video_tagging_assistant.review_exporter import export_html_report


def test_export_html_report_writes_summary_and_rows(tmp_path: Path):
    output_path = tmp_path / "report" / "index.html"
    results = [
        GenerationResult(
            source_video_path=Path("videos/clip01.mp4"),
            structured_tags={"安装方式": "胸前", "光源": "自然光"},
            multi_select_tags={"画面特征": ["重复纹理"], "影像表达": ["建筑空间"]},
            scene_description="详细描述",
            provider="qwen_dashscope",
            model="qwen3.6-flash",
        )
    ]

    export_html_report(results, output_path)

    html = output_path.read_text(encoding="utf-8")
    assert "总视频数" in html
    assert "安装方式" in html
    assert "画面特征" in html
    assert "详细描述" in html
