# -*- coding: utf-8 -*-
"""vidkit.voice —— 配音时长适配：把 TTS 出来的 wav 对齐到镜头长度

核心结论（实测踩出来的）：
    目标时长 = 镜长 − 0.28 秒     ← 不是 − 0.06，不是 − 0.17
    留 0.28 秒余量，最后一个字才不会被镜边界切掉。

为什么用 atempo 而不是重采样：
    线性插值重采样会同时移调（12*log2(rate) 个半音）；
    ffmpeg 的 atempo 是时间伸缩，音高不变。
"""
import os
import shutil
import subprocess
import tempfile

import numpy as np
import soundfile as sf

FFMPEG = "ffmpeg"


def ff_tempo(src, dst, rate):
    """真 atempo（保音高）。rate>2 时串联多级。"""
    chain, r = [], rate
    while r > 2.0:
        chain.append("atempo=2.0"); r /= 2.0
    while r < 0.5:
        chain.append("atempo=0.5"); r /= 0.5
    chain.append("atempo=%.4f" % r)
    subprocess.run([FFMPEG, "-y", "-v", "error", "-i", src,
                    "-filter:a", ",".join(chain), dst], capture_output=True)
    return os.path.exists(dst)


def tail_margin(path):
    """返回 (时长秒, 最后有声位置秒, 到末尾的余量秒)。"""
    w, sr = sf.read(path)
    if w.ndim > 1:
        w = w.mean(axis=1)
    dur = len(w) / float(sr)
    hop = max(int(sr * 0.02), 1)
    rms = [float(np.sqrt(np.mean(w[k:k + hop] ** 2))) for k in range(0, len(w) - hop, hop)]
    if not rms:
        return dur, dur, 0.0
    peak = max(rms) or 1e-9
    thr = peak * 0.02
    last = 0
    for i, v in enumerate(rms):
        if v > thr:
            last = i
    last_t = last * (hop / float(sr))
    return dur, last_t, dur - last_t


def normalize(path, peak=0.89):
    w, sr = sf.read(path)
    if w.ndim > 1:
        w = w.mean(axis=1)
    p = float(np.max(np.abs(w))) or 1.0
    return w / p * peak, sr


def run(wav, shot_sec, out=None, margin=0.28, lo=0.85, hi=1.45, verbose=True):
    """把 wav 适配到 shot_sec 秒的镜长。返回结果 dict。"""
    raw_dur, _, _ = tail_margin(wav)
    target = shot_sec - margin
    need = raw_dur / target
    use = min(max(need, lo), hi)

    out = out or os.path.join(
        os.path.dirname(wav), "_fit_" + os.path.basename(wav))

    if abs(use - 1.0) < 0.012:
        shutil.copy(wav, out)
    else:
        ff_tempo(wav, out, use)

    dur, last, margin_now = tail_margin(out)
    ok = (dur <= shot_sec - 0.05) and (margin_now >= 0.15)

    if verbose:
        print("  源      %.2fs" % raw_dur)
        print("  镜长    %.2fs" % shot_sec)
        print("  目标    %.2fs  （= 镜长 − %.2f）" % (target, margin))
        print("  需倍率  %.2f×  →  实用 %.2f×" % (need, use))
        if need > hi:
            print("    ⚠️ 需要 %.2f× 但上限是 %.2f× ⇒ 会被截断或留白；"
                  "建议缩短文案，别硬加速" % (need, hi))
        elif need < lo:
            print("    ⚠️ 需要放慢到 %.2f× 但下限是 %.2f× ⇒ 会被拉伸" % (need, lo))
        print("  产物    %s" % out)
        print("  调后    %.2fs" % dur)
        print("  余量    %.2fs  %s" % (margin_now, "OK" if ok else "⚠️ 偏小，最后一个字有被切风险"))
        print()
        print("  判据：余量 >= 0.15s 才算安全（0.05s 那种就是踩过坑的值）")

    return {"out": out, "dur": dur, "margin": margin_now, "rate": use, "ok": ok}
