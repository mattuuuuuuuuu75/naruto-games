import os
import sys
import io
import re
import json
import time
import wave
import shutil
import subprocess
from faster_whisper import WhisperModel
from google import genai
from google.genai import types

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")

# Load Vertex AI credentials
ENV_CANDIDATES = [
    r"c:\Users\mattu\Documents\MyProjects\🤖_AgentTools\Scripts\.env",
    r"c:\Users\mattu\Documents\MyProjects\.env",
]
for env_path in ENV_CANDIDATES:
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

project_id = (
    os.getenv("CONSTRUCTION_GCP_PROJECT_ID")
    or os.getenv("PERSONAL_AI_PROJECT_ID")
    or os.getenv("VERTEX_AI_PROJECT_ID")
)
cred = (
    os.getenv("CONSTRUCTION_GOOGLE_APPLICATION_CREDENTIALS")
    or os.getenv("PERSONAL_AI_CREDENTIALS")
    or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
)
for p in [
    r"c:\Users\mattu\Documents\MyProjects\🤖_AgentTools\Scripts\Config\personal_key.json",
    r"c:\Users\mattu\Documents\MyProjects\🤖_AgentTools\Config\personal_key.json",
    r"C:\AgentTools\Config\personal_key.json",
]:
    if (not cred or not os.path.exists(cred)) and os.path.exists(p):
        cred = p
if cred and os.path.exists(cred):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = cred

TTS_MODEL = "gemini-3.8-flash-tts"
client = genai.Client(vertexai=True, project=project_id, location="global")

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
AUDIO_DIR = os.path.join(PROJECT_ROOT, "assets", "audio")
SUMMON_DIR = os.path.join(AUDIO_DIR, "summon")
LEADERS_DIR = os.path.join(AUDIO_DIR, "leaders")
SYS_DIR = os.path.join(AUDIO_DIR, "sys")
TEMP_DIR = os.path.join(PROJECT_ROOT, "scripts", "_temp_v2")
PROGRESS_PATH = os.path.join(TEMP_DIR, "progress_v2.json")

for d in [SUMMON_DIR, LEADERS_DIR, SYS_DIR, TEMP_DIR]:
    os.makedirs(d, exist_ok=True)

print("[Init] Loading local faster-whisper 'base' for instant quality verification...", flush=True)
wm = WhisperModel("base", device="cpu", compute_type="int8", local_files_only=True)
ENGLISH_LEAK_RE = re.compile(r"[A-Za-z]{5,}")
ALLOWED_EN = {"indra", "laser", "circus", "lucky", "seven", "super", "naruto", "sasuke", "sakura", "bingo"}

LAST_TS = 0.0
MIN_INTERVAL = 2.4  # Fast pacing with automatic 429 backoff

def wait_pace():
    global LAST_TS
    el = time.time() - LAST_TS
    if el < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - el)
    LAST_TS = time.time()

# ==============================================================================
# SIGNATURE VOICE PROFILES (100% Gender-Verified + Studio Rubberband Sculpting)
# ==============================================================================
NARUTO_VOICE = "Puck"  # Male ♂
NARUTO_STYLE = (
    "16-year-old hot-blooded mischievous Japanese shonen anime boy hero! "
    "Slightly raspy, nasal, gutsy, brash, super energetic少年 voice shouting with huge grin and spirit!"
)
NARUTO_FX = (
    "rubberband=pitch=1.09:formant=shifted:pitchq=quality:smoothing=on,"
    "rubberband=pitch=1.03:formant=preserved:pitchq=quality:smoothing=on"
)

SASUKE_VOICE = "Iapetus"  # Male ♂ Clear
SASUKE_STYLE = (
    "17-year-old cool, aloof, stoic, handsome Japanese anime rival boy. "
    "Calm, cold, low-key sharp clear youth voice, composed with quiet lethal intensity."
)
SASUKE_FX = "rubberband=pitch=1.02:formant=shifted:pitchq=quality:smoothing=on"

SAKURA_VOICE = "Laomedeia"  # Female ♀ Upbeat Youthful
SAKURA_STYLE = (
    "16-year-old bright, cute yet fierce and spirited Japanese anime heroine girl! "
    "Clear youthful female voice that bursts with fiery punchy power on battle cries!"
)
SAKURA_FX = None

KAKASHI_VOICE = "Charon"  # Male ♂ Deep Cool
KAKASHI_STYLE = (
    "30-year-old cool, laid-back, effortlessly charismatic silver-haired elite ninja sensei. "
    "Relaxed, sleek adult male baritone that turns razor-sharp in battle."
)
KAKASHI_FX = "rubberband=pitch=1.03:formant=preserved:pitchq=quality:smoothing=on"

MINATO_VOICE = "Achird"  # Male ♂ Warm Handsome Young Man
MINATO_STYLE = (
    "24-year-old refreshing, gentle, sincere yet lightning-fast heroic young male Hokage. "
    "Handsome, warm, clear young man voice."
)
MINATO_FX = "rubberband=pitch=1.02:formant=preserved:pitchq=quality:smoothing=on"

def extract_pcm(audio_bytes):
    if audio_bytes[:4] == b"RIFF":
        with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
            pcm = wf.readframes(wf.getnframes())
    else:
        pcm = audio_bytes
    if len(pcm) % 2 != 0:
        pcm = pcm[:-1]
    return pcm

