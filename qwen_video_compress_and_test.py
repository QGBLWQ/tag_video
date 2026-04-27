import os
import json
import base64
import subprocess
from pathlib import Path

import httpx
from openai import OpenAI

BASE_DIR = Path(r"C:\Users\19872\Desktop\work！")
FFMPEG_PATH = BASE_DIR / "ffmpeg.exe"
SOURCE_VIDEO_PATH = BASE_DIR / "videos" / "1.mp4"
COMPRESSED_VIDEO_PATH = BASE_DIR / "videos" / "1_small.mp4"
MODEL_NAME = "qwen3.6-flash"
FPS = 2


def compress_video(source: Path, target: Path) -> None:
    if not source.exists():
        raise FileNotFoundError(f"视频不存在: {source}")
    if not FFMPEG_PATH.exists():
        raise FileNotFoundError(f"未找到 ffmpeg: {FFMPEG_PATH}")

    target.parent.mkdir(parents=True, exist_ok=True)

    command = [
        str(FFMPEG_PATH),
        "-y",
        "-i",
        str(source),
        "-vf",
        "scale=640:-2,fps=2",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "32",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-an",
        str(target),
    ]

    print("=== 开始压缩视频 ===")
    print(" ".join(command))
    subprocess.run(command, check=True)

    if not target.exists():
        raise RuntimeError("压缩完成后未找到输出文件")

    size_mb = target.stat().st_size / (1024 * 1024)
    print(f"压缩完成: {target}")
    print(f"压缩后大小: {size_mb:.2f} MB")


def encode_video(video_path: Path) -> str:
    with open(video_path, "rb") as video_file:
        return base64.b64encode(video_file.read()).decode("utf-8")


def build_prompt() -> str:
    return """
你需要根据视频内容生成审核候选结果。

要求：
1. 输出中文
2. summary 为 1 到 2 句，描述画面主体、动作、场景
3. tags 为 3 到 5 个简洁标签
4. 如果信息不足，notes 中说明
5. 严格输出 JSON，不要输出任何额外说明

返回格式：
{
  "summary": "string",
  "tags": ["string", "string", "string"],
  "notes": "string"
}
""".strip()


def call_qwen(video_path: Path) -> None:
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        raise RuntimeError("未检测到环境变量 DASHSCOPE_API_KEY")

    base64_video = encode_video(video_path)
    print(f"Base64 长度: {len(base64_video)}")

    print("HTTP_PROXY:", os.getenv("HTTP_PROXY") or "<empty>")
    print("HTTPS_PROXY:", os.getenv("HTTPS_PROXY") or "<empty>")

    http_client = httpx.Client(timeout=180.0, trust_env=False)
    client = OpenAI(
        api_key=api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        timeout=180.0,
        max_retries=1,
        http_client=http_client,
    )

    print("=== 开始调用千问 ===")
    try:
        completion = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "video_url",
                            "video_url": {
                                "url": f"data:video/mp4;base64,{base64_video}"
                            },
                            "fps": FPS,
                        },
                        {
                            "type": "text",
                            "text": build_prompt(),
                        },
                    ],
                }
            ],
        )
    finally:
        http_client.close()

    content = completion.choices[0].message.content
    print("=== 原始返回 ===")
    print(content)

    print("\n=== 尝试解析 JSON ===")
    try:
        parsed = json.loads(content)
        print(json.dumps(parsed, ensure_ascii=False, indent=2))
    except Exception:
        print("返回内容不是严格 JSON，请先看上面的原始返回。")


if __name__ == "__main__":
    compress_video(SOURCE_VIDEO_PATH, COMPRESSED_VIDEO_PATH)
    call_qwen(COMPRESSED_VIDEO_PATH)
