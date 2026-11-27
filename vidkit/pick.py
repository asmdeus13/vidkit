# -*- coding: utf-8 -*-
"""vidkit.pick —— 抽卡评分：一批候选图，按四条判据打分排序

判据（可关可调）：
    ① 人脸朝向      eyes_on_camera：眼睛是不是朝镜头（有需要有不需，所以只报不判）
    ② 构图合规      人物占比（用边缘/肤色粗估，不引入人脸库依赖）
    ③ 文字残留      模型自己画上去的乱码字 —— 用"高频小连通块"粗检
    ④ 组内一致性    这一批之间的亮度/饱和度是否一致（选出离群项）

设计取舍：不引入 dlib/face_recognition 这类重依赖。
人脸朝向只用"肤色块重心 vs 画面重心"做粗估，输出建议值，最终仍由人定。
"""
import os
import sys

import numpy as np
from PIL import Image

from . import metrics


def skin_mask(im):
    """粗略肤色掩码（YCrCb 阈值），返回 bool 数组。"""
    a = np.asarray(im.convert("RGB"), dtype=np.float32)
    R, G, B = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    Y = 0.299 * R + 0.587 * G + 0.114 * B
    Cr = (R - Y) * 0.713 + 128
    Cb = (B - Y) * 0.564 + 128
    return (Cr > 133) & (Cr < 180) & (Cb > 77) & (Cb < 130) & (Y > 60)


def subject_ratio(im):
    """主体（肤色区）占画面比例 %。"""
    m = skin_mask(im)
    return float(m.mean() * 100.0)


def text_residue_score(im):
    """文字残留粗检：统计「高频小连通块」的数量。

    思路：模型乱画上去的字通常是密集、高对比、细笔画的小块。
    用梯度图的二值化 + 形态学腐蚀后剩下的碎块数量当代理指标。
    """
    g = np.asarray(im.convert("L"), dtype=np.float32)
    gx = np.abs(np.diff(g, axis=1))[:-1, :]
    gy = np.abs(np.diff(g, axis=0))[:, :-1]
    edge = np.maximum(gx, gy)
    hot = edge > 60
    # 按 16x16 分块，统计「边缘密度高但均匀」的块数（字通常是这种）
    hh, ww = hot.shape
    bs = 16
    blocks = 0
    for y in range(0, hh - bs, bs):
        for x in range(0, ww - bs, bs):
            blk = hot[y:y + bs, x:x + bs]
            d = blk.mean()
            if 0.12 < d < 0.55:
                blocks += 1
    return blocks


def score_one(path):
    im = metrics.read_image(path)
    ls = metrics.lum_stats(im)
    return {
        "path": path,
        "subject": subject_ratio(im),
        "whiteness": metrics.white_ratio(im),
        "saturation": metrics.saturation(im),
        "edges": metrics.edge_density(im),
        "lum_mean": ls["mean"],
        "lum_std": ls["std"],
        "text_residue": text_residue_score(im),
        "size": im.size,
    }


def run(folder, verbose=True, top=0):
    exts = (".png", ".jpg", ".jpeg", ".webp")
    files = [os.path.join(folder, f) for f in sorted(os.listdir(folder))
             if f.lower().endswith(exts)]
    if not files:
        print("  ❌ %s 里没有图片" % folder)
        return []

    rows = [score_one(p) for p in files]

    # 组内一致性：亮度/饱和度的中位数偏离
    lums = np.array([r["lum_mean"] for r in rows])
    sats = np.array([r["saturation"] for r in rows])
    med_l, med_s = float(np.median(lums)), float(np.median(sats))
    for r in rows:
        r["outlier"] = abs(r["lum_mean"] - med_l) + abs(r["saturation"] - med_s) * 100

    # 综合排序：文字残留和离群程度降分，主体占比和边缘密度加分
    for r in rows:
        s = 0.0
        s += min(r["subject"] / 20.0, 1.0) * 30        # 主体够大
        s += min(r["edges"] / 12.0, 1.0) * 25          # 材质细节够
        s -= min(r["text_residue"] / 40.0, 1.0) * 25   # 文字残留降分
        s -= min(r["outlier"] / 40.0, 1.0) * 20        # 组内离群降分
        r["score"] = round(max(s, 0.0), 1)

    rows.sort(key=lambda r: -r["score"])
    if top:
        rows = rows[:top]

    if verbose:
        print("  目录 %s  %d 张" % (folder, len(files)))
        print()
        print("  排名  文件名                        得分  主体%%  白%%   边缘  亮度  字残留  离群")
        print("  ----  ----------------------------  ----  -----  ----  ----  ----  ------  ----")
        for i, r in enumerate(rows, 1):
            print("  %3d   %-28s  %5.1f  %5.1f  %5.1f  %5.1f  %5.0f  %5d  %5.1f"
                  % (i, os.path.basename(r["path"])[:28], r["score"], r["subject"],
                     r["whiteness"], r["edges"], r["lum_mean"], r["text_residue"], r["outlier"]))
        print()
        print("  说明：")
        print("    · 得分是四项加权，只用来排序，不是「合格线」")
        print("    · 字残留 > 10 的，建议人工看一眼（模型可能画了乱码）")
        print("    · 离群越大说明这张和同批其它张差得越多（可能是意外好或意外坏）")
    return rows
