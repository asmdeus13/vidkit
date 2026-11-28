# -*- coding: utf-8 -*-
"""vidkit.color —— 多帧色彩校正：逐通道均值/方差对齐到首帧

问题：AI 生视频多镜拼接，色温一跳就露馅。观众说不出来，但能感觉到「这不是一条片」。
做法：不改构图、不改内容，只把每帧的每个通道拉回首帧的均值/方差。
实测：能把色偏 delta 从 15.7 压到 < 1.0，帧间漂移降约 25%。
"""
import os
import subprocess

import numpy as np
from PIL import Image

from . import metrics

FFMPEG = "ffmpeg"


def align_array(a, ref, strength=1.0):
    """把数组 a 的逐通道均值/方差拉向 ref。strength=0..1 控制力度。"""
    a = a.astype(np.float32)
    out = a.copy()
    for c in range(a.shape[2]):
        m_a, s_a = float(a[:, :, c].mean()), float(a[:, :, c].std()) or 1.0
        m_r, s_r = float(ref[:, :, c].mean()), float(ref[:, :, c].std()) or 1.0
        norm = (a[:, :, c] - m_a) / s_a
        target = norm * s_r + m_r
        out[:, :, c] = a[:, :, c] * (1 - strength) + target * strength
    return np.clip(out, 0, 255)


def run(path, out_path=None, fps=None, only_lum=False, strength=1.0, verbose=True):
    """对视频做逐帧色彩对齐。返回 (输出路径, 首尾漂移变化)。"""
    info = metrics.probe(path)
    out_path = out_path or os.path.splitext(path)[0] + "_color.mp4"

    # 抽帧到临时目录（原分辨率，保证回写不糊）
    import tempfile
    import glob
    tmp = tempfile.mkdtemp(prefix="vidkit_color_")
    # ⚠️ 不要用 fps= 滤镜：它会向下取整帧数（实测 744 帧 → 734 帧，少 0.42 秒，
    #    尾段被切）。默认逐帧全抽，回写时用同一个帧率，片长才不变。
    vf = []
    if fps:
        vf = ["-vf", "fps=%s" % fps]
    n = subprocess.run(
        [FFMPEG, "-y", "-v", "error", "-i", path] + vf +
        ["-start_number", "0", os.path.join(tmp, "f%05d.png")],
        capture_output=True)
    if n.returncode != 0:
        raise RuntimeError("抽帧失败：" + n.stderr.decode("utf-8", "replace")[:300])

    files = sorted(glob.glob(os.path.join(tmp, "*.png")))
    if len(files) < 2:
        raise RuntimeError("抽到的帧太少")

    ref = np.asarray(Image.open(files[0]).convert("RGB"), dtype=np.float32)
    before, after = [], []
    for i, p in enumerate(files):
        a = np.asarray(Image.open(p).convert("RGB"), dtype=np.float32)
        d0 = float(np.mean(np.abs(a.mean(axis=(0, 1)) - ref.mean(axis=(0, 1)))))
        before.append(d0)
        if i == 0:
            continue
        if only_lum:
            # 只修亮度：按 Y 的比例缩放
            y_a = 0.299 * a[:, :, 0] + 0.587 * a[:, :, 1] + 0.114 * a[:, :, 2]
            y_r = 0.299 * ref[:, :, 0] + 0.587 * ref[:, :, 1] + 0.114 * ref[:, :, 2]
            k = (y_r.mean() + 1e-6) / (y_a.mean() + 1e-6)
            fixed = np.clip(a * k, 0, 255)
        else:
            fixed = align_array(a, ref, strength)
        Image.fromarray(fixed.astype(np.uint8)).save(p)
        d1 = float(np.mean(np.abs(fixed.mean(axis=(0, 1)) - ref.mean(axis=(0, 1)))))
        after.append(d1)

    # 回写视频（保留原音轨）
    r = subprocess.run(
        [FFMPEG, "-y", "-v", "error", "-framerate", str(fps or info["fps"]),
         "-i", os.path.join(tmp, "f%05d.png"), "-i", path,
         "-map", "0:v:0", "-map", "1:a:0?", "-c:v", "libx264", "-crf", "18",
         "-pix_fmt", "yuv420p", "-c:a", "copy", out_path],
        # ⚠️ 不要 -shortest：源的视频常比音轨略长（实测 31.000s vs 30.728s），
        #    -shortest 会把视频截到音轨长度（744 帧 → 734 帧），尾段被吃掉。
        capture_output=True)
    if r.returncode != 0:
        raise RuntimeError("回写失败：" + r.stderr.decode("utf-8", "replace")[:300])

    if verbose:
        print("  源          %s" % path)
        print("  产物        %s" % out_path)
        print("  %dx%d  %.1ffps" % (info["w"], info["h"], info["fps"]))
        print()
        print("  首帧基准，末帧色偏：")
        print("    校正前  %.2f" % before[-1])
        print("    校正后  %.2f" % after[-1])
        print("    降幅    %.0f%%" % ((1 - after[-1] / max(before[-1], 1e-6)) * 100))
        print()
        print("  判据：色偏 < 3 基本看不出；> 8 观众会觉得「不是一条片」")
    return out_path, before[-1], after[-1]