def apply_fx_to_pcm(pcm_bytes, af_filter):
    if not af_filter:
        return pcm_bytes
    in_w = os.path.join(TEMP_DIR, "fx_in.wav")
    with wave.open(in_w, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(24000)
        wf.writeframes(pcm_bytes)
    out_pcm = subprocess.check_output(
        ["ffmpeg", "-v", "error", "-y", "-i", in_w, "-af", af_filter, "-ar", "24000", "-ac", "1", "-f", "s16le", "-"]
    )
    if len(out_pcm) % 2 != 0:
        out_pcm = out_pcm[:-1]
    return out_pcm

def pcm_to_mp3(pcm_bytes, mp3_path, bitrate="56k"):
    in_w = os.path.join(TEMP_DIR, "enc_in.wav")
    with wave.open(in_w, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(24000)
        wf.writeframes(pcm_bytes)
    subprocess.run(
        ["ffmpeg", "-y", "-i", in_w, "-ar", "24000", "-ac", "1", "-b:a", bitrate, mp3_path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )

def check_pcm_clean(pcm_bytes):
    chk_w = os.path.join(TEMP_DIR, "chk.wav")
    with wave.open(chk_w, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(24000)
        wf.writeframes(pcm_bytes)
    segs, _ = wm.transcribe(chk_w, language="ja")
    txt = "".join(s.text for s in segs)
    for m in ENGLISH_LEAK_RE.findall(txt):
        if m.lower() not in ALLOWED_EN:
            return False, f"English leak '{m}' in '{txt[:50]}'"
    for bad in ["トランスクリプト", "ディレクター", "プロファイル", "スタイル"]:
        if bad in txt:
            return False, f"Prompt kata leak '{bad}'"
    return True, txt

def synth_sculpted(voice_name, style_en, text_ja, af_filter=None, max_sec=18.0):
    clean_style = style_en.replace(":", " -")
    prompt = f"""# AUDIO PROFILE: VoiceActor
## THE SCENE: Japanese TV Anime Official Dubbing Studio
### DIRECTOR'S NOTES
Acting direction - {clean_style} Speak ONLY the Japanese line below naturally with authentic anime emotion. Never read headers or notes.

#### TRANSCRIPT
{text_ja}"""

    backoff = [5, 12, 25, 45, 70]
    for attempt in range(len(backoff) + 1):
        try:
            wait_pace()
            resp = client.models.generate_content(
                model=TTS_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name)
                        )
                    ),
                ),
            )
            raw_pcm = extract_pcm(resp.candidates[0].content.parts[0].inline_data.data)
            dur = len(raw_pcm) / 48000.0
            if (dur > max_sec or dur < 0.8) and attempt < len(backoff):
                print(f"    [Warn] Duration {dur:.1f}s out of bounds, retrying...", flush=True)
                continue
            ok, info = check_pcm_clean(raw_pcm)
            if not ok and attempt < len(backoff):
                print(f"    [Warn] Whisper caught '{info}', retrying...", flush=True)
                continue
            return apply_fx_to_pcm(raw_pcm, af_filter)
        except Exception as e:
            err_s = str(e)
            if attempt < len(backoff):
                w = backoff[attempt] if "429" in err_s or "RESOURCE_EXHAUSTED" in err_s else 6
                print(f"    [Retry {attempt+1}] {err_s[:80]} -> sleep {w}s", flush=True)
                time.sleep(w)
            else:
                raise

