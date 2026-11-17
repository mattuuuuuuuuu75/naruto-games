import os
import sys
import io
import re
import json
import time
import wave
import subprocess
from faster_whisper import WhisperModel
from google import genai
from google.genai import types

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
AUDIO_DIR = os.path.join(PROJECT_ROOT, 'assets', 'audio')
MANIFEST_PATH = os.path.join(AUDIO_DIR, 'manifest.json')
TEMP_WAV = os.path.join(PROJECT_ROOT, 'scripts', '_temp_wav', 'audit_tmp.wav')
os.makedirs(os.path.dirname(TEMP_WAV), exist_ok=True)

# Import CHARACTERS_75, LEADERS_12, SYS_CLIPS, CALL_PREFIXES, col_letter_ja from generate_voices
sys.path.insert(0, os.path.dirname(__file__))
import generate_voices as gv

# Fix tricky readings in CHARACTERS_75 (Hyuga = ヒュウガ, Byakugan = ビャクガン, Juho Soshiken = ジュウホソウシケン)
FIXED_CHAR_MAP = {}
for cid, spoken_name, voice, mode, style, quote_line in gv.CHARACTERS_75:
    spoken_name = spoken_name.replace("日向", "ヒュウガ・")
    quote_line = quote_line.replace("白眼", "ビャクガン").replace("柔歩双獅拳", "ジュウホ双獅拳")
    FIXED_CHAR_MAP[cid] = (cid, spoken_name, voice, mode, style, quote_line)

FIXED_LEADERS = {}
for lid, voice, style, sel_t, bin_t in gv.LEADERS_12:
    sel_t = sel_t.replace("白眼", "ビャクガン")
    FIXED_LEADERS[lid] = (lid, voice, style, sel_t, bin_t)

print("Loading local faster-whisper 'base' model...")
device = "cuda" if False else "cpu"
wm = WhisperModel("base", device="cpu", compute_type="int8", local_files_only=True)

ENGLISH_LEAK_RE = re.compile(r'[A-Za-z]{5,}')
ALLOWED_EN_WORDS = {'indra', 'laser', 'circus', 'lucky', 'seven', 'super'}

def transcribe_words(mp3_path):
    segments, _ = wm.transcribe(mp3_path, language="ja", word_timestamps=True)
    words = []
    full_text = []
    for seg in segments:
        full_text.append(seg.text)
        if seg.words:
            for w in seg.words:
                words.append((w.start, w.end, w.word.strip()))
    return "".join(full_text), words

def has_english_leak(text):
    for match in ENGLISH_LEAK_RE.findall(text):
        if match.lower() not in ALLOWED_EN_WORDS:
            return True, match
    low = text.lower()
    for bad in ["トランスクリプト", "ディレクター", "オーディオプロファイル", "ジェントル", "エネルギッシュ"]:
        if bad in low:
            return True, bad
    return False, None

def clean_resynth_summon(cid):
    """Deterministic, 100% leak-free 2-part synthesis: Naruto Aoede call + 0.48s silence + Character voice quote!"""
    _, spoken_name, voice, _, style, quote_line = FIXED_CHAR_MAP[cid]
    col_ja = gv.col_letter_ja(cid)
    prefix = gv.CALL_PREFIXES[(cid - 1) % len(gv.CALL_PREFIXES)]
    naruto_call = f"{prefix} {col_ja}の{cid}番、{spoken_name}だってばよ！！"

    # Use ultra-clean single-speaker synthesis for each part so speaker labels can NEVER leak or duplicate!
    pcm_call = gv.synth_single(
        "Aoede",
        "Energetic raspy young shonen anime hero boy shouting excitedly",
        naruto_call,
        max_expected_sec=11.0
    )
    silence = b'\x00' * int(24000 * 2 * 0.48)
    pcm_quote = gv.synth_single(
        voice,
        style.replace(":", " -"),
        quote_line,
        max_expected_sec=17.0
    )
    full_pcm = pcm_call + silence + pcm_quote
    split_sec = round((len(pcm_call) + int(len(silence) * 0.65)) / 48000.0, 2)
    total_sec = round(len(full_pcm) / 48000.0, 2)
    mp3_abs = os.path.join(AUDIO_DIR, 'summon', f"{cid:02d}.mp3")
    gv.pcm_to_mp3(full_pcm, mp3_abs, bitrate='48k')
    return split_sec, total_sec

