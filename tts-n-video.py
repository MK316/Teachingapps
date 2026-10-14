import asyncio
import io
import subprocess
import tempfile
import zipfile
from pathlib import Path

import edge_tts
import imageio_ffmpeg
import streamlit as st
from PIL import Image, ImageDraw, ImageFont

st.set_page_config(page_title="Listening Audio Maker", page_icon="🎧")

VOICES = {
    "US English · Female (Aria)": "en-US-AriaNeural",
    "US English · Male (Guy)": "en-US-GuyNeural",
    "British English · Female (Sonia)": "en-GB-SoniaNeural",
    "British English · Male (Ryan)": "en-GB-RyanNeural",
    "Australian English · Female (Natasha)": "en-AU-NatashaNeural",
    "Korean · Female (SunHi)": "ko-KR-SunHiNeural",
}

# (path, index inside a .ttc collection). Noto Sans CJK also covers Korean.
FONT_PATHS = [
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 1),
    ("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 0),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 0),
]


async def make_audio(text, voice, rate, path):
    await edge_tts.Communicate(text, voice, rate=rate).save(str(path))


def load_font(size):
    for p, index in FONT_PATHS:
        if Path(p).exists():
            return ImageFont.truetype(p, size, index=index)
    return ImageFont.load_default(size=size)


def wrap_text(draw, text, font, max_width):
    """Wrap each line of text by words so that it fits max_width."""
    lines = []
    for paragraph in text.split("\n"):
        words, current = paragraph.split(), ""
        for word in words:
            trial = f"{current} {word}".strip()
            if draw.textlength(trial, font=font) <= max_width or not current:
                current = trial
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return "\n".join(lines)


def make_cover(label, path, width=1280, height=720, margin=80):
    img = Image.new("RGB", (width, height), "#1E3A5F")
    draw = ImageDraw.Draw(img)
    # Start big and shrink until the wrapped text fits on the screen
    for size in range(120, 27, -6):
        font = load_font(size)
        wrapped = wrap_text(draw, label, font, width - 2 * margin)
        left, top, right, bottom = draw.multiline_textbbox(
            (width / 2, height / 2), wrapped, font=font, anchor="mm", align="center", spacing=size // 4)
        if right - left <= width - 2 * margin and bottom - top <= height - 2 * margin:
            break
    draw.multiline_text((width / 2, height / 2), wrapped, fill="white", font=font,
                        anchor="mm", align="center", spacing=size // 4)
    img.save(path)


def make_video(cover, audio, video):
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", "-loop", "1", "-i", str(cover), "-i", str(audio),
         "-c:v", "libx264", "-tune", "stillimage", "-c:a", "aac", "-b:a", "192k",
         "-pix_fmt", "yuv420p", "-shortest", str(video)],
        check=True,
    )


# ---------------- UI ----------------
st.title("🎧 Listening Audio Maker")
st.caption("Turn sentences into natural-sounding audio (mp3) or videos (mp4) for Google Forms / YouTube.")

text = st.text_area(
    "Sentences (one per line)",
    height=200,
    placeholder="The blue ball is on the table.\nThe classroom is quiet.\nThe bunny has long ears.",
)

col1, col2 = st.columns(2)
with col1:
    voice_label = st.selectbox("Voice", list(VOICES))
    speed = st.slider("Speed (%)", -30, 20, -10, step=5,
                      help="Negative = slower. -10% is comfortable for learners.")
with col2:
    output = st.radio("Output", ["mp3 (audio)", "mp4 (video)", "Both"], index=1)

st.markdown("**Extra spoken text** — `{n}` is replaced by the sentence number.")
col3, col4 = st.columns(2)
with col3:
    use_prefix = st.checkbox("Add prefix (spoken before each sentence)")
    prefix = st.text_input("Prefix", value="Number {n}.", placeholder="e.g., Number {n}.",
                           disabled=not use_prefix, label_visibility="collapsed") if use_prefix else ""
with col4:
    use_suffix = st.checkbox("Add suffix (spoken after each sentence)")
    suffix = st.text_input("Suffix", value="", placeholder="e.g., Write your answer now.",
                           disabled=not use_suffix, label_visibility="collapsed") if use_suffix else ""

video_text = st.text_area(
    "Text on video (mp4 only)",
    value="Question {n}",
    height=80,
    help="Shown on every video. {n} is replaced by the question number. "
         "Long text wraps and shrinks to fit. Leave empty for a plain background.",
)

sentences = [s.strip() for s in text.splitlines() if s.strip()]

if st.button("Generate", type="primary", disabled=not sentences):
    want_mp3 = output in ("mp3 (audio)", "Both")
    want_mp4 = output in ("mp4 (video)", "Both")
    voice = VOICES[voice_label]
    rate = f"{speed:+d}%"

    workdir = Path(tempfile.mkdtemp())
    files = []
    progress = st.progress(0.0, text="Starting…")

    try:
        for i, sentence in enumerate(sentences, start=1):
            parts = [prefix.replace("{n}", str(i)), sentence, suffix.replace("{n}", str(i))]
            spoken = " ".join(part.strip() for part in parts if part.strip())
            name = f"q{i:02d}"
            audio = workdir / f"{name}.mp3"
            progress.progress((i - 1) / len(sentences), text=f"Making {name}…")

            asyncio.run(make_audio(spoken, voice, rate, audio))
            if want_mp3:
                files.append(audio)
            if want_mp4:
                cover = workdir / f"{name}.png"
                video = workdir / f"{name}.mp4"
                make_cover(video_text.replace("{n}", str(i)).strip(), cover)
                make_video(cover, audio, video)
                files.append(video)

            with st.expander(f"{name} — {sentence[:60]}{'…' if len(sentence) > 60 else ''}"):
                if want_mp4:
                    st.video(str(workdir / f"{name}.mp4"))
                else:
                    st.audio(str(audio))

        progress.progress(1.0, text="Done!")

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as z:
            for f in files:
                z.write(f, arcname=f.name)
        st.download_button("⬇️ Download all (zip)", buffer.getvalue(),
                           file_name="listening_files.zip", mime="application/zip")
        st.success(f"Created {len(files)} file(s).")

    except Exception as error:
        progress.empty()
        st.error(f"Something went wrong: {type(error).__name__}: {error}")

st.divider()
st.caption("Tip: after uploading videos to YouTube, delete the auto-generated captions "
           "so that students cannot read the sentences.")
