from pathlib import Path

from video_tagging_assistant.models import CompressedArtifact
from video_tagging_assistant.pipeline_models import CaseManifest
from video_tagging_assistant.tagging_service import run_batch_tagging


class StubProvider:
    provider_name = "stub"

    def generate(self, context):
        from video_tagging_assistant.models import GenerationResult

        return GenerationResult(
            source_video_path=context.source_video_path,
            case_key=context.prompt_payload["workbook"]["文件夹名"],
            summary_text="自动简介",
            structured_tags={"安装方式": "手持"},
            scene_description="画面描述",
            provider="stub",
            model="stub-model",
        )


def stub_compressor(task, output_dir, compression_config):
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"{task.source_video_path.stem}_proxy.mp4"
    target.write_bytes(b"proxy")
    return CompressedArtifact(
        source_video_path=task.source_video_path,
        compressed_video_path=target,
    )


def build_manifest(tmp_path: Path) -> CaseManifest:
    normal = tmp_path / "normal.MP4"
    night = tmp_path / "night.MP4"
    normal.write_bytes(b"video")
    night.write_bytes(b"video")
    return CaseManifest(
        case_id="case_A_0105",
        row_index=12,
        created_date="20260428",
        mode="OV50H40_Action5Pro_DCG HDR",
        raw_path=tmp_path / "raw",
        vs_normal_path=normal,
        vs_night_path=night,
        local_case_root=tmp_path / "case_A_0105",
        server_case_dir=tmp_path / "server" / "case_A_0105",
        remark="场景备注",
        labels={"安装方式": "手持", "运动模式": "行走"},
    )


def test_run_batch_tagging_generates_results_when_mode_is_fresh(tmp_path: Path):
    events = []
    results = run_batch_tagging(
        manifests=[build_manifest(tmp_path)],
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "output",
        provider=StubProvider(),
        prompt_template={"system": "describe"},
        mode="fresh",
        event_callback=events.append,
        compressor=stub_compressor,
    )
    assert results[0].case_id == "case_A_0105"
    assert results[0].auto_summary == "自动简介"
    assert any(event.stage.value == "tagging_running" for event in events)


def test_run_batch_tagging_uses_cache_when_mode_is_cached(tmp_path: Path):
    manifest = build_manifest(tmp_path)
    run_batch_tagging(
        manifests=[manifest],
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "output",
        provider=StubProvider(),
        prompt_template={"system": "describe"},
        mode="fresh",
        event_callback=lambda event: None,
        compressor=stub_compressor,
    )
    cached_results = run_batch_tagging(
        manifests=[manifest],
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "output2",
        provider=StubProvider(),
        prompt_template={"system": "describe"},
        mode="cached",
        event_callback=lambda event: None,
        compressor=stub_compressor,
    )
    assert cached_results[0].tag_source == "cache"
