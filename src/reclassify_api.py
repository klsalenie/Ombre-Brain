<<<<<<< HEAD
#!/usr/bin/env python3
"""
========================================
reclassify_api.py — 重新打标「未分类」记忆桶的一次性脚本
========================================

历史遗留的、落在「未分类/」目录的记忆桶，调 LLM 重算 domain/tags/name，
然后搬着那个桶去正确的 domain 目录。

关键行为：
- 扫描 dynamic / 未分类下所有 .md，逼一次 analyze
- 只修改 frontmatter 和文件位置，不动正文
- 幂等：已在正确位置的跳过

不做什么（边界）：
- 不做合并、不做衰减、不调整 importance
- 不作为常驻服务运行，手动 docker exec 调用

对外暴露：CLI 入口（python3 reclassify_api.py）
========================================
"""
import asyncio
import os
import json
import glob
import re

from openai import AsyncOpenAI
import frontmatter

ANALYZE_PROMPT = (
    "你是一个内容分析器。请分析以下文本，输出结构化的元数据。\n\n"
    "分析规则：\n"
    '1. domain（主题域）：选最精确的 1~2 个，只选真正相关的\n'
    '   日常: ["饮食", "穿搭", "出行", "居家", "购物"]\n'
    '   人际: ["家庭", "恋爱", "友谊", "社交"]\n'
    '   成长: ["工作", "学习", "考试", "求职"]\n'
    '   身心: ["健康", "心理", "睡眠", "运动"]\n'
    '   兴趣: ["游戏", "影视", "音乐", "阅读", "创作", "手工"]\n'
    '   数字: ["编程", "AI", "硬件", "网络"]\n'
    '   事务: ["财务", "计划", "待办"]\n'
    '   内心: ["情绪", "回忆", "梦境", "自省"]\n'
    "2. valence（情感效价）：0.0~1.0，0=极度消极 → 0.5=中性 → 1.0=极度积极\n"
    "3. arousal（情感唤醒度）：0.0~1.0，0=非常平静 → 0.5=普通 → 1.0=非常激动\n"
    "4. tags（关键词标签）：3~5 个最能概括内容的关键词\n"
    "5. suggested_name（建议桶名）：10字以内的简短标题\n\n"
    "输出格式（纯 JSON，无其他内容）：\n"
    '{\n'
    '  "domain": ["主题域1", "主题域2"],\n'
    '  "valence": 0.7,\n'
    '  "arousal": 0.4,\n'
    '  "tags": ["标签1", "标签2", "标签3"],\n'
    '  "suggested_name": "简短标题"\n'
    '}'
)

DATA_DIR = os.path.join(
    os.environ.get("OMBRE_BUCKETS_DIR", "").strip()
    or (lambda: __import__("utils").load_config()["buckets_dir"])(),
    "dynamic",
)
UNCLASS_DIR = os.path.join(DATA_DIR, "未分类")


def sanitize(name):
    name = re.sub(r'[<>:"/\\|?*\n\r]', '', name).strip()
    return name[:20] if name else "未命名"


async def reclassify():
    from utils import load_config
    cfg = load_config()
    dehy = cfg.get("dehydration", {})
    client = AsyncOpenAI(
        api_key=os.environ.get("OMBRE_COMPRESS_API_KEY", "") or dehy.get("api_key", ""),
        base_url=dehy.get("base_url", "https://api.deepseek.com/v1"),
        timeout=60.0,
    )
    model_name = dehy.get("model", "deepseek-chat")

    files = sorted(glob.glob(os.path.join(UNCLASS_DIR, "*.md")))
    print(f"找到 {len(files)} 个未分类文件\n")

    for fpath in files:
        basename = os.path.basename(fpath)
        post = frontmatter.load(fpath)
        content = post.content.strip()
        name = post.metadata.get("name", "")
        full_text = f"{name}\n{content}" if name else content

        try:
            resp = await client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": ANALYZE_PROMPT},
                    {"role": "user", "content": full_text[:2000]},
                ],
                max_tokens=256,
                temperature=0.1,
            )
            raw = resp.choices[0].message.content.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
            result = json.loads(raw)
        except Exception as e:
            print(f"  X API失败 {basename}: {e}")
            continue

        new_domain = result.get("domain", ["未分类"])[:3]
        new_tags = result.get("tags", [])[:5]
        new_name = sanitize(result.get("suggested_name", "") or name)
        new_valence = max(0.0, min(1.0, float(result.get("valence") or 0.5)))
        new_arousal = max(0.0, min(1.0, float(result.get("arousal") or 0.3)))

        post.metadata["domain"] = new_domain
        post.metadata["tags"] = new_tags
        post.metadata["valence"] = new_valence
        post.metadata["arousal"] = new_arousal
        if new_name:
            post.metadata["name"] = new_name

        # 写回文件
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(frontmatter.dumps(post))

        # 移动到正确目录
        primary = sanitize(new_domain[0]) if new_domain else "未分类"
        target_dir = os.path.join(DATA_DIR, primary)
        os.makedirs(target_dir, exist_ok=True)

        bid = post.metadata.get("id", "")
        new_filename = f"{new_name}_{bid}.md" if new_name and new_name != bid else basename
        dest = os.path.join(target_dir, new_filename)

        if dest != fpath:
            os.rename(fpath, dest)

        print(f"  OK {basename}")
        print(f"     -> {primary}/{new_filename}")
        print(f"     domain={new_domain} tags={new_tags} V={new_valence} A={new_arousal}")
        print()


