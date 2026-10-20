"""Reproducible vertical motion reel; synthetic examples, no accounts or APIs.
Run with Pillow, NumPy, --ffmpeg <local FFmpeg> and --fonts <Malgun font folder>.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import wave
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "frontend/public/showcase"
QA = ROOT / "work/reel-2026-10-20"
MEDIA = ROOT / "docs/media"
W, H, FPS, S = 1080, 1920, 30, 1.5
INK, PURPLE, CREAM, MUTED, WHITE, LILAC, GREEN = (
    "#262135",
    "#7260d9",
    "#f8f6fc",
    "#746c87",
    "#ffffff",
    "#e5defb",
    "#155f52",
)
SCENES = [
    (
        0,
        3,
        "CAREER HARNESS",
        ["이 공고,", "나랑 맞나?"],
        "RAG · Python · LLM. 같은 단어를 만나도 판단은 남습니다.",
    ),
    (
        3,
        7,
        "01 / 직무 해석",
        ["같은 RAG,", "다른 본업."],
        "기술 목록 다음에 확인할 것. 입사 후 만들어야 하는 산출물.",
    ),
    (
        7,
        11,
        "02 / 경험의 거리",
        ["해본 일과", "빈칸을 구분."],
        "평가 실험은 근거. 측정하지 않은 운영 성과는 공백으로.",
    ),
    (
        11,
        15,
        "03 / 문항별 전략",
        ["경험마다,", "보여줄 판단."],
        "지원동기는 선택 기준. 전문역량은 검증. 협업은 조율 행동.",
    ),
    (
        15,
        20,
        "04 / 초안 전 설계",
        ["600자를", "어디에 쓸까?"],
        "문항 의도와 권장 분량을 이해하고 경험과 메모를 선택합니다.",
    ),
    (
        20,
        24,
        "05 / 사실과 표현",
        ["팀이 한 일.", "내가 한 일."],
        "팀 성과를 내 성과로 바꾸지 않습니다. 주장마다 현재 근거를 확인합니다.",
    ),
    (
        24,
        28,
        "06 / 역할을 나눈 검수",
        ["쓰는 역할,", "확인하는 역할."],
        "근거가 있는가. 면접에서 설명할 수 있는가. 문항에 답했는가.",
    ),
    (
        28,
        32,
        "07 / 수정과 보관",
        ["근거가 바뀌면", "다시 확인."],
        "관련 초안은 재검토. 확정한 보관본은 당시 상태를 유지합니다.",
    ),
    (
        32,
        36,
        "ONE APPLICATION",
        ["공고에서", "최종본까지."],
        "공고, 근거, 전략, 문항 설계, 작성, 검수, 보관을 한 작업실에서.",
    ),
    (
        36,
        40,
        "CAREER HARNESS",
        ["해낸 일은", "정확하게."],
        "Career Harness. 대화하며 준비하고, 근거와 문서를 함께 보관하세요.",
    ),
]


def px(x):
    return round(x * S)


@lru_cache(maxsize=80)
def font(size, bold=False):
    return ImageFont.truetype(str(FONTS / ("malgunbd.ttf" if bold else "malgun.ttf")), px(size))


def text(d, xy, value, size=24, color=INK, bold=False):
    d.text((px(xy[0]), px(xy[1])), value, font=font(size, bold), fill=color)
    if xy[0] + d.textlength(value, font=font(size, bold)) / S > 681:
        raise ValueError("Text outside safe edge: " + value)


def box(d, xy, fill=WHITE, radius=20):
    d.rounded_rectangle(tuple(px(v) for v in xy), radius=px(radius), fill=fill)


def para(d, xy, lines, size=24, color=INK, bold=False, spacing=39):
    for j, line in enumerate(lines):
        text(d, (xy[0], xy[1] + j * spacing), line, size, color, bold)


def layer(draw, delay=0):
    im = Image.new("RGBA", (W, H))
    draw(ImageDraw.Draw(im))
    bounds = im.getbbox()
    return im.crop(bounds), bounds[0], bounds[1], delay


def card(y, tag, title, detail, fill=WHITE, accent=PURPLE, delay=0):
    def draw(d):
        box(d, (48, y, 672, y + 152), fill, 22)
        box(d, (48, y + 23, 53, y + 128), accent, 2)
        text(d, (76, y + 21), tag, 16, accent, True)
        text(d, (76, y + 52), title, 28, INK, True)
        text(d, (76, y + 102), detail, 20, MUTED)

    return layer(draw, delay)


def note(y, lines, dark=False, size=22):
    return layer(lambda c: para(c, (54, y), lines, size, "#c7b7eb" if dark else MUTED, False, 42), 0.42)


def make_scene(i):
    start, end, label, headings, _ = SCENES[i]
    dark = i in {0, 9}
    bg = Image.new("RGB", (W, H), INK if dark else CREAM)
    d = ImageDraw.Draw(bg)
    for x in range(0, 721, 72):
        d.line((px(x), 0, px(x), H), fill="#302a40" if dark else "#efebf6")
    d.ellipse((px(476), px(-80), px(916), px(360)), outline="#43375d" if dark else LILAC, width=px(2))
    text(d, (48, 55), "h↗  Career Harness", 20, "#d9d0f4" if dark else PURPLE, True)
    text(d, (48, 124), label, 16, "#b4a3da" if dark else MUTED, True)
    layers = [layer(lambda c: para(c, (45, 183), headings, 65, WHITE if dark else INK, True, 91))]
    if i == 0:
        layers += [
            card(471, "공고", "“RAG 경험 우대”", "그래서, 실제로 맡는 일은?", delay=0.15),
            card(651, "경험", "“프로젝트는 했는데…”", "어디까지 내 근거로 쓸 수 있을까?", delay=0.3),
            note(884, ["반복하던 취업 판단을", "작성 과정에 연결합니다."], True, 31),
        ]
    elif i == 1:
        layers += [
            card(
                460,
                "서비스 개발 공고 예시",
                "API · 배포 · 장애 대응",
                "요구 산출물  /  작동하는 서비스",
                delay=0.1,
            ),
            card(
                646,
                "현업 분석 공고 예시",
                "가설 · 실험 · 의사결정",
                "요구 산출물  /  판단을 돕는 분석",
                LILAC,
                delay=0.25,
            ),
            note(872, ["암묵지 → 실제 업무와 산출물부터.", "키워드 일치는 적합성의 결론이 아닙니다."]),
        ]
    elif i == 2:
        layers += [
            layer(lambda c: text(c, (53, 434), "예시 경험  /  문서 검색 평가 프로젝트", 21, MUTED), 0.06),
            card(
                497,
                "직접 근거",
                "평가 기준과 실험을 설계",
                "원자료에서 본인 역할 확인",
                "#e2eee9",
                GREEN,
                0.15,
            ),
            card(683, "현재 공백", "운영 비용 절감은 미측정", "검증하지 않은 성과는 쓰지 않기", delay=0.3),
            note(897, ["암묵지 → 직접 · 인접 · 근거 없음으로 구분."]),
        ]
    elif i == 3:
        rows = [
            ("지원동기", "왜 이 일을 택했나", "경험에서 생긴 선택 기준"),
            ("전문역량", "어떻게 검증했나", "판단 · 행동 · 확인된 결과"),
            ("협업", "어떻게 맞췄나", "상대의 기준과 본인 조율 행동"),
        ]
        layers += [
            card(446 + j * 173, *row, LILAC if j == 1 else WHITE, delay=0.1 + j * 0.13)
            for j, row in enumerate(rows)
        ]
    elif i == 4:

        def plan(c):
            box(c, (48, 433, 672, 1014), WHITE, 25)
            text(c, (76, 459), "전문역량  /  600자 구성 예시", 23, PURPLE, True)
            text(c, (76, 505), "배분은 권고. 실제 문항 요구가 우선입니다.", 18, MUTED)
            colors = ["#c4b7f0", "#a792e5", "#7260d9", "#40305f"]
            labels = ["역량 선언", "문제와 역할", "기술적 행동", "성과와 직무 연결"]
            x = 76
            for j, n in enumerate([70, 120, 280, 130]):
                width = 568 * n / 600
                box(c, (x, 557, x + width - 3, 602), colors[j], 5)
                x += width
                yy = 636 + j * 67
                box(c, (76, yy + 8, 86, yy + 18), colors[j], 3)
                text(c, (101, yy), labels[j], 23, INK, j == 2)
                text(c, (552, yy), f"{n}자", 23, PURPLE, True)
            text(c, (76, 929), "선택 경험  →  강조 방향  →  작성 메모", 21, PURPLE, True)
            text(c, (76, 967), "화면의 가이드를 실제 작성 입력에 연결", 18, MUTED)

        layers += [layer(plan, 0.12)]
    elif i == 5:
        layers += [
            card(
                453,
                "확인할 주장",
                "“운영 비용을 줄였습니다”",
                "측정 기록이 없다면 확인이 필요합니다.",
                delay=0.1,
            ),
            card(
                638,
                "현재 근거로 좁힌 표현",
                "“평가 기준을 설계했습니다”",
                "예시 문장  /  실제 수행 근거가 있을 때",
                LILAC,
                delay=0.28,
            ),
            note(865, ["암묵지 → 사실과 표현을 따로 관리.", "좋은 예시의 성과를 내 사실로 옮기지 않기."]),
        ]
    elif i == 6:
        rows = [
            ("작성", "승인한 메시지로 초안", "현재 근거와 문항 요구를 사용"),
            ("사실 검수", "수치 · 기여 · 출처 확인", "근거가 부족하면 질문으로 반환"),
            ("채용 관점 검수", "이 문항에 답했는가", "수정 후 최종 결정은 사용자가"),
        ]
        layers += [
            card(446 + j * 173, *row, LILAC if j == 1 else WHITE, delay=0.1 + j * 0.13)
            for j, row in enumerate(rows)
        ]
    elif i == 7:
        layers += [
            card(
                451,
                "경험 근거 수정",
                "“이 기능은 제가 맡지 않았어요”",
                "사용자 정정이 관련 문서 상태를 변경",
                delay=0.1,
            ),
            card(637, "연결된 초안", "재검토 필요", "메시지와 근거를 다시 확인", LILAC, delay=0.23),
            note(867, ["보관본은 당시 버전 그대로.", "최종본 보관과 실제 제출은 별도입니다."], size=24),
        ]
    elif i == 8:
        for j, pair in enumerate(
            [
                ("01  공고 · 근거", "02  전략 승인"),
                ("03  문항별 설계", "04  자소서 · 이력서"),
                ("05  검수 · 수정", "06  최종본 · 면접"),
            ]
        ):

            def row(c, j=j, pair=pair):
                for k, value in enumerate(pair):
                    xx = 48 + k * 322
                    yy = 462 + j * 156
                    box(c, (xx, yy, xx + 302, yy + 126), LILAC if j == 1 else WHITE, 20)
                    text(c, (xx + 19, yy + 43), value, 23, INK, True)

            layers.append(layer(row, 0.1 + j * 0.13))
        layers.append(note(970, ["대화로 진행하고, 오른쪽에는", "근거 · 초안 · 버전이 쌓입니다."], size=25))
    else:

        def endcard(c):
            text(c, (49, 419), "지원서는 설득력 있게.", 36, "#c3b0ee", True)
            box(c, (48, 550, 672, 852), "#3b3152", 27)
            text(c, (77, 587), "취업 준비의 판단을 이어 주는", 25, "#d1c5e7")
            text(c, (77, 639), "나의 커리어 작업실", 38, WHITE, True)
            box(c, (77, 733, 642, 807), PURPLE, 15)
            text(c, (105, 749), "Career Harness  →  공개 체험", 27, WHITE, True)
            text(c, (51, 909), "github.com/yoon-chan-hyeok", 23, "#c2b2da")
            text(c, (51, 950), "/career-harness", 23, "#c2b2da")
            text(c, (51, 1010), "무료 한도 적용 · 개인 전체 작성 품질은 검증 중", 18, "#b3a1d0")

        layers.append(layer(endcard, 0.15))
    return bg, layers


def ease(p):
    return 1 - (1 - min(1, max(0, p))) ** 3


def frame_at(t, cache):
    i = next((j for j, s in enumerate(SCENES) if s[0] <= t < s[1]), 9)
    start = SCENES[i][0]
    if i not in cache:
        cache.clear()
        cache[i] = make_scene(i)
    bg, layers = cache[i]
    im = bg.copy()
    for pic, x, y, delay in layers:
        a = ease((t - start - delay) / 0.52)
        if a <= 0:
            continue
        overlay = pic if a >= 1 else pic.copy()
        if a < 1:
            overlay.putalpha(overlay.getchannel("A").point(lambda n: round(n * a)))
        im.paste(overlay, (x, y + px(38 * (1 - a))), overlay)
    d = ImageDraw.Draw(im)
    dark = i in {0, 9}
    text(d, (49, 1144), "취업 준비의 판단을, 하나의 흐름으로.", 18, "#b8a8ce" if dark else MUTED)
    text(d, (49, 1182), "규칙을 재구성한 예시 · 실제 AI 응답 아님", 14, "#a291bc" if dark else MUTED)
    text(d, (601, 1180), f"{i + 1:02}/10", 14, "#b8a8ce" if dark else PURPLE, True)
    box(d, (48, 1234, 672, 1238), "#453957" if dark else "#ddd5ee", 2)
    if t > 0:
        box(d, (48, 1234, 48 + 624 * min(t / 40, 1), 1238), PURPLE, 2)
    cut = (t - start) / 0.23
    if i and cut < 1:
        left = round(W * ease(cut))
        d.rectangle((left, 0, min(W, left + px(26)), H), fill=PURPLE)
    return im


def soundtrack(path):
    sr = 44100
    audio = np.zeros(sr * 40, dtype=np.float32)
    rng = np.random.default_rng(42)

    def add(at, values, volume):
        start = round(at * sr)
        stop = min(len(audio), start + len(values))
        if start < len(audio):
            audio[start:stop] += values[: stop - start] * volume

    for b in range(80):
        t = np.arange(round(0.22 * sr)) / sr
        add(
            b * 0.5,
            np.sin(2 * np.pi * (53 * t + 35 * 0.045 * (1 - np.exp(-t / 0.045)))) * np.exp(-t * 22),
            0.36,
        )
        t = np.arange(round(0.06 * sr)) / sr
        add(b * 0.5 + 0.25, rng.normal(0, 0.3, len(t)) * np.exp(-t * 85), 0.07)
        n = [220, 174.614, 261.626, 195.998][(b // 8) % 4] * (2 if b % 4 == 2 else 1)
        t = np.arange(round(0.4 * sr)) / sr
        add(b * 0.5, (np.sin(2 * np.pi * n * t) + 0.25 * np.sin(4 * np.pi * n * t)) * np.exp(-t * 11), 0.085)
    audio *= np.minimum(np.arange(len(audio)) / sr / 0.15, 1)
    audio *= np.minimum((len(audio) - np.arange(len(audio))) / sr / 1.2, 1)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sr)
        f.writeframes((np.clip(audio, -0.95, 0.95) * 32767).astype("<i2").tobytes())


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--ffmpeg", required=True)
    p.add_argument("--fonts", type=Path, default=Path("C:/Windows/Fonts"))
    p.add_argument("--previews-only", action="store_true")
    args = p.parse_args()
    global FONTS
    FONTS = args.fonts
    for d in [QA, OUT, MEDIA]:
        d.mkdir(parents=True, exist_ok=True)
    shots = []
    for i, s in enumerate(SCENES):
        shot = frame_at(s[0] + 1.65, {})
        shot.save(QA / f"scene-{i + 1:02}.jpg", quality=92)
        shots.append(shot.resize((270, 480), Image.Resampling.LANCZOS))
    sheet = Image.new("RGB", (1350, 960))
    for i, shot in enumerate(shots):
        sheet.paste(shot, ((i % 5) * 270, (i // 5) * 480))
    sheet.save(QA / "contact-sheet.jpg", quality=93)
    frame_at(1.65, {}).save(MEDIA / "reel-poster.jpg", quality=94)
    manifest = [{"start": s[0], "end": s[1], "section": s[2], "title": s[3], "caption": s[4]} for s in SCENES]
    (MEDIA / "reel-scenes.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    def stamp(s):
        return f"00:00:{s:02},000"

    captions = (
        "\n\n".join(f"{i + 1}\n{stamp(s[0])} --> {stamp(s[1])}\n{s[4]}" for i, s in enumerate(SCENES)) + "\n"
    )
    (OUT / "career-harness-reel.srt").write_text(captions, encoding="utf-8")
    if args.previews_only:
        return
    audio = QA / "original-beat.wav"
    soundtrack(audio)
    movie = OUT / "career-harness-reel.mp4"
    command = [
        args.ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "rawvideo",
        "-vcodec",
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
        str(audio),
        "-map",
        "0:v",
        "-map",
        "1:a",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-t",
        "40",
        "-movflags",
        "+faststart",
        str(movie),
    ]
    with (QA / "encode.log").open("wb") as log:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=log)
        cache = {}
        try:
            for n in range(40 * FPS):
                process.stdin.write(frame_at(n / FPS, cache).tobytes())
                if n % 120 == 0:
                    print(f"Rendered {n / FPS:.0f}/40 seconds", flush=True)
        finally:
            process.stdin.close()
        if process.wait() != 0:
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
            "[0:v]fps=8,scale=270:480:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse=dither=bayer",
            "-loop",
            "0",
            str(MEDIA / "reel-preview.gif"),
        ],
        check=True,
    )
    print(f"Done: {movie.stat().st_size:,} bytes", flush=True)


if __name__ == "__main__":
    main()
