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

FONT_PATHS = [
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


async def make_audio(text, voice, rate, path):
    await edge_tts.Communicate(text, voice, rate=rate).save(str(path))


def load_font(size):
    for p in FONT_PATHS:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size=size)


def make_cover(label, path):
    img = Image.new("RGB", (1280, 720), "#1E3A5F")
    draw = ImageDraw.Draw(img)
    draw.text((640, 360), label, fill="white", font=load_font(120), anchor="mm")
    img.save(path)


def make_video(cover, audio, video):
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", "-loop", "1", "-i", str(cover), "-i", str(audio),
         "-c:v", "libx264", "-tune", "stillimage", "-c:a", "aac", "-b:a", "192k",
         "-pix_fmt", "yuv420p", "-shortest", str(video)],
        check=True,
    )


NUMBER_WORDS = ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
                "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen",
                "eighteen", "nineteen", "twenty"]


def number_word(n):
    return NUMBER_WORDS[n - 1] if n <= len(NUMBER_WORDS) else str(n)


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
    add_number = st.checkbox('Add "Number one." before each sentence', value=False)

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
            spoken = f"Number {number_word(i)}. {sentence}" if add_number else sentence
            name = f"q{i:02d}"
            audio = workdir / f"{name}.mp3"
            progress.progress((i - 1) / len(sentences), text=f"Making {name}…")

            asyncio.run(make_audio(spoken, voice, rate, audio))
            if want_mp3:
                files.append(audio)
            if want_mp4:
                cover = workdir / f"{name}.png"
                video = workdir / f"{name}.mp4"
                make_cover(f"Question {i}", cover)
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
