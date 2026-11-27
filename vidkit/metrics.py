# -*- coding: utf-8 -*-
"""vidkit.metrics —— 六项指标（五个子命令共用这一层）

这些指标不是凭空挑的，是踩出来的：
  · 地板绿斑  —— 生视频模型在"想动但没空间动"时会释放成色斑
  · 帧间差    —— 判"切镜"还是"连续运动"；也是判抖动的基准
  · 亮度分布  —— 判光比结构，跟参考对不上就露馅
  · 白色占比  —— 云、雾、光、留白；说"云气太薄"其实是在说这个数低
  · 边缘密度  —— 材质复杂度；程序化噪声补不到真实材质那一档
  · 色彩漂移  —— 多镜拼接的色温跳变
"""
import subprocess

import numpy as np
from PIL import Image

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"


def probe(path):
    """返回 dict(w, h, fps, frames, duration)。失败抛异常。"""
    r = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,r_frame_rate,nb_frames,duration",
         "-of", "default=nw=1", path],
        capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("ffprobe 失败：" + r.stderr[:300])
    d = {}
    for line in r.stdout.strip().split("\n"):
        if "=" in line:
            k, v = line.split("=", 1)
            d[k.strip()] = v.strip()
    num, den = (d.get("r_frame_rate", "24/1").split("/") + ["1"])[:2]
    return {
        "w": int(d.get("width", 0)),
        "h": int(d.get("height", 0)),
        "fps": float(num) / float(den or 1),
        "frames": int(float(d.get("nb_frames", 0) or 0)),
        "duration": float(d.get("duration", 0) or 0),
    }


def grab_frames(path, fps, width=None, outdir=None):
    """抽帧，返回 PIL Image 列表。width=None 表示原分辨率。"""
    import os
    import tempfile
    outdir = outdir or tempfile.mkdtemp(prefix="vidkit_")
    vf = "fps=%s" % fps
    if width:
        vf += ",scale=%d:-1" % width
    r = subprocess.run(
        [FFMPEG, "-y", "-v", "error", "-i", path, "-vf", vf,
         "-f", "image2", os.path.join(outdir, "f%05d.png")],
        capture_output=True)
    if r.returncode != 0:
        raise RuntimeError("抽帧失败：" + r.stderr.decode("utf-8", "replace")[:300])
    import glob
    return [Image.open(p).convert("RGB") for p in sorted(glob.glob(os.path.join(outdir, "*.png")))]


def _arr(im, resize=None):
    if resize:
        im = im.resize(resize, Image.BILINEAR)
    return np.asarray(im, dtype=np.float32)


def green_blotch(im, region="floor"):
    """地板绿斑占比（%）。

    region="floor" 只量画面下半 28% —— 因为全画面量会把植物算进去，误报。
    """
    a = _arr(im)
    h = a.shape[0]
    if region == "floor":
        a = a[int(h * 0.72):, :, :]
    R, G, B = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    lum = (R + G + B) / 3.0
    mask = (G > R + 20) & (G > B + 18) & (lum > 60)
    return float(mask.mean() * 100.0)


def white_ratio(im):
    """白色（云/雾/光/留白）占比 %。"""
    a = _arr(im)
    R, G, B = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    lum = 0.299 * R + 0.587 * G + 0.114 * B
    mx = a.max(axis=2)
    mn = a.min(axis=2)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0)
    return float((((lum > 170) & (sat < 0.18)).mean()) * 100.0)


def lum_stats(im):
    """亮度均值 / 标准差 / 暗中亮三段占比。"""
    a = _arr(im)
    R, G, B = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    lum = 0.299 * R + 0.587 * G + 0.114 * B
    return {
        "mean": float(lum.mean()),
        "std": float(lum.std()),
        "dark": float((lum < 40).mean() * 100),
        "mid": float(((lum >= 40) & (lum < 140)).mean() * 100),
        "bright": float((lum >= 140).mean() * 100),
    }


def saturation(im):
    a = _arr(im)
    mx = a.max(axis=2)
    mn = a.min(axis=2)
    return float(np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0).mean())


def edge_density(im):
    """Sobel 近似：相邻像素差的均值。= 材质复杂度。"""
    g = np.asarray(im.convert("L"), dtype=np.float32)
    gx = np.abs(np.diff(g, axis=1))
    gy = np.abs(np.diff(g, axis=0))
    return float(np.mean(np.maximum(gx[:-1, :], gy[:, :-1])))


def frame_diffs(images, resize=(120, 90)):
    """相邻帧平均绝对差（列表）。第一个元素是 0。"""
    arrs = [_arr(im, resize) for im in images]
    out = [0.0]
    for i in range(1, len(arrs)):
        out.append(float(np.abs(arrs[i] - arrs[i - 1]).mean()))
    return out


def cut_points(diffs, threshold=None, k=3.0):
    """返回疑似切镜的下标。

    ⚠️ 不要用固定阈值。固定 8 只对「抽 2fps 的低运动片」成立；
    高运动片（每帧都在动，帧间差均值 30+）会全部超标。
    ⇒ 用相对于本片分布的异常值：> 中位数 + k × 稳健标准差（MAD 换算）。

    threshold 显式给值时用它（绝对阈值，适合已知运动量的场景）。
    """
    vals = [d for i, d in enumerate(diffs) if i > 0]
    if not vals:
        return []
    if threshold is not None:
        return [i for i, d in enumerate(diffs) if i > 0 and d > threshold]
    med = float(np.median(vals))
    mad = float(np.median([abs(v - med) for v in vals])) or 1e-6
    robust_std = mad * 1.4826
    thr = med + k * robust_std
    # 至少要比中位数高 50%，避免"整体很稳但微小波动全被当切点"
    thr = max(thr, med * 1.5)
    return [i for i, d in enumerate(diffs) if i > 0 and d > thr]


def intra_drift(diffs, cuts, guard=2):
    """剔除切点（±guard）后的平均帧间差 = 镜内漂移。"""
    skip = set()
    for c in cuts:
        for o in range(-guard, guard + 1):
            skip.add(c + o)
    vals = [d for i, d in enumerate(diffs) if i > 0 and i not in skip]
    return float(np.mean(vals)) if vals else 0.0


def color_drift(images, resize=(160, 120)):
    """逐核对首帧的色彩漂移：返回每帧的 mean delta（0-255 尺度）。"""
    if not images:
        return []
    base = _arr(images[0], resize)
    out = [0.0]
    for im in images[1:]:
        a = _arr(im, resize)
        out.append(float(np.mean(np.abs(a.mean(axis=(0, 1)) - base.mean(axis=(0, 1))))))
    return out


def read_image(path):
    return Image.open(path).convert("RGB")