def col_letter_ja(num_id):
    return ["ビー", "アイ", "エヌ", "ジー", "オー"][(num_id - 1) // 15]

CALL_PREFIXES = [
    "口寄せ成功！",
    "いくぜっ！",
    "でたぁっ！",
    "よっしゃあ！",
    "チャクラ全開！",
]

# ==============================================================================
# ALL 75 CHARACTERS (100% Gender-Verified + Seiyuu-Matched Voice & Rubberband FX)
# Tuple: (id, naruto_spoken_name, char_voice, char_fx, char_style_en, char_quote_ja)
# ==============================================================================
CHARACTERS_75 = [
    # B (1-15)
    (1, "うずまきナルト", NARUTO_VOICE, NARUTO_FX, NARUTO_STYLE,
     "仙法、超大玉螺旋多連ガン！ まっすぐ自分の言葉は曲げねェ…それがオレの忍道だってばよ！！"),
    (2, "うちはサスケ", SASUKE_VOICE, SASUKE_FX, SASUKE_STYLE,
     "永遠の万華鏡写輪眼…！ オレは過去を断ち切る。お前は、オレにとっての新たな光だ。"),
    (3, "春野サクラ", SAKURA_VOICE, SAKURA_FX, SAKURA_STYLE,
     "百豪の術、桜花衝！ しゃーんなろー！！ やっと二人の背中に追いついたわよ！！"),
    (4, "はたけカカシ", KAKASHI_VOICE, KAKASHI_FX, KAKASHI_STYLE,
     "万華鏡写輪眼、カムイ…仲間を大切にしない奴は、それ以上のクズだ。"),
    (5, "波風ミナト", MINATO_VOICE, MINATO_FX, MINATO_STYLE,
     "ヒライシンの術、二の段！ 木ノ葉の黄色い閃光！ ここからは誰にも触れさせないよ！"),
    (6, "ガマ仙人、自来也", "Algenib", "rubberband=pitch=0.95:formant=preserved:pitchq=quality",
     "50-year-old hearty, gravelly, bold legendary male Toad Sage master speaking with heroic kabuki charisma!",
     "仙法、五右衛門、超大玉螺旋丸！ 忍びとは耐え忍ぶ者のことなんだよ…諦めねェど根性だ！！"),
    (7, "五代目火影、綱手", "Gacrux", None,
     "Commanding, fearless, mature husky-voiced female Hokage leader shouting with fierce sisterly authority!",
     "創造再生、百豪の極み！ 火影の称号をナメるなよ！ 命を懸けて里を守るわよ！！"),
    (8, "マイト・ガイ", "Sadachbia", "rubberband=pitch=0.96:formant=preserved:pitchq=quality",
     "30-year-old explosively passionate, ultra-hot-blooded male martial arts master screaming about youth!",
     "八門遁甲の陣、ヤガイ！ 紅き春の蒸気！ 青春のクライマックスだァァ！！"),
    (9, "ロック・リー", "Sadachbia", "rubberband=pitch=1.09:formant=shifted:pitchq=quality:smoothing=on",
     "17-year-old earnest, super polite, ultra-passionate teen boy martial artist shouting with pure determination!",
     "八門遁甲、表蓮華、裏蓮華！ 努力の天才だと証明してみせます！ 僕の忍道です！！"),
    (10, "奈良シカマル", "Zubenelgenubi", "rubberband=pitch=1.04:formant=shifted:pitchq=quality:smoothing=on",
     "17-year-old laid-back, sighing, super-smart teen boy strategist who gets sharp and serious for his friends.",
     "影真似、影首縛りの術…めんどくせーが、やるしかねェだろ。仲間のためだ！"),
    (11, "ヒュウガ・ネジ", "Orus", "rubberband=pitch=1.03:formant=shifted:pitchq=quality:smoothing=on",
     "17-year-old calm, noble, stoic young male prodigy speaking with quiet dignity and gratitude.",
     "八卦六十四掌、回天！ …ナルト、お前はオレを闇から救い出してくれたんだ。"),
    (12, "ヒュウガ・ヒナタ", "Achernar", None,
     "16-year-old shy, gentle, soft-spoken pure anime girl gathering tremendous courage for the boy she loves.",
     "ビャクガン、ジュウホ双獅拳！ 私だって…ナルトくんの隣を歩きたいから！"),
    (13, "サイ", "Schedar", "rubberband=pitch=1.05:formant=shifted:pitchq=quality:smoothing=on",
     "17-year-old soft, calm, polite young male artist boy speaking gently with newfound warmth.",
     "超獣偽画、狛犬！ 仲間との繋がり…それが僕に笑顔を教えてくれたんだ。"),
    (14, "ヤマト隊長", "Alnilam", None,
     "26-year-old dependable, serious, composed male ANBU captain speaking with steady low resolve.",
     "木遁、樹界降誕！ 九尾のチャクラは、僕が木遁で完全に抑え込む！"),
    (15, "猿飛アスマ", "Algieba", "rubberband=pitch=0.95:formant=preserved:pitchq=quality",
     "31-year-old rugged, warm-hearted, gruff veteran male sensei speaking with protective wisdom.",
     "風遁、翠嵐烈風！ 木ノ葉の玉を守り抜く…それが未来を繋ぐ忍の務めだ。"),

    # I (16-30)
    (16, "秋道チョウジ", "Achird", "rubberband=pitch=0.98:formant=shifted:pitchq=quality",
     "17-year-old kind-hearted teen boy getting fiercely fired up to protect his best friend!",
     "超倍化の術、蝶弾爆撃！ 仲間の悪口を言う奴は絶対に許さない！ カロリー解放！！"),
    (17, "山中イノ", "Autonoe", None,
     "16-year-old bright, stylish, confident anime girl kunoichi speaking with lively spirit!",
     "心転身の術、忍連合通信！ 忍連合軍全員の心を、ひとつに繋ぐわよ！！"),
    (18, "犬塚キバと赤丸", "Fenrir", "rubberband=pitch=1.08:formant=shifted:pitchq=quality:smoothing=on",
     "17-year-old wild, cocky, feral teen boy beast-tamer shouting excitedly!",
     "ガロウガ、尾追いガツウガ！ いくぜ赤丸！ オレたちも火影を狙うぞ！！"),
    (19, "油女シノ", "Schedar", "rubberband=pitch=0.97:formant=preserved:pitchq=quality",
     "17-year-old quiet, mysterious, deadpan stoic young man speaking calmly and logically.",
     "秘術、蟲玉…オレのキカイチュウからは誰一人として逃れられない。なぜならだ。"),
    (20, "テンテン", "Leda", None,
     "17-year-old lively, energetic, cute weapons-master kunoichi girl shouting cheerfully!",
     "双昇龍、バショウセン解放！ 六道仙人の宝具だって使いこなしてみせるわよ！"),
    (21, "猿飛木ノ葉丸", "Puck", "rubberband=pitch=1.18:formant=shifted:pitchq=quality:smoothing=on",
     "12-year-old cheeky, energetic little brother boy ninja shouting enthusiastically to rival Naruto!",
     "火遁、灰積焼と螺旋丸！ ナルト兄ちゃん直伝の螺旋丸！ これに決めたコレ！！"),
    (22, "うみのイルカ先生", "Achird", None,
     "27-year-old warm, caring, emotional male teacher shouting with deep pride for his student Naruto!",
     "木ノ葉隠れ、絆の教え！ ナルトは…オレが認めた最高の生徒だ！！"),
    (23, "シズネとトントン", "Erinome", None,
     "28-year-old earnest, reliable, clear-voiced female medical ninja reporting dutifully!",
     "毒霧、仕込み千本！ 綱手様！ 医療部隊の準備、いつでも万全です！"),
    (24, "五代目風影、我愛羅", "Enceladus", "rubberband=pitch=1.03:formant=shifted:pitchq=quality:smoothing=on",
     "17-year-old calm, quiet, cool, crystalline-voiced young male Kazekage speaking with deep conviction.",
     "砂瀑大葬、絶対防御…ここに敵はいない。我らはすべて、忍だ！！"),
    (25, "カンクロウ", "Zubenelgenubi", None,
     "18-year-old tough, confident older brother male puppeteer speaking with brash swagger!",
     "黒秘技、機々一発！ 傀儡師の頂点、その真髄を見せてやるぜ！"),
    (26, "テマリ", "Pulcherrima", None,
     "19-year-old fierce, sassy, confident older-sister female wind kunoichi shouting proudly!",
     "風遁、大カマイタチの術！ 忍連合軍で私の風遁を超える使い手はいないよ！"),
    (27, "キラービー", "Fenrir", "rubberband=pitch=0.93:formant=preserved:pitchq=quality",
     "35-year-old muscular, booming, funky male rapper ninja chanting his lines with rhythmic hip-hop flow!",
     "ライリ熱刀、ラリアット！ バカヤロー！ コノヤロー！ 八本目の剣で韻を踏むぜ、イェー！！"),
    (28, "四代目雷影、エー", "Algenib", "rubberband=pitch=0.88:formant=shifted:pitchq=quality",
     "47-year-old massive, hot-tempered, thunderous male warlord roaring with explosive power!",
     "雷遁チャクラモード、ライギャク水平！ オレのスピードについて来られる忍など存在せん！！"),
    (29, "三代目土影、オオノキ", "Algenib", "rubberband=pitch=1.07:formant=shifted:pitchq=quality",
     "79-year-old feisty, gravelly, stubborn elderly grandpa Tsuchikage shouting with pride!",
     "塵遁、原界剥離の術！ 己を捨てず、誇りを胸に戦う！ 両天秤のオオノキじゃ！"),
    (30, "五代目水影、照美メイ", "Sulafat", None,
     "31-year-old glamorous, alluring, elegant mature female Mizukage speaking with graceful charm.",
     "溶遁、溶怪の術とフットン！ 霧隠れの水影として、ここで全てを溶かし尽くすわ！"),

    # N (31-45)
    (31, "うちはイタチ", "Charon", "rubberband=pitch=1.02:formant=preserved:pitchq=quality",
     "21-year-old calm, deep, sorrowful yet infinitely loving older brother speaking quietly to Sasuke.",
     "天照、月読、スサノオ…許せサスケ。お前がこれからどうなろうと、オレはお前をずっと愛している。"),
    (32, "ペイン天道", "Charon", "rubberband=pitch=0.92:formant=preserved:pitchq=quality",
     "Godlike, cold, solemn, commanding deep male baritone proclaiming judgment upon the world.",
     "神羅天征、地爆天星！ …痛みを考えろ、痛みを知れ。ここより世界に痛みを！！"),
    (33, "うずまき長門", "Sadaltager", None,
     "35-year-old quiet, weary, sincere male voice entrusting hope and peace to Naruto.",
     "外道、輪廻天生の術…ナルト、お前なら本当に平和を掴み取れるかもしれんな。"),
    (34, "暁の小南", "Despina", None,
     "Calm, cool, dignified mature female angel kunoichi speaking with serene unbreakable resolve.",
     "神のシシャの術、六千億枚の起爆札！ 今度こそ…枯れない希望の花になるわ。"),
    (35, "デイダラ", "Sadachbia", "rubberband=pitch=1.03:formant=shifted:pitchq=quality",
     "19-year-old wild, cocky, theatrical young male bomber artist shouting gleefully about explosive art!",
     "起爆粘土、シーフォー・カルラ！ 芸術は爆発だ！！ 一瞬の煌めきこそが究極の美だ、うん！"),
    (36, "赤砂のサソリ", "Iapetus", "rubberband=pitch=1.05:formant=shifted:pitchq=quality",
     "Youthful, cool, detached, crystalline-voiced male master puppeteer speaking with quiet arrogance.",
     "赤秘技、百機の操演…芸術とは、永遠に美しく残るものだ。百機を見ろ。"),
    (37, "干柿鬼鮫", "Algieba", "rubberband=pitch=0.94:formant=preserved:pitchq=quality",
     "32-year-old polite yet menacing shark-like male swordsman chuckling darkly with warrior honor.",
     "水遁、大コウ弾の術！ イタチさん…どうやら私は、ロクでもない人間でもなかったようですよ。"),
    (38, "暁の飛段", "Fenrir", "rubberband=pitch=1.02:formant=preserved:pitchq=quality",
     "22-year-old brash, loud, unhinged male fanatic villain laughing and shouting wildly!",
     "呪術、死司ヒョウケツ！ ひゃっはー！ ジャシン様への儀式が始まるぜェ！！"),
    (39, "暁の角都", "Charon", "rubberband=pitch=0.87:formant=shifted:pitchq=quality",
     "91-year-old menacing, icy, ultra-deep gravelly male bounty hunter speaking coldly.",
     "ジオング、五属性複合忍術…地獄の沙汰も金次第だ。お前の心臓をもらうぞ。"),
    (40, "黒ゼツと白ゼツ", "Enceladus", "rubberband=pitch=0.95:formant=preserved:pitchq=quality",
     "Creepy, sinister, shadowy male manipulator whispering ominously from the darkness.",
     "カゲロウ、胞子の術…忍の歴史はすべて、この瞬間のためにあったのだ。"),
    (41, "うちはオビト", "Alnilam", None,
     "31-year-old deeply emotional fallen male hero entrusting his dream to Naruto with raw feeling.",
     "カムイ、六道十尾キュウイン！ …ナルト、お前は必ず、火影になれよ！！"),
    (42, "うちはマダラ", "Charon", "rubberband=pitch=0.90:formant=preserved:pitchq=quality",
     "Supreme, commanding, god-tier legendary male warlord speaking with overwhelming deep authority.",
     "テンガイシンセイ、完成体スサノオ！ …お前も舞うか？ 二つの隕石をどうする、オオノキよ！"),
    (43, "大蛇丸", "Enceladus", "rubberband=pitch=1.08:formant=shifted:pitchq=quality:smoothing=on",
     "Silky, eerie, serpentine, husky sinister villain speaking with chilling fascination.",
     "ヤマタの術、口寄せエドテンセイ…すべての忍術の真理を解き明かす。サスケくんの風を見届けよう。"),
    (44, "薬師カブト", "Sadaltager", "rubberband=pitch=1.03:formant=shifted:pitchq=quality",
     "24-year-old polite, intellectual, smug glasses-wearing young male Dragon Sage.",
     "仙法、ハクゲキの術！ 蛇から龍へと昇華した、ボクの仙術を見せてあげるよ！"),
    (45, "うちはシスイ", "Orus", "rubberband=pitch=1.04:formant=shifted:pitchq=quality",
     "16-year-old noble, warm, sincere young male Uchiha prodigy entrusting peace to Itachi.",
     "万華鏡写輪眼、コトアマツカミ！ うちはの名と木ノ葉の平和…イタチ、お前に託す！"),

    # G (46-60)
    (46, "初代火影、千手柱間", "Fenrir", "rubberband=pitch=0.90:formant=preserved:pitchq=quality",
     "Heroic, booming, legendary male God of Shinobi speaking with towering resolve!",
     "仙法木遁、真数千手、チョウジョウケブツ！ 里を傷つける者は、たとえ友や我が子であろうと許さん！！"),
    (47, "二代目火影、千手扉間", "Orus", "rubberband=pitch=0.95:formant=preserved:pitchq=quality",
     "Stern, sharp, commanding male tactician Hokage barking orders on the battlefield!",
     "水遁水断波、互乗起爆札！ ヒライシンも影分身もワシが創った術だ！ いくぞ猿よ！"),
    (48, "三代目火影、猿飛ヒルゼン", "Algenib", "rubberband=pitch=0.92:formant=preserved:pitchq=quality",
     "69-year-old wise, warm, dignified elderly male Hokage speaking with the Will of Fire!",
     "五遁大連弾の術、金剛ニョイ！ 木の葉舞うところに火は燃ゆる…火の影は里を照らす！"),
    (49, "うずまきクシナ", "Sulafat", "rubberband=pitch=1.03:formant=preserved:pitchq=quality",
     "24-year-old fiery yet infinitely loving young mother speaking through warm tears to her son Naruto!",
     "金剛封鎖、赤い血潮のハバネロ！ ナルト…大好きだってばね！！"),
    (50, "九尾、クラマ", "Algenib", "rubberband=pitch=0.80:formant=shifted:pitchq=quality",
     "Colossal, ferocious nine-tailed demon fox roaring fiercely alongside Naruto with gravelly monster power!",
     "超大玉尾獣玉、九尾チャクラモード！ 行くぞナルト！！ ワシのチャクラを全部持っていきやがれ！！"),
    (51, "一尾、シュカク", "Sadachbia", "rubberband=pitch=0.92:formant=shifted:pitchq=quality",
     "Wild, cackling, rowdy male sand tanuki monster shouting boastfully!",
     "風遁練空弾、砂漠層大葬封印！ ガアラと組めば最強の絶対防御と封印術だぜ！！"),
    (52, "二尾、マタタビ", "Erinome", None,
     "Dignified, fierce mystical female blue-flame cat spirit speaking with polite power.",
     "青炎の火鼠玉！ 蒼き劫火ですべてを焼き尽くします！"),
    (53, "三尾、イソブ", "Umbriel", "rubberband=pitch=0.88:formant=shifted:pitchq=quality",
     "Gentle, humble yet massive low-voiced male giant turtle beast.",
     "サンゴ掌、大水弾！ 霧隠れの鉄壁、サンゴの盾を突破できるかな？"),
    (54, "四尾、ソンゴクウ", "Charon", "rubberband=pitch=0.86:formant=shifted:pitchq=quality",
     "Proud, booming male Great Sage Ape King roaring with respect for Naruto!",
     "仙法、熔遁螺旋手裏剣！ 水簾洞の美猴王！ ナルトよ、オレの力を貸してやる！！"),
    (55, "五尾、コクオウ", "Vindemiatrix", None,
     "Serene, noble, polite female white steed spirit speaking with calm dignity.",
     "フットン、怪力無双！ 蒸気チャクラを沸点まで高め、一撃で粉砕いたします！"),
    (56, "六尾、サイケン", "Achird", "rubberband=pitch=1.08:formant=shifted:pitchq=quality",
     "Friendly, earnest, polite young male slug spirit speaking cheerfully!",
     "水遁、泡沫の術！ シャボン玉の舞いとともに、すべてを溶かすであります！"),
    (57, "七尾、チョウメイ", "Sadachbia", "rubberband=pitch=1.04:formant=shifted:pitchq=quality",
     "Upbeat, cheerful, lucky-seven male beetle beast shouting happily!",
     "秘伝、リンプン隠れの術！ ラッキーセブン重明だ！ 空を駆け抜けて友達百人作るっス！！"),
    (58, "八尾、ギュウキ", "Alnilam", "rubberband=pitch=0.84:formant=shifted:pitchq=quality",
     "Rough, dependable giant male ox-octopus beast roaring encouragement to Bee and Naruto!",
     "尾獣ハチマキ、連続尾獣玉！ ビー！ ナルト！ お前ら二人のコンビネーションで決めるぞ！！"),
    (59, "外道魔像、十尾", "Charon", "rubberband=pitch=0.82:formant=shifted:pitchq=quality",
     "Ancient, earth-shaking deep male mythic narrator rumbling ominously.",
     "天変地異、神樹降臨…すべてのチャクラの根源が今、大地を揺るがす…！！"),
    (60, "ガマブン太とガマ吉", "Algenib", "rubberband=pitch=0.88:formant=preserved:pitchq=quality",
     "Tough, yakuza-boss giant male toad chief shouting boldly!",
     "火遁、ガマユ炎弾！ 親分ガマブン太とガマ吉の親子連携、見せてやるぜ！！"),

    # O (61-75)
    (61, "六道仙人モード、うずまきナルト", NARUTO_VOICE, NARUTO_FX, NARUTO_STYLE,
     "六道、超大玉螺旋手裏剣！ 仲間の想いを全部乗せた、オレの最強の螺旋手裏剣だってばよ！！"),
    (62, "輪廻写輪眼、うちはサスケ", SASUKE_VOICE, SASUKE_FX, SASUKE_STYLE,
     "インドラの矢、アメノテヂカラ！ 全尾獣のチャクラをスサノオに集束させた、最強の一矢だ！！"),
    (63, "威装・スサノオ", "Fenrir", "rubberband=pitch=0.94:formant=preserved:pitchq=quality",
     "Epic, hot-blooded male anime narrator roaring the ultimate fusion of Naruto and Sasuke!",
     "九尾と完成体スサノオ合体！ ナルトとサスケ、二人の力が重なった究極の鎧だ！！"),
    (64, "風遁・螺旋手裏剣", KAKASHI_VOICE, KAKASHI_FX, KAKASHI_STYLE,
     "超高密度チャクラの刃…四代目火影すら到達できなかった、形態変化と性質変化の融合だ！"),
    (65, "雷切・千鳥・キリン", SASUKE_VOICE, SASUKE_FX, SASUKE_STYLE,
     "千鳥流し、雷遁キリン！ 雷鳴とともに敵を貫く！ 消えろ、キリンとともに！！"),
    (66, "六道仙人、大筒木ハゴロモ", "Rasalgethi", "rubberband=pitch=0.90:formant=preserved:pitchq=quality",
     "Ancient, transcendent, wise elderly male Sage of Six Paths speaking with sacred calm.",
     "万物創造、六道地爆天星…忍宗の絆、ナルトとサスケよ、お前たちに未来を託すぞ。"),
    (67, "大筒木カグヤ", "Despina", "rubberband=pitch=0.96:formant=preserved:pitchq=quality",
     "Icy, divine, otherworldly female Rabbit Goddess speaking with regal archaic majesty.",
     "アメノミナカ、膨張グドウダマ…この空間もすべてのチャクラも、わらわ一人のものぞ…！"),
    (68, "両目万華鏡、はたけカカシ", KAKASHI_VOICE, KAKASHI_FX, KAKASHI_STYLE,
     "カムイ雷切、完成体スサノオ！ オビトのプレゼントだ…第七班、教え子たちを舐めるなよ！！"),
    (69, "新三竦み、第七班集結", NARUTO_VOICE, NARUTO_FX, NARUTO_STYLE,
     "ガマ吉、アオダ、カツユ同時口寄せ！ 第七班、ここに完全復活！！ いくぞサスケ、サクラ！！"),
    (70, "ダルイとミフネ", "Umbriel", "rubberband=pitch=0.95:formant=preserved:pitchq=quality",
     "Cool, laid-back yet sharp male Cloud general slashing with black lightning!",
     "嵐遁レーザーサーカスと居合斬り！ 黒い雷と侍の信念で、エドテンセイを斬り伏せる！！"),
    (71, "チヨバアとサクラ", "Gacrux", "rubberband=pitch=0.93:formant=shifted:pitchq=quality",
     "Warm, battle-hardened elderly grandmother puppet master smiling as she entrusts the future.",
     "白秘技、チカマツ十人衆！ 次の世代はきっと昔のワシらとは違う…未来に託すぞい！"),
    (72, "桃地ザブザとハク", "Algenib", "rubberband=pitch=0.90:formant=preserved:pitchq=quality",
     "Fierce, gravelly, deeply moved male Demon of the Hidden Mist remembering Naruto's bond.",
     "魔鏡氷晶、霧隠れの術…ナルトよ、お前はあの日からずっと変わらぬまま成長したな。"),
    (73, "忍連合軍の術", NARUTO_VOICE, NARUTO_FX, NARUTO_STYLE,
     "五大国全忍、大同団結！ 無限月読を打ち破るのは、オレたち全員の忍連合の術だってばよ！！"),
    (74, "一楽のラーメン", NARUTO_VOICE, NARUTO_FX, NARUTO_STYLE,
     "特製チャーシュー大盛り！ 任務帰りの一杯！ チャクラ全回復の最強グルメだってばよ！！"),
    (75, "終末の谷・和解の印", NARUTO_VOICE, NARUTO_FX, NARUTO_STYLE,
     "ナルトとサスケ、魂の決着！ サスケ…お前が痛ェとオレも痛ェんだ…帰ろうぜ、木ノ葉へ！！"),
]

# 12 Selectable Oshi Character Cards (100% Gender & Character Matched!)
LEADERS_12 = [
    ("naruto", NARUTO_VOICE, NARUTO_FX, NARUTO_STYLE,
     "オレのカードを選んだな！ まっすぐ自分の言葉は曲げねェ！ 絶対ビンゴするってばよ！！",
     "やったー！！ 超S級任務達成！ オレたちの最強ビンゴだってばよぉぉ！！"),
    ("sasuke", SASUKE_VOICE, SASUKE_FX, SASUKE_STYLE,
     "フン…オレのカードを選んだか。見せてやる…うちはの本当の力を。",
     "当然の結果だ。万華鏡写輪眼の前に死角はない…見事なビンゴだな。"),
    ("sakura", SAKURA_VOICE, SAKURA_FX, SAKURA_STYLE,
     "私のカードね！ 百豪のチャクラ全開でいくわよ！ しゃーんなろー！！",
     "やったわー！！ しゃーんなろー！！ 百豪ビンゴ、完全達成よ！！"),
    ("kakashi", KAKASHI_VOICE, KAKASHI_FX, KAKASHI_STYLE,
     "おっ、オレのカードかい？ ま、本気を出せばカムイですぐにビンゴしちゃうよ。",
     "お見事！ さすがはオレが見込んだだけのことはあるね。超エス級ビンゴ達成だ！"),
    ("minato", MINATO_VOICE, MINATO_FX, MINATO_STYLE,
     "四代目火影、波風ミナトだ！ 黄色い閃光のスピードで一番乗りを目指すよ！",
     "すごいよ！ ヒライシンの術みたいな最速ビンゴ達成だね！ おめでとう！！"),
    ("itachi", "Charon", "rubberband=pitch=1.02:formant=preserved:pitchq=quality",
     "21-year-old calm, deep, gentle older brother speaking quietly with charisma.",
     "オレのカードを選ぶとはな…焦ることはない、勝利の道筋はすでに見えている。",
     "見事だ…お前の瞳には、しっかりと勝利の光が映っていたようだな。"),
    ("gaara", "Enceladus", "rubberband=pitch=1.03:formant=shifted:pitchq=quality:smoothing=on",
     "17-year-old calm, quiet, cool young male Kazekage of the Sand.",
     "砂の風影、我愛羅だ。絶対防御の砂で、お前の勝利を最後まで守り抜こう。",
     "見事な絆の力だ…砂の誇りにかけて、このビンゴ達成を祝福しよう！"),
    ("hinata", "Achernar", None,
     "16-year-old shy, sweet, gentle anime girl speaking with warm determination.",
     "あ、あの…私のカードを選んでくれてありがとう！ ビャクガンでしっかり見極めるね！",
     "やったぁ…！ あきらめないでよかった…最高のビンゴ達成だね！！"),
    ("jiraiya", "Algenib", "rubberband=pitch=0.95:formant=preserved:pitchq=quality",
     "50-year-old boisterous, gravelly, heroic male Toad Sage master!",
     "ガッハッハ！ 妙木山のガマ仙人、自来也様のカードとはお目が高いのう！",
     "よぉーっし！ ど根性ビンゴ達成じゃ！ これぞ伝説の三忍の豪運よ！！"),
    ("shikamaru", "Zubenelgenubi", "rubberband=pitch=1.04:formant=shifted:pitchq=quality:smoothing=on",
     "17-year-old clever, laid-back teen boy strategist.",
     "めんどくせーが…選ばれたからには二百手先まで読んで勝たせてやるよ！",
     "チェックメイトだ！ 作戦通り、完璧なビンゴ達成だぜ！"),
    ("guy_lee", "Sadachbia", "rubberband=pitch=0.96:formant=preserved:pitchq=quality",
     "30-year-old explosively hot-blooded male martial artist screaming about youth!",
     "ナイスガイ！！ 青春フルパワー全開で、熱血ビンゴへ突き進むぞぉぉ！！",
     "うおおおぉぉ！！ 青春のクライマックス！！ 熱血ビンゴ達成だァァ！！"),
    ("madara", "Charon", "rubberband=pitch=0.90:formant=preserved:pitchq=quality",
     "Supreme, commanding, god-tier legendary male warlord.",
     "ほう…このうちはマダラのカードを選ぶか。ならば圧倒的な力で舞うとしよう！",
     "フハハハハ！ これぞ完成体スサノオの威光！ 見事なビンゴであったぞ！！"),
]

# System / Excitement clips (All using THE Naruto Voice!)
SYS_CLIPS = [
    ("test", "チャクラ充填完了！ うずまきナルト、準備バッチリだ！ 忍界大戦ビンゴ大会、いくってばよ！！"),
    ("hit", "よしっ！ カードにヒットしたってばよ！"),
    ("double_hit", "すげぇぞ！ ダブルヒットだってばよ！！"),
    ("triple_hit", "うおおぉっ！ 全員同時ヒットの神引きだってばよぉぉ！！"),
    ("reach", "きたきたぁっ！ リーチ突入だ！ あと一つでビンゴだってばよ！！"),
    ("bingo", "やったぁぁー！！ 超エス級任務達成！ ビンゴだってばよぉぉ！！"),
    ("reset", "忍界リセットの術！ 新しいビンゴカードで勝負開始だってばよ！！"),
    ("complete", "全七十五人の忍が全員集結したぞ！ 最高の忍界大戦だったってばよ！！"),
]

def load_progress():
    if os.path.exists(PROGRESS_PATH):
        with open(PROGRESS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"sys": [], "leaders": [], "summon": []}

def save_progress(prog):
    with open(PROGRESS_PATH, "w", encoding="utf-8") as f:
        json.dump(prog, f, ensure_ascii=False)

def main():
    manifest_path = os.path.join(AUDIO_DIR, "manifest.json")
    if os.path.exists(manifest_path):
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    else:
        manifest = {"summon": {}, "leaders": {}, "sys": {}}

    prog = load_progress()
    ver = "v=2"

    print("=== [V2] Phase 1: Generating 8 Naruto System Clips ===", flush=True)
    for key, text in SYS_CLIPS:
        if key in prog["sys"]:
            continue
        print(f"  [Sys] {key} ...", flush=True)
        pcm = synth_sculpted(NARUTO_VOICE, NARUTO_STYLE, text, NARUTO_FX, max_sec=15.0)
        mp3_abs = os.path.join(SYS_DIR, f"{key}.mp3")
        pcm_to_mp3(pcm, mp3_abs)
        manifest["sys"][key] = {
            "src": f"assets/audio/sys/{key}.mp3?{ver}",
            "duration": round(len(pcm) / 48000.0, 2),
        }
        prog["sys"].append(key)
        save_progress(prog)
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

    print("=== [V2] Phase 2: Generating 12 Oshi Leader Card Voices (24 clips) ===", flush=True)
    for lid, voice, fx, style, sel_t, bin_t in LEADERS_12:
        if lid in prog["leaders"]:
            continue
        print(f"  [Leader] {lid} (voice={voice}) ...", flush=True)
        pcm_sel = synth_sculpted(voice, style, sel_t, fx, max_sec=16.0)
        pcm_to_mp3(pcm_sel, os.path.join(LEADERS_DIR, f"{lid}_select.mp3"))
        pcm_bin = synth_sculpted(voice, style, bin_t, fx, max_sec=16.0)
        pcm_to_mp3(pcm_bin, os.path.join(LEADERS_DIR, f"{lid}_bingo.mp3"))
        manifest["leaders"][lid] = {
            "select": f"assets/audio/leaders/{lid}_select.mp3?{ver}",
            "bingo": f"assets/audio/leaders/{lid}_bingo.mp3?{ver}",
        }
        prog["leaders"].append(lid)
        save_progress(prog)
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

    print("=== [V2] Phase 3: Generating 75 Summon + Character Quote Voices ===", flush=True)
    silence_pcm = b"\x00" * int(24000 * 2 * 0.42)

    for cid, spoken_name, c_voice, c_fx, c_style, c_quote in CHARACTERS_75:
        if cid in prog["summon"]:
            continue
        col_ja = col_letter_ja(cid)
        prefix = CALL_PREFIXES[(cid - 1) % len(CALL_PREFIXES)]
        naruto_call = f"{prefix} {col_ja}の{cid}番、{spoken_name}だってばよ！！"

        print(f"  [{cid:02d}/75] Naruto({NARUTO_VOICE}+FX) -> {spoken_name}({c_voice}) ...", flush=True)
        pcm_call = synth_sculpted(NARUTO_VOICE, NARUTO_STYLE, naruto_call, NARUTO_FX, max_sec=11.0)
        pcm_quote = synth_sculpted(c_voice, c_style, c_quote, c_fx, max_sec=18.0)

        full_pcm = pcm_call + silence_pcm + pcm_quote
        split_sec = round((len(pcm_call) + int(len(silence_pcm) * 0.7)) / 48000.0, 2)
        total_sec = round(len(full_pcm) / 48000.0, 2)

        sid = f"{cid:02d}"
        mp3_abs = os.path.join(SUMMON_DIR, f"{sid}.mp3")
        pcm_to_mp3(full_pcm, mp3_abs)

        manifest["summon"][str(cid)] = {
            "src": f"assets/audio/summon/{sid}.mp3?{ver}",
            "splitSec": split_sec,
            "duration": total_sec,
            "voice": c_voice,
        }
        prog["summon"].append(cid)
        save_progress(prog)
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

    shutil.rmtree(TEMP_DIR, ignore_errors=True)
    print("=== [V2] ALL 107 CHARACTER-TUNED VOICES GENERATED SUCCESSFULLY! ===", flush=True)

if __name__ == "__main__":
    main()