if __name__ == "__main__":
    asyncio.run(reclassify())
=======
#!/usr/bin/env python3
"""Reclassify legacy ``dynamic/unclassified`` buckets.

The command changes metadata and location only. Stored memory content is read
and written verbatim. Configuration and the analyzer are resolved when the
command runs, not while the module is imported, so the workflow is testable and
safe to embed in a future desktop maintenance process.
"""

from __future__ import annotations

import asyncio
import math
import re
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

import frontmatter

from dehydrator import Dehydrator
from utils import atomic_write_text, load_config


class Analyzer(Protocol):
    async def analyze(self, content: str) -> Mapping[str, Any]: ...


Emit = Callable[[str], Any]


def sanitize(name: object, *, fallback: str = "unnamed", limit: int = 80) -> str:
    cleaned = re.sub(r'[^\w\s\u4e00-\u9fff-]', "", str(name or ""), flags=re.UNICODE)
    return cleaned.strip()[:limit] or fallback


def _bucket_id(value: object, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "", str(value or ""))[:64]
    return cleaned or sanitize(fallback, fallback="bucket", limit=64)


def _unit_float(value: object, default: float) -> float:
    try:
        numeric = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return default
    if not math.isfinite(numeric):
        return default
    return max(0.0, min(1.0, numeric))


def _string_list(value: object, *, limit: int, fallback: list[str]) -> list[str]:
    if isinstance(value, str):
        candidates = [value]
    elif isinstance(value, (list, tuple)):
        candidates = list(value)
    else:
        candidates = []
    normalized = []
    for item in candidates:
        text = str(item or "").strip()
        if text and text not in normalized:
            normalized.append(text[:80])
        if len(normalized) >= limit:
            break
    return normalized or list(fallback)


def _target_path(
    dynamic_dir: Path,
    post: frontmatter.Post,
    source: Path,
    analysis: Mapping[str, Any],
) -> tuple[Path, dict[str, Any]]:
    old_name = str(post.metadata.get("name") or "")
    domains = _string_list(
        analysis.get("domain"),
        limit=3,
        fallback=["unclassified"],
    )
    tags = _string_list(analysis.get("tags"), limit=5, fallback=[])
    name = sanitize(
        analysis.get("suggested_name") or old_name,
        fallback=sanitize(old_name, fallback="unnamed", limit=80),
        limit=80,
    )
    identifier = _bucket_id(post.metadata.get("id"), source.stem)
    primary = sanitize(domains[0], fallback="unclassified", limit=80)
    filename = f"{name}_{identifier}.md" if name != identifier else f"{identifier}.md"
    metadata = {
        "domain": domains,
        "tags": tags,
        "name": name,
        "valence": _unit_float(analysis.get("valence"), 0.5),
        "arousal": _unit_float(analysis.get("arousal"), 0.3),
    }
    return dynamic_dir / primary / filename, metadata


async def reclassify(
    config: Mapping[str, Any] | None = None,
    *,
    analyzer: Analyzer | None = None,
    emit: Emit = print,
) -> dict[str, int]:
    """Reclassify every legacy bucket and return machine-readable counters."""

    resolved_config = dict(config or load_config())
    dynamic_dir = Path(str(resolved_config.get("buckets_dir") or "buckets")) / "dynamic"
    unclassified_dir = dynamic_dir / "unclassified"
    legacy_cn_dir = dynamic_dir / "未分类"
    source_dirs = [path for path in (unclassified_dir, legacy_cn_dir) if path.is_dir()]
    files = sorted(
        path
        for source_dir in source_dirs
        for path in source_dir.glob("*.md")
        if path.is_file()
    )
    summary = {"found": len(files), "updated": 0, "failed": 0, "skipped": 0}
    emit(f"Found {len(files)} unclassified bucket(s).")
    if not files:
        return summary

    active_analyzer = analyzer or Dehydrator(resolved_config)
    for source in files:
        try:
            post = frontmatter.load(source)
            original_content = post.content
            old_name = str(post.metadata.get("name") or "")
            analysis = await active_analyzer.analyze(
                f"{old_name}\n{original_content}"[:2000]
                if old_name
                else original_content[:2000]
            )
            if not isinstance(analysis, Mapping):
                raise ValueError("analyzer result must be an object")
            destination, metadata = _target_path(
                dynamic_dir,
                post,
                source,
                analysis,
            )
            if destination != source and destination.exists():
                raise FileExistsError(
                    f"destination already exists; source was left untouched: {destination}"
                )

            for key, value in metadata.items():
                post.metadata[key] = value
            if post.content != original_content:
                raise RuntimeError("stored content changed before serialization")

            destination.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(str(destination), frontmatter.dumps(post))
            if destination != source:
                source.unlink()
            summary["updated"] += 1
            emit(f"OK {source.name} -> {destination.relative_to(dynamic_dir)}")
        except Exception as exc:
            summary["failed"] += 1
            emit(f"ERROR {source.name}: {exc}")

    for source_dir in source_dirs:
        try:
            source_dir.rmdir()
        except OSError:
            pass
    return summary


if __name__ == "__main__":
    asyncio.run(reclassify())
>>>>>>> upstream/main
