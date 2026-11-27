# 发布前扫密钥（scan_secrets.py）
# 用途：把仓库里所有待提交文件扫一遍，命中任何密钥模式就失败退出。
# 顺序很重要：**先扫，再 git init + 第一次 commit**。
# 因为一旦密钥进过 git 历史，后来删文件也删不掉 —— 历史里永远留着。

import io
import os
import re
import sys

# 这些模式是"一眼就是密钥"的高置信规则
PATTERNS = [
    ("openai/sk",      re.compile(r"sk-[A-Za-z0-9_\-]{20,}")),
    ("anthropic",      re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")),
    ("github-pat",     re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}")),
    ("aws-akid",       re.compile(r"AKIA[0-9A-Z]{16}")),
    ("slack",          re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}")),
    ("google-api",     re.compile(r"AIza[0-9A-Za-z_\-]{35}")),
    ("generic-bearer", re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]{30,}")),
    # 长的十六进制串（很多国内中转站的 key 是 32/64 位 hex）
    ("hex-32plus",     re.compile(r"\b[0-9a-fA-F]{32,}\b")),
]

# 这些行就算命中也不算（注释里的示例、明显的占位符）
WHITELIST_LINE = [
    "YOUR_KEY", "YOUR_API_KEY", "xxx", "XXXX", "<", ">",
    "example", "placeholder", "sk-xxx", "replace_me",
]

EXCLUDE_DIRS = {".git", "__pycache__", "node_modules", "output", ".venv", "venv"}
EXCLUDE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".mov",
               ".wav", ".mp3", ".safetensors", ".gguf", ".ckpt", ".pt", ".pth"}


def walk(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for fn in filenames:
            ext = os.path.splitext(fn)[1].lower()
            if ext in EXCLUDE_EXT:
                continue
            yield os.path.join(dirpath, fn)


def is_safe_ext(ext):
    return ext in {".md", ".txt", ".py", ".js", ".mjs", ".json", ".yml", ".yaml",
                   ".toml", ".cfg", ".ini", ".sh", ".ps1", ".bat", ".cmd", ""}


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    root = os.path.abspath(root)
    hits = []
    scanned = 0

    for path in walk(root):
        ext = os.path.splitext(path)[1].lower()
        if not is_safe_ext(ext):
            continue
        try:
            with io.open(path, "r", encoding="utf-8", errors="replace") as f:
                for lineno, line in enumerate(f, 1):
                    scanned += 1
                    if any(w in line for w in WHITELIST_LINE):
                        continue
                    for name, rx in PATTERNS:
                        if rx.search(line):
                            hits.append((path, lineno, name, line.strip()[:120]))
                            break
        except Exception as e:
            print("  [skip] %s (%s)" % (path, e))

    print("  扫了 %d 行，%d 个文件" % (scanned, len(list(walk(root)))))
    if hits:
        print("\n  ❌ 命中 %d 处，**不许提交**：" % len(hits))
        for path, lineno, name, snippet in hits:
            rel = os.path.relpath(path, root)
            print("    %s:%d  [%s]  %s" % (rel, lineno, name, snippet))
        print("\n  处理办法：把密钥移到环境变量或本地 config（已在 .gitignore 里），")
        print("  代码里只留 os.environ.get('XXX') 这类读取。")
        return 1

    print("  ✅ 零命中，可以 git init")
    return 0


if __name__ == "__main__":
    sys.exit(main())
