#!/usr/bin/env python3
"""检查发布包中现役非脚本文本的中文化完整性。"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {".md", ".html", ".htm", ".toml", ".json", ".yaml", ".yml", ".txt"}
EXCLUDED_PARTS = {".git", "scripts", "node_modules", "__pycache__", "dist", "build"}
MACHINE_KEYS = {
    "name", "type", "codename", "area", "layer", "target_file", "created", "updated",
    "version", "status", "project", "model", "model_reasoning_effort", "sandbox_mode",
    "nickname_candidates", "archived", "archived_date", "matcher", "command", "timeout",
    "CLAUDE_CODE_SUBAGENT_MODEL",
}
FORBIDDEN_PATHS = {
    "<ASSISTANT_ROOT>": "<WORKSPACE_ROOT>",
    "assistant/": "workspace/",
    "00 专注区": "00 Focus Zone",
    "01 项目区": "01 Projects Zone",
    "02 阅读区": "05 Reading Zone",
    "03 写作区": "06 Writing Zone",
    "00.专注区_agent.md": "00.focus_zone_canon.md",
    "00.项目区_agent.md": "00.projects_canon.md",
    "00.阅读区_agent.md": "00.reading_canon.md",
    "00.写作区_agent.md": "00.writing_canon.md",
    "_本周.md": "_current.md",
    "长期记忆.md": "Long_Term_Memory/status.md",
    "助手根目录": "工作空间根目录",
    "助手目录（`workspace/`）": "工作空间目录（`workspace/`）",
    "MetaScale": "元技能系统",
    "UltraScale": "元编排系统",
    "Black Box 端": "Claude Code 端",
    "Black Box 版预测生成": "Claude Code 版预测生成",
    "<WORKSPACE_ROOT>\\": "<WORKSPACE_ROOT>/",
    "<CLAUDE_HOME>\\": "<CLAUDE_HOME>/",
    "<CODEX_HOME>\\": "<CODEX_HOME>/",
    "MEMORY\\": "MEMORY/",
    "SOUL\\": "SOUL/",
    "USER\\": "USER/",
    "Long_Term_Memory\\": "Long_Term_Memory/",
    "`长期记忆`": "`Long_Term_Memory`",
}
FORBIDDEN_HEADINGS = re.compile(
    r"^\s*#{1,6}\s+(?:daily-dream|weekly-dream|quarterly-archive|week-sync|close-node|"
    r"create-project|write-progress|new-file|meta-skill|storage-agent|general-search-agent)\s*$",
    re.IGNORECASE,
)
RAW_NARRATIVE_TERMS = re.compile(
    r"(?<![A-Za-z0-9_-])(?:dreaming|dream|semantic|episodic|schema|prompt|workflow|eval|evaluation|grader|"
    r"comparator|analyzer|sub-agent|subagent|archive|log|case|baseline|artifact|assertion|"
    r"workspace|phase|skill|hook|agent|detect|execute|automation|thread|session|turn|progress|"
    r"headless|compact|feature|verdict|near-miss|held-out|smoke)(?![A-Za-z0-9_-])",
    re.IGNORECASE,
)
ENGLISH_SECTION_HEADINGS = re.compile(
    r"^\s*#{1,6}\s+(?:workflow|inputs?|outputs?|boundaries|upstream|downstream|peers?|"
    r"daily review|weekly review|session search|general search agent)\b",
    re.IGNORECASE,
)
ENGLISH_WORD = re.compile(r"[A-Za-z][A-Za-z-]+")
CJK = re.compile(r"[\u3400-\u9fff]")
INLINE_CODE = re.compile(r"`[^`]*`")
INLINE_MATH = re.compile(r"\$[^$]+\$")
MARKDOWN_LINK_TARGET = re.compile(r"\]\([^)]*\)")
PAREN_GLOSS = re.compile(r"[（(][^（）()\u3400-\u9fff]*[A-Za-z][^（）()\u3400-\u9fff]*[）)]")
URL = re.compile(r"https?://\S+")
DOLLAR_IDENTIFIER = re.compile(r"\$[A-Za-z][\w-]*")
HTML_BLOCK = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
HTML_TAG = re.compile(r"<[^>]+>")
HUMAN_METADATA = re.compile(
    r'^\s*["\']?(title|display_name|short_description|description)["\']?\s*[:=]\s*["\']?(.*?)["\']?\s*,?\s*$'
)


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int
    reason: str
    excerpt: str

    def render(self, root: Path = ROOT) -> str:
        rel = self.path.relative_to(root)
        return f"{rel}:{self.line}: {self.reason}: {self.excerpt.strip()}"


def active_surface_files(root: Path = ROOT) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if (not path.is_file()
                or (path.suffix.lower() not in TEXT_SUFFIXES and path.name != "LICENSE")):
            continue
        rel = path.relative_to(root)
        if any(part in EXCLUDED_PARTS for part in rel.parts):
            continue
        files.append(path)
    return sorted(files)


def strip_markdown_fences(lines: list[str]) -> list[tuple[int, str]]:
    visible: list[tuple[int, str]] = []
    in_fence = False
    in_frontmatter = bool(lines and lines[0].strip() == "---")
    in_sources = False
    for lineno, line in enumerate(lines, 1):
        stripped = line.strip()
        if in_frontmatter:
            if lineno > 1 and stripped == "---":
                in_frontmatter = False
                continue
            key_match = re.match(r"^([A-Za-z_][\w.-]*)\s*:\s*(.*)$", line)
            if key_match and key_match.group(1) not in MACHINE_KEYS:
                visible.append((lineno, key_match.group(2)))
            continue
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        heading = re.match(r"^\s*#{1,6}\s+(.+?)\s*$", line)
        if heading:
            title = heading.group(1)
            if re.match(r"^(?:参考文献|资料来源|bibliography|references)(?:\s|$)", title, re.IGNORECASE):
                in_sources = True
            if in_sources:
                continue
            visible.append((lineno, line))
            continue
        if in_sources:
            continue
        visible.append((lineno, line))
    return visible


def normalize_human_text(line: str) -> str:
    line = INLINE_CODE.sub("", line)
    line = INLINE_MATH.sub("", line)
    line = MARKDOWN_LINK_TARGET.sub("]", line)
    line = URL.sub("", line)
    line = DOLLAR_IDENTIFIER.sub("", line)
    previous = None
    while previous != line:
        previous = line
        line = PAREN_GLOSS.sub("", line)
    return line


def visible_lines(path: Path, body: str) -> list[tuple[int, str]]:
    if path.name == "LICENSE":
        chinese_lead = body.split("--- MIT 许可证 · 英文法律原文 ---", 1)[0]
        return list(enumerate(chinese_lead.splitlines(), 1))
    if path.suffix.lower() == ".md":
        return strip_markdown_fences(body.splitlines())
    if path.suffix.lower() in {".html", ".htm"}:
        cleaned = HTML_COMMENT.sub("", body)
        cleaned = HTML_BLOCK.sub("", cleaned)
        return [(i, HTML_TAG.sub(" ", line)) for i, line in enumerate(cleaned.splitlines(), 1)]
    result: list[tuple[int, str]] = []
    for lineno, line in enumerate(body.splitlines(), 1):
        assignment = re.match(r'^\s*["\']?([A-Za-z_][\w.-]*)["\']?\s*[:=]\s*(.*)$', line)
        if assignment and assignment.group(1) in MACHINE_KEYS:
            continue
        result.append((lineno, line))
    return result


def audit_file(path: Path) -> list[Finding]:
    findings: list[Finding] = []
    try:
        body = path.read_text(encoding="utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        return [Finding(path, exc.start, "UTF-8 解码失败", str(exc))]
    if "\ufffd" in body:
        findings.append(Finding(path, 1, "含 U+FFFD 替换字符", "文件编码已损坏"))
    if path.suffix.lower() == ".md":
        for lineno, original in enumerate(body.splitlines(), 1):
            if re.match(r"^#{1,6}[^#\s]", original):
                findings.append(Finding(path, lineno, "Markdown 标题标记后缺少空格，锚点不会生效", original))
    for lineno, original in enumerate(body.splitlines(), 1):
        metadata = HUMAN_METADATA.match(original)
        if not metadata:
            continue
        value = normalize_human_text(metadata.group(2))
        if ENGLISH_WORD.search(value) and not CJK.search(value):
            findings.append(Finding(path, lineno, "面向用户的元数据缺少中文名称", original))
    for old, new in FORBIDDEN_PATHS.items():
        for match in re.finditer(re.escape(old), body):
            line = body.count("\n", 0, match.start()) + 1
            findings.append(Finding(path, line, f"旧路径或旧称，应改为 {new}", old))
    for lineno, original in visible_lines(path, body):
        if FORBIDDEN_HEADINGS.search(original):
            findings.append(Finding(path, lineno, "标题缺少中文名称", original))
            continue
        if ENGLISH_SECTION_HEADINGS.search(original):
            findings.append(Finding(path, lineno, "英文节标题未中文化", original))
        human = normalize_human_text(original)
        if re.match(r"^\s*#{1,6}\s+", original) and ENGLISH_WORD.search(human) and not CJK.search(human):
            findings.append(Finding(path, lineno, "标题仅有英文可见名称", original))
        words = ENGLISH_WORD.findall(human)
        if len(words) >= 4 and not CJK.search(human):
            findings.append(Finding(path, lineno, "整行英文叙述未中文化", original))
        match = RAW_NARRATIVE_TERMS.search(human)
        if match:
            findings.append(Finding(path, lineno, f"正文裸露英文术语 {match.group(0)!r}", original))
    return findings


def audit(root: Path = ROOT) -> list[Finding]:
    findings: list[Finding] = []
    for path in active_surface_files(root):
        findings.extend(audit_file(path))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="审计发布包非脚本文本的中文化完整性")
    parser.add_argument("--root", type=Path, default=ROOT, help="仓库根目录")
    args = parser.parse_args()
    root = args.root.resolve()
    findings = audit(root)
    if findings:
        print(f"中文化表面审计失败：{len(findings)} 项")
        for finding in findings:
            print(finding.render(root))
        return 1
    files = active_surface_files(root)
    print(f"中文化表面审计通过：{len(files)} 个发布包非脚本文本文件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
