import base64
import json
import os
from pathlib import Path
from typing import Dict
from urllib import request

from video_tagging_assistant.models import GenerationResult, PromptContext
from video_tagging_assistant.providers.base import VideoTagProvider


def parse_json_content(content: str) -> Dict:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    return json.loads(cleaned)


def build_qwen_multimodal_message(video_data_url: str, prompt_text: str, fps: int) -> Dict:
    return {
        "role": "user",
        "content": [
            {
                "type": "video_url",
                "video_url": {"url": video_data_url},
                "fps": fps,
            },
            {
                "type": "text",
                "text": prompt_text,
            },
        ],
    }


def normalize_response_payload(payload: Dict, source_video_path: Path, provider_name: str, model: str) -> GenerationResult:
    multi_select_field_names = {"画面特征", "影像表达"}
    structured_tags = {}
    multi_select_tags = {}

    for key, value in payload.items():
        if key == "画面描述":
            continue
        if key in multi_select_field_names:
            values = value if isinstance(value, list) else [value]
            multi_select_tags[key] = [str(item).strip() for item in values if str(item).strip()]
        else:
            structured_tags[key] = str(value).strip()

    return GenerationResult(
        source_video_path=source_video_path,
        structured_tags=structured_tags,
        multi_select_tags=multi_select_tags,
        scene_description=str(payload.get("画面描述", "")).strip(),
        provider=provider_name,
        model=model,
        raw_response_excerpt=json.dumps(payload, ensure_ascii=False)[:500],
    )


class QwenDashScopeVideoTagProvider(VideoTagProvider):
    provider_name = "qwen_dashscope"

    def __init__(self, base_url: str, api_key_env: str, model: str, fps: int = 2, api_key: str = "") -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key_env = api_key_env
        self.model = model
        self.fps = fps
        self.api_key = api_key

    def _encode_video(self, video_path: Path) -> str:
        with open(video_path, "rb") as video_file:
            return base64.b64encode(video_file.read()).decode("utf-8")

    def _build_prompt_text(self, context: PromptContext) -> str:
        single_fields = context.template_fields.get("single_choice_fields", {})
        multi_fields = context.template_fields.get("multi_choice_fields", {})
        single_lines = [f"- {name}: {', '.join(values)}" for name, values in single_fields.items()]
        multi_lines = [f"- {name}: {', '.join(values)}" for name, values in multi_fields.items()]
        ignore_opening_instruction = context.template_fields.get(
            "ignore_opening_instruction",
            "不要描述开头固定出现的手持手机展示时间特写镜头。",
        )
        scene_instruction = context.template_fields.get(
            "scene_description_instruction",
            "画面描述可更详细，重点描述光亮变化、场景细节、主体运动和画面变化。",
        )
        prompt_lines = [
            context.template_fields.get("system", "请根据视频内容输出结构化标签。"),
            "",
            "规则：",
            "1. 输出中文",
            "2. 单选字段必须且只能选择一个候选值",
            "3. 多选字段可以选择多个候选值",
            "4. 所有值必须来自给定候选列表",
            "5. 不允许输出未定义字段",
            f"6. {ignore_opening_instruction}",
            "7. 画面描述应从真正进入测试场景之后开始，不要把固定的手机时间展示开场算作有效画面内容。",
            f"8. {scene_instruction}",
            "",
            "单选字段：",
            *single_lines,
            "",
            "多选字段：",
            *multi_lines,
            "",
            "附加上下文：",
            f"- case_id: {context.parsed_metadata.get('case_id')}",
            f"- mode: {context.parsed_metadata.get('mode')}",
            f"- file_name: {context.parsed_metadata.get('file_name')}",
            "",
            "返回格式：",
            '{"安装方式": "string", "运动模式": "string", "运镜方式": "string", "光源": "string", "画面特征": ["string"], "影像表达": ["string"], "画面描述": "string"}',
        ]
        return "\n".join([line for line in prompt_lines if line])

    def generate(self, context: PromptContext) -> GenerationResult:
        api_key = self.api_key or os.environ.get(self.api_key_env) or os.environ.get("DASHSCOPE_API_KEY")
        if not api_key:
            raise RuntimeError("未检测到可用的 DashScope API Key")
        base64_video = self._encode_video(context.compressed_video_path)
        video_data_url = f"data:video/mp4;base64,{base64_video}"
        message = build_qwen_multimodal_message(video_data_url, self._build_prompt_text(context), self.fps)
        payload = {
            "model": self.model,
            "messages": [message],
        }
        req = request.Request(
            url=f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        with request.urlopen(req, timeout=180) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        content = body["choices"][0]["message"]["content"]
        parsed = parse_json_content(content)
        return normalize_response_payload(parsed, context.source_video_path, self.provider_name, self.model)
