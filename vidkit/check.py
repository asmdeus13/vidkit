# -*- coding: utf-8 -*-
"""vidkit.check —— 画面验收：给一个视频，出一张判读表

判据（本机实测标定，可改）：
    地板绿斑%   < 0.20 干净   |  > 0.35 有问题
    镜内漂移    < 12  稳      |  > 20  在抖
    亮度漂移    < 15  稳      |  > 25  光在跳
    帧间差突变  > 10 且非切点 => 闪
"""
import sys

import numpy as np

from . import metrics


THRESH = {
    "green":  {"clean": 0.20, "bad": 0.35},
    "drift":  {"clean": 12.0, "bad": 20.0},
    "lumdrift": {"clean": 15.0, "bad": 25.0},
    "jump":   {"clean": 10.0, "bad": 10.0},
}


def _mark(value, clean, bad, lower_better=True):
    if lower_better:
        if value <= clean:
            return "OK "
        if value <= bad:
            return "WARN"
        return "BAD "
    else:
        if value >= clean:
            return "OK "
        if value >= bad:
            return "WARN"
        return "BAD "


def run(path, fps=2.0, width=480, expect_shots=0, verbose=True):
    info = metrics.probe(path)
    frames = metrics.grab_frames(path, fps, width=width)
    if len(frames) < 2:
        raise RuntimeError("抽到的帧太少（%d）" % len(frames))

    diffs = metrics.frame_diffs(frames)
    # 不传绝对阈值 ⇒ 用自适应（相对本片分布），否则高运动片会全部超标
    cuts = metrics.cut_points(diffs)

    # 如果有预期镜数，按等分推算镜边界，跟检测到的切点对一下
    guessed = []
    if expect_shots > 1:
        per = len(frames) / float(expect_shots)
        guessed = [int(round(k * per)) for k in range(1, expect_shots)]
        # 等分边界不是切点的，说明这两镜接得很软（同景别连续动作）
        soft = [g for g in guessed if not any(abs(g - c) <= 2 for c in cuts)]
    else:
        soft = []

    drift = metrics.intra_drift(diffs, cuts)
    greens = [metrics.green_blotch(f) for f in frames]
    lums = [metrics.lum_stats(f)["mean"] for f in frames]
    drift_color = metrics.color_drift(frames)

    lum_drift = max(lums) - min(lums)
    inner = [d for i, d in enumerate(diffs) if i > 0 and i not in cuts]
    med_inner = float(np.median(inner)) if inner else 0.0
    jump_thr = max(med_inner * 2.0, float(np.median(diffs)) * 1.6, 10.0)
    jumps = [d for i, d in enumerate(diffs) if i > 0 and i not in cuts and d > jump_thr]

    if not verbose:
        return {
            "info": info, "green": float(np.mean(greens)), "drift": drift,
            "lum_drift": lum_drift, "jumps": jumps, "cuts": cuts,
        }

    print("  视频    %dx%d  %.2fs  %.1ffps  %d 帧"
          % (info["w"], info["h"], info["duration"], info["fps"], info["frames"]))
    print("  抽帧    %.1ffps 宽 %d  → %d 帧" % (fps, width, len(frames)))
    print()
    print("  指标              值            判读      阈值(干净/有问题)")
    print("  ----------------  ------------  --------  ----------------")
    g = float(np.mean(greens))
    print("  地板绿斑%%         %8.3f      %s      < %.2f / > %.2f"
          % (g, _mark(g, THRESH["green"]["clean"], THRESH["green"]["bad"]),
             THRESH["green"]["clean"], THRESH["green"]["bad"]))
    print("  镜内漂移           %8.1f      %s      < %.0f / > %.0f"
          % (drift, _mark(drift, THRESH["drift"]["clean"], THRESH["drift"]["bad"]),
             THRESH["drift"]["clean"], THRESH["drift"]["bad"]))
    print("  亮度漂移           %8.1f      %s      < %.0f / > %.0f"
          % (lum_drift, _mark(lum_drift, THRESH["lumdrift"]["clean"], THRESH["lumdrift"]["bad"]),
             THRESH["lumdrift"]["clean"], THRESH["lumdrift"]["bad"]))
    print("  最大帧间差         %8.1f      %s      < %.0f / > %.0f"
          % (max(diffs), "—", THRESH["jump"]["clean"], THRESH["jump"]["bad"]))
    print("  色彩漂移(末帧)     %8.1f      %s      < 3 / > 8"
          % (drift_color[-1], _mark(drift_color[-1], 3.0, 8.0)))
    print()
    # ⚠️ 局限说明：帧间差判切镜只在「低运动片」可靠。
    #   每帧都在动的高运动片（帧间差中位数 30+），镜内值和镜间值叠在一起，分不开。
    #   所以：给了 --shots 就按等分边界报峰值（这是可控的）；没给就明说不可靠。
    if expect_shots > 1:
        print("  按 --shots %d 的等分边界逐个看帧间差：" % expect_shots)
        for gg in guessed:
            if 0 <= gg < len(diffs):
                inner_local = [diffs[i] for i in range(max(1, gg - 3), min(len(diffs), gg + 4))
                               if i != gg]
                base = float(np.median(inner_local)) if inner_local else 0.0
                ratio = diffs[gg] / base if base > 1e-6 else 0.0
                tag = "切镜" if ratio >= 1.8 else ("软接" if ratio >= 1.15 else "无切")
                print("    帧 %-4d 差 %5.1f  邻域中位 %5.1f  比值 %.2f  → %s"
                      % (gg, diffs[gg], base, ratio, tag))
    else:
        print("  ⚠️ 未给 --shots，跳过了切镜判定。")
        print("     原因：帧间差判切镜只在低运动片可靠；每帧都在动的高运动片分不开。")
        print("     要看切镜请加 --shots <镜头数>，或直接看抽帧拼图。")
    if jumps:
        print("  ⚠️ 非切点的帧间突变 %d 处（可能是闪）：%s"
              % (len(jumps), [round(x, 1) for x in jumps[:8]]))
    else:
        print("  ✅ 没有非切点的帧间突变")

    bad = []
    if g > THRESH["green"]["bad"]:
        bad.append("地板绿斑超标 → 检查三针锚点是不是「同一条轨迹上的点」，"
                   "或改用 3 针（4 针容易把「想动但没空间」释放成色斑）")
    if drift > THRESH["drift"]["bad"]:
        bad.append("镜内在抖 → 检查首帧与末帧的构图差异，或换 seed 重跑")
    if lum_drift > THRESH["lumdrift"]["bad"]:
        bad.append("亮度在跳 → 多镜拼接前做逐通道对齐（见 vidkit color）")
    if jumps:
        bad.append("有非切点突变 → 多半是两镜构图太像、模型在接缝处重画")

    if bad:
        print()
        print("  建议：")
        for b in bad:
            print("    · " + b)
    return {"green": g, "drift": drift, "lum_drift": lum_drift, "bad": bad}
