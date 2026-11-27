#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""vidkit —— AI 视频流水线的五个质检位

    vidkit check  <视频>                     画面验收：绿斑/漂移/亮度/色彩
    vidkit pick   <图片目录>                 抽卡评分：一批候选图打分排序
    vidkit plint  <提示词文件>               提示词连贯化：六条，哪条没写
    vidkit voice  <wav> --shot 5.1667        配音时长适配：目标 = 镜长 − 0.28
    vidkit color  <视频> [--fix]             多帧色彩校正：逐通道对齐首帧

依赖：ffmpeg（命令行）＋ numpy ＋ Pillow ＋ soundfile
"""
import argparse
import sys


def main():
    ap = argparse.ArgumentParser(
        prog="vidkit",
        description="AI 视频流水线的五个质检位（check / pick / plint / voice / color）")
    sub = ap.add_subparsers(dest="cmd")

    c = sub.add_parser("check", help="画面验收")
    c.add_argument("video")
    c.add_argument("--fps", type=float, default=2.0, help="抽帧帧率（默认 2）")
    c.add_argument("--width", type=int, default=480, help="抽帧宽度（默认 480）")
    c.add_argument("--shots", type=int, default=0, help="预期镜头数（可选，用来核边界）")

    p = sub.add_parser("pick", help="抽卡评分")
    p.add_argument("folder")
    p.add_argument("--top", type=int, default=0, help="只显示前 N 张")

    l = sub.add_parser("plint", help="提示词连贯化检查")
    l.add_argument("prompt")

    v = sub.add_parser("voice", help="配音时长适配")
    v.add_argument("wav")
    v.add_argument("--shot", type=float, required=True, help="镜长秒数，如 5.1667")
    v.add_argument("--out", default=None)
    v.add_argument("--margin", type=float, default=0.28, help="留的尾部余量（默认 0.28）")

    k = sub.add_parser("color", help="多帧色彩校正")
    k.add_argument("video")
    k.add_argument("--out", default=None)
    k.add_argument("--fps", type=float, default=None, help="抽帧率（默认用原帧率）")
    k.add_argument("--only-lum", action="store_true", help="只修亮度，不动色相")
    k.add_argument("--strength", type=float, default=1.0, help="校正力度 0..1")

    args = ap.parse_args()
    if not args.cmd:
        ap.print_help()
        return 2

    from . import check, pick, plint, voice, color

    try:
        if args.cmd == "check":
            check.run(args.video, fps=args.fps, width=args.width, expect_shots=args.shots)
        elif args.cmd == "pick":
            pick.run(args.folder, top=args.top)
        elif args.cmd == "plint":
            plint.run(args.prompt)
        elif args.cmd == "voice":
            voice.run(args.wav, args.shot, out=args.out, margin=args.margin)
        elif args.cmd == "color":
            color.run(args.video, out_path=args.out, fps=args.fps,
                      only_lum=args.only_lum, strength=args.strength)
    except Exception as e:
        print("  ❌ %s" % e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