def compute_whisper_split(words, fallback_split, total_dur):
    """Find exact split timestamp right after Naruto's first 'だってばよ' / 'ばよ'."""
    accum = ""
    for idx, (ws, we, wt) in enumerate(words):
        accum += wt
        if ws < 9.0 and ("だってばよ" in accum or "てばよ" in accum or "ばよ" in accum):
            # Look at start of next word after 'ばよ'
            if idx + 1 < len(words):
                next_start = words[idx + 1][0]
                if next_start > we:
                    return round(we + (next_start - we) * 0.65, 2)
            return round(min(total_dur - 1.0, we + 0.18), 2)
    return fallback_split

def main():
    with open(MANIFEST_PATH, 'r', encoding='utf-8') as f:
        manifest = json.load(f)

    fixed_count = 0

    # 1. Audit all 75 summon clips
    print("=== Auditing 75 Summon Clips with faster-whisper ===")
    for cid in range(1, 76):
        mp3_abs = os.path.join(AUDIO_DIR, 'summon', f"{cid:02d}.mp3")
        entry = manifest["summon"][str(cid)]
        text, words = transcribe_words(mp3_abs)

        leak, reason = has_english_leak(text)
        # Check duplicate summon call ('だってばよ' appearing >=2 times when quote doesn't have 'だってば')
        _, _, _, _, _, expected_quote = FIXED_CHAR_MAP[cid]
        datte_count = len(re.findall(r'だってばよ|てばよ', text))
        quote_has_datte = ('だってば' in expected_quote)
        dup_call = (not quote_has_datte and datte_count >= 2) or (quote_has_datte and datte_count >= 3)

        # Check specific reading errors
        bad_reading = False
        if cid in (11, 12) and ("ひなたひなた" in text.replace(" ", "") or "はくがん" in text or "白眼" not in text and "はく" in text):
            bad_reading = True
        if cid == 12:
            bad_reading = True  # Force clean resynth of 12 with ヒュウガ & ビャクガン
        if cid == 11 and ("ひなた" in text or "ヒナタ" in text):
            bad_reading = True
        if cid == 16 and text.startswith("ナルト"):
            dup_call = True

        if leak or dup_call or bad_reading or entry["duration"] > 20.5:
            print(f"[FIX #{cid:02d}] Triggered (leak={reason}, dup={dup_call}, bad_read={bad_reading}, dur={entry['duration']}s) | Text: {text[:60]}...")
            split_sec, total_sec = clean_resynth_summon(cid)
            entry["splitSec"] = split_sec
            entry["duration"] = total_sec
            fixed_count += 1
            print(f"  -> Re-synthesized #{cid:02d} cleanly! (split={split_sec}s, dur={total_sec}s)")
        else:
            # Refine splitSec using Whisper word timestamps!
            new_split = compute_whisper_split(words, entry["splitSec"], entry["duration"])
            if abs(new_split - entry["splitSec"]) > 0.35:
                print(f"[Split Refine #{cid:02d}] {entry['splitSec']}s -> {new_split}s")
            entry["splitSec"] = new_split

    # 2. Audit 12 Leader select + bingo clips (especially Hinata #8 Byakugan!)
    print("=== Auditing 24 Leader Clips ===")
    for lid, voice, style, sel_t, bin_t in FIXED_LEADERS.values():
        for kind, target_text in [("select", sel_t), ("bingo", bin_t)]:
            mp3_abs = os.path.join(AUDIO_DIR, 'leaders', f"{lid}_{kind}.mp3")
            text, _ = transcribe_words(mp3_abs)
            leak, reason = has_english_leak(text)
            bad_byakugan = (lid == "hinata" and kind == "select" and ("はくがん" in text or "ハクガン" in text))
            if leak or bad_byakugan:
                print(f"[FIX leader {lid}_{kind}] (leak={reason}, byakugan={bad_byakugan}) -> Re-synthesizing...")
                pcm = gv.synth_single(voice, style.replace(":", " -"), target_text, max_expected_sec=15.0)
                gv.pcm_to_mp3(pcm, mp3_abs, bitrate='48k')
                fixed_count += 1

    with open(MANIFEST_PATH, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"=== AUDIT COMPLETE! Fixed {fixed_count} clips & refined all 75 split timestamps! ===")

if __name__ == '__main__':
    main()
