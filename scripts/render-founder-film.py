"""Founder-case motion film. Reconstructed scenes, actual synthetic product capture.
No private source is read here. Pillow/NumPy + local FFmpeg only.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import wave
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "frontend/public/showcase"
MEDIA = ROOT / "docs/media"
QA = ROOT / "work/founder-film-2026-10-20"
W, H, S, FPS, DURATION = 1080, 1920, 1.5, 60, 38
PURPLE = "#9876ff"
WHITE = "#fbfaff"
INK = "#171320"
MUTED = "#aaa0ba"
PINK = "#ff7fa4"
GREEN = "#9de9c6"
SCENES = [
    (0, 2, "문제 발견", "AI가 수치와 기여 범위를 바꿨다."),
    (2, 4, "실제 사례 01", "같은 키워드가 같은 직무를 뜻하진 않았다."),
    (4, 7, "판단 기준 변경", "본업 · 직접 근거 · 공백부터 확인."),
    (7, 9.5, "실제 사례 02", "경험의 범위도, 본인 기여도 바뀌었다."),
    (9.5, 12, "사실과 표현 분리", "사실은 근거에서. 표현은 별도로."),
    (12, 15, "역할별 검수", "작성 · 사실 검수 · 채용 관점 검수."),
    (15, 18, "사용자 승인", "중요한 메시지는 내가 확인한다."),
    (18, 23, "실제 구현", "문항 의도 · 권장 배분 · 경험을 먼저."),
    (23, 27, "실제 경험 · 도전 문항", "도구 이름보다, 가설을 바꾼 이유."),
    (27, 30.5, "문항별 설계", "600자 구성 예시. 권장 배분을 내 경험에 맞게."),
    (30.5, 34, "암묵지의 구조화", "반복하던 판단을 Skill과 Rule로."),
    (34, 38, "Career Harness", "해낸 일은 정확하게. 지원서는 설득력 있게."),
]


def px(v):
    return round(v * S)


@lru_cache(maxsize=100)
def font(size, bold=True):
    return ImageFont.truetype(
        str(ROOT / "backend/career/assets/fonts" / ("CareerKR-Bold.ttf" if bold else "CareerKR-Regular.ttf")),
        px(size),
    )


@lru_cache(maxsize=1000)
def tile(value, size, color, bold=True):
    f = font(size, bold)
    b = f.getbbox(value)
    im = Image.new("RGBA", (max(1, math.ceil(f.getlength(value)) + px(5)), b[3] - min(0, b[1]) + px(7)))
    d = ImageDraw.Draw(im)
    d.text((0, -min(0, b[1])), value, font=f, fill=color, stroke_width=0)
    return im


def txt(im, value, x, y, size=30, color=WHITE, bold=True, a=1, scale=1, anchor="left", angle=0):
    pic = tile(value, size, color, bold)
    if scale != 1:
        pic = pic.resize(
            (max(1, round(pic.width * scale)), max(1, round(pic.height * scale))), Image.Resampling.BICUBIC
        )
    if angle:
        pic = pic.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
    if a < 1:
        pic = pic.copy()
        pic.putalpha(pic.getchannel("A").point(lambda p: round(p * max(0, a))))
    xx = px(x) - (pic.width // 2 if anchor == "center" else pic.width if anchor == "right" else 0)
    im.paste(pic, (xx, px(y)), pic)


def rect(im, xy, fill, r=12, outline=None, width=1):
    ImageDraw.Draw(im).rounded_rectangle(
        tuple(px(v) for v in xy), radius=px(r), fill=fill, outline=outline, width=px(width)
    )


def line(im, points, color=PURPLE, width=2):
    ImageDraw.Draw(im).line([(px(x), px(y)) for x, y in points], fill=color, width=px(width), joint="curve")


def smooth(p):
    return max(0, min(1, p)) ** 2 * (3 - 2 * max(0, min(1, p)))


def out(p):
    return 1 - (1 - max(0, min(1, p))) ** 3


def enter(t, delay=0):
    return out((t - delay) / 0.5)


def pill(im, value, x, y, color=PURPLE, bg="#2a223c", size=18):
    width = tile(value, size, color).width / S + 28
    rect(im, (x, y, x + width, y + 45), bg, 22)
    txt(im, value, x + 14, y + 6, size, color)


def title(im, lines, t, y=185, size=72, color=WHITE):
    for j, value in enumerate(lines):
        p = enter(t, j * 0.085)
        txt(im, value, 46, y + j * (size + 18) + 55 * (1 - p), size, color, a=p, scale=1 + 0.12 * (1 - p))


def dot(im, x, y, r=4, color=PURPLE):
    ImageDraw.Draw(im).ellipse((px(x - r), px(y - r), px(x + r), px(y + r)), fill=color)


def pathflow(im, points, p, color=PURPLE, width=3):
    lengths = [math.dist(a, b) for a, b in zip(points, points[1:])]
    total = sum(lengths)
    remain = total * max(0, min(1, p))
    for j, (a, b) in enumerate(zip(points, points[1:])):
        if remain <= 0:
            break
        ratio = min(1, remain / lengths[j])
        end = (a[0] + (b[0] - a[0]) * ratio, a[1] + (b[1] - a[1]) * ratio)
        line(im, [a, end], color, width)
        dot(im, *end, 5, color)
        remain -= lengths[j]


@lru_cache(maxsize=3)
def background(light=False):
    c1 = np.array([244, 239, 255] if light else [21, 17, 31], dtype=float)
    c2 = np.array([221, 210, 250] if light else [43, 29, 69], dtype=float)
    yy, xx = np.mgrid[0:H, 0:W]
    g = np.exp(-(((xx - W * 0.9) / W) ** 2 + ((yy - H * 0.25) / (H * 0.65)) ** 2) * 2)
    arr = np.empty((H, W, 3), dtype=np.uint8)
    for c in range(3):
        arr[:, :, c] = c1[c] + (c2[c] - c1[c]) * g
    im = Image.fromarray(arr)
    d = ImageDraw.Draw(im)
    for x in range(36, 720, 36):
        for y in range(36, 1280, 36):
            dot(im, x, y, 0.65, "#cec2e4" if light else "#3d3150")
    d.arc((px(410), px(-140), px(1080), px(530)), 0, 360, fill="#c8b7ef" if light else "#4b376b", width=2)
    return im


def header(im, tag, light=False):
    color = INK if light else "#cbb9ed"
    txt(im, "h↗", 48, 45, 31, PURPLE)
    txt(im, "CAREER HARNESS", 103, 56, 15, color)
    txt(im, tag, 670, 56, 14, color, anchor="right")


def pointer(im, x, y, clicked=False):
    d = ImageDraw.Draw(im)
    p = [(x, y), (x + 10, y + 38), (x + 18, y + 27), (x + 33, y + 26)]
    d.polygon([(px(a), px(b)) for a, b in p], fill=WHITE, outline=INK, width=2)
    if clicked:
        for j in range(8):
            a = j * math.pi / 4
            line(
                im,
                [(x + math.cos(a) * 36, y + math.sin(a) * 36), (x + math.cos(a) * 48, y + math.sin(a) * 48)],
                GREEN,
                3,
            )


def caption(im, value, light=False):
    lines = []
    current = ""
    for ch in value:
        proposed = current + ch
        if font(23, False).getlength(proposed) / S > 603:
            lines.append(current)
            current = ch
        else:
            current = proposed
    if current:
        lines.append(current)
    rect(im, (39, 1096, 681, 1096 + len(lines) * 36 + 24), "#282032" if not light else "#e0d5f1", 15)
    for j, s in enumerate(lines):
        txt(im, s, 59, 1106 + j * 36, 23, WHITE if not light else INK, False)
    txt(im, "실제 경험 기반 · 장면 재구성", 47, 1220, 15, MUTED if not light else "#655875", False)


def scene(i, t, global_t):
    light = i in {4, 7, 9, 11}
    im = background(light).copy()
    header(im, SCENES[i][2], light)
    if i == 0:
        title(im, ["AI가", "내 경력을", "바꿨다."], t, y=186, size=92)
        for j, word in enumerate(["직무", "수치", "본인 기여"]):
            p = enter(t, 0.24 + j * 0.13)
            pill(im, word, 52 + j * 165, 709 + (1 - p) * 60, PINK, "#3e2538", 23)
        line(im, [(51, 639), (51 + 520 * enter(t, 0.45), 639)], PINK, 7)
        txt(im, "그래서, 판단부터 설계했다.", 51, 887, 31, "#d4c3eb", a=enter(t, 0.65))
    elif i == 1:
        txt(im, "RAG", 360, 176, 202, PURPLE, anchor="center", scale=1 + 0.06 * math.sin(t * 3))
        rect(im, (46, 526, 331, 716), "#302442", 22)
        rect(im, (389, 526, 674, 716), "#302442", 22)
        txt(im, "공고", 73, 550, 23, "#b5a1cf")
        txt(im, "RAG", 75, 587, 50)
        txt(im, "내 경험", 414, 550, 23, "#b5a1cf")
        txt(im, "RAG", 414, 587, 50)
        pathflow(im, [(331, 621), (360, 621), (389, 621)], out(t / 0.7), GREEN, 5)
        p = enter(t, 0.55)
        rect(im, (141, 797, 579, 894), "#4b263c", 18)
        txt(im, "키워드만 같았다.", 360, 811, 39, PINK, anchor="center", a=p)
        txt(
            im,
            "실제 업무가 다른데도 적합하다고 판단",
            360,
            946,
            24,
            WHITE,
            False,
            anchor="center",
            a=enter(t, 0.7),
        )
    elif i == 2:
        title(im, ["기준을", "바꿨다."], t, y=174, size=80)
        rows = [
            ("01", "실제 맡는 일", "Actual Output"),
            ("02", "직접 증명할 경험", "Direct Evidence"),
            ("03", "아직 부족한 역량", "Current Gap"),
        ]
        for j, (n, word, en) in enumerate(rows):
            p = enter(t, 0.13 + j * 0.21)
            yy = 466 + j * 181
            txt(im, n, 51, yy + 25, 22, PURPLE, a=p)
            txt(im, word, 113 + (1 - p) * 65, yy + 14, 39, WHITE, a=p)
            txt(im, en, 115, yy + 83, 20, "#b6a4ce", False, a=p)
            pathflow(im, [(51, yy + 135), (668, yy + 135)], p, "#594472", 1)
    elif i == 3:
        title(im, ["내가 한 일이", "달라졌다?"], t, y=173, size=68)
        for j, (word, yy) in enumerate([("경험의 범위", 490), ("성과 수치", 634), ("본인 기여", 778)]):
            p = enter(t, j * 0.16)
            offset = math.sin(t * 39 + j) * 8 * max(0, 1 - t / 1.4)
            txt(im, word, 53 + offset, yy, 45, PINK, a=p)
            line(im, [(56, yy + 79), (653, yy + 79)], "#614057", 2)
            txt(im, "확인 필요", 650, yy + 14, 21, MUTED, anchor="right", a=p)
    elif i == 4:
        title(im, ["사실과 표현을", "분리했다."], t, y=173, size=63, color=INK)
        for j, (word, sub, xx) in enumerate([("FACT", "확인된 사실", 47), ("EXPRESSION", "표현 방식", 371)]):
            p = enter(t, 0.1 + j * 0.12)
            rect(im, (xx, 466 + 35 * (1 - p), xx + 302, 741 + 35 * (1 - p)), WHITE, 22)
            txt(im, word, xx + 21, 493, 26, "#6341aa", a=p)
            txt(im, sub, xx + 21, 565, 26, INK, a=p)
            for z, length in enumerate([227, 190, 212]):
                line(im, [(xx + 24, 639 + z * 25), (xx + 24 + length, 639 + z * 25)], "#d1c5e6", 4)
        pathflow(im, [(197, 750), (197, 805), (360, 866)], enter(t, 0.35), PURPLE, 4)
        pathflow(im, [(522, 750), (522, 805), (360, 866)], enter(t, 0.5), PURPLE, 4)
        rect(im, (209, 865, 511, 982), "#7250b9", 23)
        txt(im, "Claim ↔ 근거", 360, 891, 31, WHITE, anchor="center")
    elif i == 5:
        title(im, ["쓰고.", "따로 검수한다."], t, y=161, size=64)
        nodes = [(360, 490, "작성"), (177, 778, "사실 검수"), (543, 778, "채용 관점")]
        for a, b in [(0, 1), (0, 2), (1, 2)]:
            pa = nodes[a][:2]
            pb = nodes[b][:2]
            pathflow(im, [pa, pb], enter(t, 0.2 + a * 0.12), PURPLE, 3)
            q = (t * 0.6 + a * 0.33) % 1
            dot(im, pa[0] + (pb[0] - pa[0]) * q, pa[1] + (pb[1] - pa[1]) * q, 7, GREEN)
        for j, (xx, yy, label) in enumerate(nodes):
            ImageDraw.Draw(im).ellipse(
                (px(xx - 99), px(yy - 72), px(xx + 99), px(yy + 72)),
                fill="#332546",
                outline="#9270c7",
                width=2,
            )
            txt(im, label, xx, yy - 24, 29, WHITE, anchor="center", a=enter(t, j * 0.1))
        txt(im, "근거?  ·  기여?  ·  문항에 답했나?", 360, 971, 26, "#cfbde6", anchor="center")
    elif i == 6:
        title(im, ["중요한 결정은", "내가 승인."], t, y=177, size=66)
        clicked = t > 1.58
        fill = "#25483e" if clicked else "#7754c7"
        # The ring opens after the reconstructed click, not an actual approval event.
        radius = 177 + 16 * math.sin(t * 3)
        ImageDraw.Draw(im).ellipse(
            (px(360 - radius), px(689 - radius), px(360 + radius), px(689 + radius)),
            outline="#684b8c",
            width=2,
        )
        rect(im, (85, 625, 635, 757), fill, 28)
        txt(im, "확인 후 진행" if not clicked else "확인 완료  →", 360, 658, 39, WHITE, anchor="center")
        p = smooth(min(1, t / 1.55))
        pointer(im, 612 + (452 - 612) * p, 907 + (714 - 907) * p, clicked and t < 1.82)
        txt(im, "AI가 사용자 승인을 대신하지 않습니다.", 360, 952, 23, "#c8b6df", False, anchor="center")
    elif i == 7:
        title(im, ["초안 전에,", "설계를 먼저."], t, y=147, size=65, color=INK)
        # Existing genuine product capture uses only synthetic QA data.
        raw = PRODUCT
        progress = smooth(t / 5)
        zoom = 1.02 + 0.75 * smooth(t / 3)
        viewport_w, viewport_h = 626, 587
        cw = raw.width / zoom
        ch = cw * viewport_h / viewport_w
        if ch > raw.height:
            ch = raw.height
            cw = ch * viewport_w / viewport_h
        cx = 655 + (1110 - 655) * smooth((t - 2.1) / 2.5)
        cy = 460
        x0 = max(0, min(raw.width - cw, cx - cw / 2))
        y0 = max(0, min(raw.height - ch, cy - ch / 2))
        shot = raw.crop((round(x0), round(y0), round(x0 + cw), round(y0 + ch))).resize(
            (px(viewport_w), px(viewport_h)), Image.Resampling.LANCZOS
        )
        rect(im, (42, 400, 678, 1024), WHITE, 26)
        im.paste(shot, (px(47), px(421)))
        rect(im, (47, 397, 673, 438), "#ebe4f5", 9)
        for j, c in enumerate(["#c69bba", "#d1bf9d", "#a7c8bb"]):
            dot(im, 64 + j * 17, 418, 4, c)
        txt(im, "실제 구현 화면 · 합성 자료", 134, 403, 15, "#625174", False)
        txt(
            im,
            "문항 설계" if progress < 0.5 else "오른쪽 문서 보관함",
            360,
            1039,
            23,
            "#65489f",
            anchor="center",
        )
    elif i == 8:
        title(im, ["도전 경험,", "기술을 나열할까?"], t, y=159, size=58)
        txt(im, "실제 Multi-Agent 실패 진단 연구", 51, 414, 20, MUTED, False)
        for j, word in enumerate(["Chunking", "Search", "Reranking"]):
            p = enter(t, j * 0.1)
            txt(im, word, 51 + j * 209, 483, 25, "#a497b9", a=p)
        pathflow(im, [(54, 555), (360, 555), (360, 619)], enter(t, 0.3), PURPLE, 3)
        txt(im, "관점을 바꾼 이유", 360, 638, 31, GREEN, anchor="center", a=enter(t, 0.4))
        rect(im, (47, 728, 673, 940), "#332546", 24)
        txt(im, "성공 조건부터 정의하고", 76, 753, 36, WHITE, a=enter(t, 0.55))
        txt(im, "로그로 실패 지점을 추적", 76, 818, 36, PURPLE, a=enter(t, 0.65))
        txt(im, "경험의 메시지 재구성 · AI 생성 결과 아님", 360, 1018, 19, MUTED, False, anchor="center")
    elif i == 9:
        title(im, ["600자,", "어디에 쓸까?"], t, y=159, size=70, color=INK)
        labels = ["역량 선언", "문제와 역할", "기술적 행동", "성과·직무 연결"]
        values = [70, 120, 280, 130]
        colors = ["#bca1e9", "#a27dde", "#7952c1", "#4c2e79"]
        for j, (label, n, c) in enumerate(zip(labels, values, colors, strict=True)):
            yy = 445 + j * 142
            p = enter(t, 0.15 + j * 0.18)
            txt(im, label, 51, yy, 27, INK)
            txt(im, f"{round(n * p)}자", 664, yy, 27, "#674496", anchor="right")
            rect(im, (51, yy + 57, 666, yy + 95), "#dfd3ed", 8)
            if p:
                rect(im, (51, yy + 57, 51 + (615 * n / 280) * p, yy + 95), c, 8)
        txt(im, "등록 가이드의 권장 배분 · 문항 요구 우선", 360, 1030, 19, "#6a5d7b", False, anchor="center")
    elif i == 10:
        title(im, ["반복하던 판단을", "Skill · Rule로."], t, y=155, size=61)
        words = ["본업", "출처", "경험", "수치", "기여", "메시지", "승인", "검수"]
        for j, word in enumerate(words):
            angle = j * math.tau / len(words) + t * 0.22
            r = 227 - 110 * smooth(t / 3.5)
            xx = 360 + math.cos(angle) * r
            yy = 716 + math.sin(angle) * r
            line(im, [(xx, yy), (360, 716)], "#5a3f7b", 2)
            dot(im, xx, yy, 3, GREEN)
            txt(im, word, xx, yy - 18, 23, "#d5c1ed", anchor="center")
        ImageDraw.Draw(im).ellipse(
            (px(288), px(644), px(432), px(788)), fill="#8862d1", outline="#c8a5ff", width=3
        )
        txt(im, "h", 360, 643, 72, WHITE, anchor="center")
        txt(im, "사람의 판단 → AI의 수행 → 근거 검수", 360, 1018, 23, WHITE, anchor="center")
    else:
        txt(im, "h↗", 360, 217, 107, "#7751c5", anchor="center", scale=0.9 + 0.1 * enter(t))
        txt(im, "Career", 360, 416, 80, INK, anchor="center", a=enter(t, 0.1))
        txt(im, "Harness", 360, 517, 80, INK, anchor="center", a=enter(t, 0.2))
        pathflow(im, [(131, 640), (590, 640)], enter(t, 0.4), "#8862c8", 6)
        txt(im, "해낸 일은 정확하게.", 360, 699, 34, INK, anchor="center", a=enter(t, 0.4))
        txt(im, "지원서는 설득력 있게.", 360, 755, 34, "#6d4b99", anchor="center", a=enter(t, 0.5))
        rect(im, (92, 874, 628, 966), "#7751c5", 22)
        txt(im, "공개 체험  ↗", 360, 893, 33, WHITE, anchor="center")
        txt(im, "career-harness-web.vercel.app", 360, 1001, 23, "#5c477c", False, anchor="center")
        txt(
            im,
            "무료 한도 적용 · 전체 개인 작성 품질 검증 중",
            360,
            1051,
            16,
            "#766883",
            False,
            anchor="center",
        )
    caption(im, SCENES[i][3], light)
    line(im, [(48, 1261), (48 + 624 * global_t / DURATION, 1261)], "#9675d0" if light else PURPLE, 3)
    return im


def frame_at(t):
    i = next((j for j, s in enumerate(SCENES) if s[0] <= t < s[1]), len(SCENES) - 1)
    local = t - SCENES[i][0]
    im = scene(i, local, t)
    # Fast match cut: only the first eight frames blend; motion stays readable.
    if i and local < 0.13:
        prev = scene(i - 1, SCENES[i - 1][1] - SCENES[i - 1][0] - 0.01, t)
        im = Image.blend(prev, im, smooth(local / 0.13))
    return im


def sound(path):
    sr = 48000
    n = sr * DURATION
    audio = np.zeros((n, 2), np.float32)
    rng = np.random.default_rng(812)

    def add(at, a, amp=1, pan=0):
        k = round(at * sr)
        end = min(n, k + len(a))
        if k >= n:
            return
        audio[k:end, 0] += a[: end - k] * amp * (1 - pan * 0.4)
        audio[k:end, 1] += a[: end - k] * amp * (1 + pan * 0.4)

    step = 60 / 144
    for b in range(math.ceil(DURATION / step)):
        at = b * step
        t = np.arange(round(0.25 * sr)) / sr
        add(at, np.sin(2 * np.pi * (47 * t + 45 * 0.04 * (1 - np.exp(-t / 0.04)))) * np.exp(-t * 24), 0.62)
        t = np.arange(round(0.09 * sr)) / sr
        if b % 2:
            add(
                at,
                rng.normal(0, 0.3, len(t)) * np.exp(-t * 33)
                + 0.15 * np.sin(2 * np.pi * 180 * t) * np.exp(-t * 40),
                0.28,
            )
        for half in [0, 0.5]:
            t = np.arange(round(0.038 * sr)) / sr
            noise = rng.normal(0, 0.25, len(t))
            noise = np.diff(noise, prepend=0)
            add(at + half * step, noise * np.exp(-t * 110), 0.10, (-1) ** b * 0.6)
        note = [110, 130.813, 97.999, 146.832][(b // 8) % 4]
        t = np.arange(round(0.28 * sr)) / sr
        add(at, np.sin(2 * np.pi * note * t) * np.exp(-t * 13), 0.17)
        if b % 2 == 0:
            t = np.arange(round(0.35 * sr)) / sr
            add(
                at,
                (np.sin(2 * np.pi * note * 4 * t) + 0.2 * np.sin(2 * np.pi * note * 8 * t)) * np.exp(-t * 12),
                0.07,
                math.sin(b),
            )
    for start, *_ in SCENES[1:]:
        t = np.arange(round(0.19 * sr)) / sr
        noise = rng.normal(0, 0.18, len(t))
        env = np.sin(np.linspace(0, np.pi, len(t))) ** 2
        add(max(0, start - 0.1), noise * env, 0.28, -0.4)
        t = np.arange(round(0.10 * sr)) / sr
        add(start, np.sin(2 * np.pi * (80 * t + 45 * t * t)) * np.exp(-t * 40), 0.3)
    t = np.arange(round(0.07 * sr)) / sr
    add(16.58, np.sin(2 * np.pi * 1400 * t) * np.exp(-t * 110), 0.2)
    audio *= np.minimum(np.arange(n) / sr / 0.08, 1)[:, None]
    audio *= np.minimum((n - np.arange(n)) / sr / 0.4, 1)[:, None]
    with wave.open(str(path), "wb") as f:
        f.setnchannels(2)
        f.setsampwidth(2)
        f.setframerate(sr)
        f.writeframes((np.clip(audio, -0.97, 0.97) * 32767).astype("<i2").tobytes())


def stamp(t):
    sec = int(t)
    ms = round((t - sec) * 1000)
    return f"00:00:{sec:02},{ms:03}"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--ffmpeg", required=True)
    p.add_argument("--previews-only", action="store_true")
    args = p.parse_args()
    for folder in [QA, MEDIA, OUT]:
        folder.mkdir(parents=True, exist_ok=True)
    global PRODUCT
    PRODUCT = Image.open(MEDIA / "product-writing-plan.jpg").convert("RGB")
    sheets = []
    manifest = []
    for i, s in enumerate(SCENES):
        t = s[0] + min((s[1] - s[0]) * 0.7, 2.4)
        shot = frame_at(t)
        shot.save(QA / f"scene-{i + 1:02}.jpg", quality=94)
        sheets.append(shot.resize((216, 384), Image.Resampling.LANCZOS))
        manifest.append({"start": s[0], "end": s[1], "section": s[2], "caption": s[3]})
    contact = Image.new("RGB", (216 * 6, 384 * 2), INK)
    for i, shot in enumerate(sheets):
        contact.paste(shot, ((i % 6) * 216, (i // 6) * 384))
    contact.save(QA / "contact-sheet.jpg", quality=95)
    frame_at(1.5).save(MEDIA / "founder-film-poster.jpg", quality=95)
    (MEDIA / "founder-film-scenes.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (OUT / "career-harness-founder-film.srt").write_text(
        "\n\n".join(f"{i + 1}\n{stamp(s[0])} --> {stamp(s[1])}\n{s[3]}" for i, s in enumerate(SCENES)) + "\n",
        encoding="utf-8",
    )
    if args.previews_only:
        return
    wav = QA / "original-sound-design.wav"
    sound(wav)
    movie = OUT / "career-harness-founder-film.mp4"
    cmd = [
        args.ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{W}x{H}",
        "-r",
        str(FPS),
        "-i",
        "pipe:0",
        "-i",
        str(wav),
        "-map",
        "0:v",
        "-map",
        "1:a",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "19",
        "-pix_fmt",
        "yuv420p",
        "-af",
        "loudnorm=I=-16:TP=-1.5:LRA=7",
        "-ar",
        "48000",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-t",
        str(DURATION),
        "-movflags",
        "+faststart",
        str(movie),
    ]
    with (QA / "encode.log").open("wb") as log:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=log)
        try:
            for n in range(FPS * DURATION):
                proc.stdin.write(frame_at(n / FPS).tobytes())
                if n % (FPS * 2) == 0:
                    print(f"Rendered {n / FPS:.0f}/{DURATION} sec", flush=True)
        finally:
            proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError((QA / "encode.log").read_text())
    subprocess.run(
        [
            args.ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(movie),
            "-t",
            "7",
            "-filter_complex",
            "[0:v]fps=10,scale=270:480:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse=dither=bayer",
            "-loop",
            "0",
            str(MEDIA / "founder-film-preview.gif"),
        ],
        check=True,
    )
    print(f"Done: {movie.stat().st_size:,} bytes", flush=True)


if __name__ == "__main__":
    main()
