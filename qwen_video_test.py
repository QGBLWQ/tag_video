import os
import json
import base64
from openai import OpenAI

VIDEO_PATH = r"C:\Users\19872\Desktop\work！\videos\1.mp4"
MODEL_NAME = "qwen3.6-flash"
FPS = 2


def encode_video(video_path: str) -> str:
    with open(video_path, "rb") as video_file:
        return base64.b64encode(video_file.read()).decode("utf-8")


def main():
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        raise RuntimeError("未检测到环境变量 DASHSCOPE_API_KEY")

    if not os.path.exists(VIDEO_PATH):
        raise FileNotFoundError(f"视频不存在: {VIDEO_PATH}")

    base64_video = encode_video(VIDEO_PATH)

    client = OpenAI(
        api_key=api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )

    prompt = """
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
                        "text": prompt,
                    },
                ],
            }
        ],
    )

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
    main()
