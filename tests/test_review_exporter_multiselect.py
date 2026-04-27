from pathlib import Path

from video_tagging_assistant.models import GenerationResult
from video_tagging_assistant.review_exporter import export_review_list


def test_export_review_list_renders_multiselect_fields(tmp_path: Path):
    output_path = tmp_path / "review.txt"
    result = GenerationResult(
        source_video_path=Path("videos/case_A_001/clip01.mp4"),
        structured_tags={"安装方式": "胸前", "光源": "自然光"},
        multi_select_tags={
            "画面特征": ["重复纹理", "边缘特征_强弱"],
            "影像表达": ["建筑空间", "风景录像"],
        },
        scene_description="详细描述，有效画面信息，不写手机时间开场。",
        provider="qwen_dashscope",
        model="qwen3.6-flash",
    )

    export_review_list([result], output_path)

    text = output_path.read_text(encoding="utf-8")
    assert "画面特征: 重复纹理, 边缘特征_强弱" in text
    assert "影像表达: 建筑空间, 风景录像" in text
