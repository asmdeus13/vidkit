# -*- coding: utf-8 -*-
"""vidkit.plint —— 提示词连贯化检查器

市面上全是「提示词生成器」，没有「提示词检查器」。
这六条是从真踩的坑里长出来的，判据都是「有没有可执行描述」，不是「有没有提到相关词」。

    ① 头部动作     有没有写清某个时刻头转向哪 / 视线落在哪
    ② 反站桩       有没有明确「身体不冻结」的条款
    ③ 运镜可执行   镜头运动有没有给数值（画面宽度百分比 / 角度）
    ④ 时间坐标     有没有 0 / 中 / 尾三个时刻的状态
    ⑤ 接住上一镜   第一句有没有写从上一镜的什么状态来
    ⑥ 正向写法     「不要做什么」有没有改写成「该做什么」
"""
import re
import sys


# 每条：(名字, 通过判据的 regex 列表（任一命中即算"有"）, 反向信号（命中说明写错了）)
RULES = [
    (
        "① 头部动作",
        [r"\bhead\b", r"\bchin\b", r"\bgaze\b", r"\beyes?\b.{0,20}(on|at|toward)",
         r"头部", r"视线", r"下巴", r"看向"],
        [],
    ),
    (
        "② 反站桩",
        [r"never\s+frozen", r"body is not (static|frozen)", r"breath",
         r"weight shifts?", r"身体不(会)?僵", r"呼吸"],
        [],
    ),
    (
        "③ 运镜可执行",
        [r"\d+\s*%\s*(of (the )?frame)", r"about\s+\d+\s*deg", r"\d+\s*(%|percent)",
         r"画面.{0,6}%", r"约\s*\d+\s*(度|%)"],
        [r"(?i)\b(slowly|subtle|subtly|gentle|gently|slight|slightly)\b(?!.*\d)"],
    ),
    (
        "④ 时间坐标",
        [r"\b0(\.0+)?\s*s(ec|econds)?\b", r"\d+\.\d+\s*s(ec|econds)?\b",
         r"by the (last|final) frame", r"首帧", r"末帧", r"中锚点"],
        [],
    ),
    (
        "⑤ 接住上一镜",
        [r"(?i)continuing from", r"(?i)previous shot", r"(?i)opening shot",
         r"接着上一镜", r"上一镜", r"全片开头"],
        [],
    ),
    (
        "⑥ 正向写法",
        [r"(?i)\b(eyes? (are|is) on|gaze (is )?(fixed|locked) on|looking at)\b"],
        [r"(?i)\b(do not|don't|never|avoid|no)\s+(look|smile|stare)"],
    ),
]


def _hits(text, patterns):
    out = []
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            out.append(m.group(0)[:40])
    return out


def run(path_or_text, verbose=True):
    if isinstance(path_or_text, str) and "\n" not in path_or_text and len(path_or_text) < 400:
        try:
            text = open(path_or_text, encoding="utf-8").read()
            src = path_or_text
        except OSError:
            text = path_or_text
            src = "(inline)"
    else:
        text = path_or_text
        src = "(inline)"

    results = []
    for name, good, bad in RULES:
        g = _hits(text, good)
        b = _hits(text, bad)
        if g and not b:
            st = "有"
        elif g and b:
            st = "半有"
        else:
            st = "没有"
        results.append((name, st, g, b))

    if verbose:
        print("  检查  %s  （%d 字符）" % (src, len(text)))
        print()
        for name, st, g, b in results:
            mark = {"有": "OK  ", "半有": "WARN", "没有": "MISS"}[st]
            print("  %s  %-12s  %s" % (mark, name, st))
            if g:
                print("        命中：" + " / ".join(g[:3]))
            if b:
                print("        ⚠️ 反向信号：" + " / ".join(b[:3]))

        n_ok = sum(1 for _, s, _, _ in results if s == "有")
        print()
        print("  合计 %d/6 条齐" % n_ok)

        missing = [name for name, s, _, _ in results if s != "有"]
        if missing:
            print()
            print("  该补的：")
            advice = {
                "① 头部动作": "加一句：某个时刻她的头转向哪、或视线落在哪（不是只有手在动）",
                "② 反站桩": "加一句：The body is never frozen: chest rises and falls with breathing, weight shifts...",
                "③ 运镜可执行": "把 slowly/subtle 换成数值：推进 约 20% 画面宽 / 俯摇 约 35 度",
                "④ 时间坐标": "补三个时刻：0.00s / 2.58s / 5.125s 各是什么状态",
                "⑤ 接住上一镜": "第一句写 Continuing from the previous shot: <上一镜末帧状态>（首镜写 opening shot）",
                "⑥ 正向写法": "把「不要看镜头」改成「她的眼睛看着自己的手」",
            }
            for m in missing:
                print("    · %s —— %s" % (m, advice.get(m, "")))
        else:
            print()
            print("  六条齐了，可以直接跑。")

    return results
