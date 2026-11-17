import os
import sys
import io
import wave
import json
import time
import subprocess
import numpy as np
from google import genai
from google.genai import types

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='backslashreplace')

# Load Vertex AI credentials from workspace AgentTools config
ENV_CANDIDATES = [
    r'c:\Users\mattu\Documents\MyProjects\🤖_AgentTools\Scripts\.env',
    r'c:\Users\mattu\Documents\MyProjects\.env',
]
for env_path in ENV_CANDIDATES:
    if os.path.exists(env_path):
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

project_id = (
    os.getenv('CONSTRUCTION_GCP_PROJECT_ID')
    or os.getenv('PERSONAL_AI_PROJECT_ID')
    or os.getenv('VERTEX_AI_PROJECT_ID')
)
cred = (
    os.getenv('CONSTRUCTION_GOOGLE_APPLICATION_CREDENTIALS')
    or os.getenv('PERSONAL_AI_CREDENTIALS')
    or os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
)
for p in [
    r'c:\Users\mattu\Documents\MyProjects\🤖_AgentTools\Scripts\Config\personal_key.json',
    r'c:\Users\mattu\Documents\MyProjects\🤖_AgentTools\Config\personal_key.json',
    r'C:\AgentTools\Config\personal_key.json',
]:
    if (not cred or not os.path.exists(cred)) and os.path.exists(p):
        cred = p
if cred and os.path.exists(cred):
    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = cred

TTS_MODEL = 'gemini-3.8-flash-tts'
client = genai.Client(vertexai=True, project=project_id, location='global')

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
AUDIO_DIR = os.path.join(PROJECT_ROOT, 'assets', 'audio')
SUMMON_DIR = os.path.join(AUDIO_DIR, 'summon')
LEADERS_DIR = os.path.join(AUDIO_DIR, 'leaders')
SYS_DIR = os.path.join(AUDIO_DIR, 'sys')
TEMP_DIR = os.path.join(PROJECT_ROOT, 'scripts', '_temp_wav')

for d in [SUMMON_DIR, LEADERS_DIR, SYS_DIR, TEMP_DIR]:
    os.makedirs(d, exist_ok=True)

LAST_CALL_TS = 0.0
MIN_INTERVAL = 4.2  # ~14 RPM safe rate limit

def wait_rate_limit():
    global LAST_CALL_TS
    elapsed = time.time() - LAST_CALL_TS
    if elapsed < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - elapsed)
    LAST_CALL_TS = time.time()

def extract_pcm(audio_bytes):
    if audio_bytes[:4] == b'RIFF':
        with wave.open(io.BytesIO(audio_bytes), 'rb') as wf:
            pcm = wf.readframes(wf.getnframes())
    else:
        pcm = audio_bytes
    if len(pcm) % 2 != 0:
        pcm = pcm[:-1]
    return pcm

def pcm_to_mp3(pcm_bytes, mp3_path, bitrate='48k'):
    wav_path = os.path.join(TEMP_DIR, 'tmp_conv.wav')
    with wave.open(wav_path, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(24000)
        wf.writeframes(pcm_bytes)
    subprocess.run(
        ['ffmpeg', '-y', '-i', wav_path, '-ar', '24000', '-ac', '1', '-b:a', bitrate, mp3_path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True
    )

def find_inter_speaker_split(pcm_bytes, min_sec=2.3, max_sec=8.5):
    """Find midpoint of the cleanest silence gap between Naruto's call and Character's quote."""
    sr = 24000
    samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    total_sec = len(samples) / sr
    win = int(sr * 0.04)  # 40ms window
    if len(samples) < win * 4:
        return round(total_sec * 0.4, 2), round(total_sec, 2)

    rms = np.array([
        np.sqrt(np.mean(samples[i:i+win] ** 2))
        for i in range(0, len(samples) - win, win)
    ])

    # Search for silent stretches (< 0.012 RMS) overlapping [min_sec, min(max_sec, total_sec - 1.5)]
    hi_bound = min(max_sec, max(min_sec + 1.0, total_sec * 0.68))
    best_gap = None
    cur_start = None
    speech_seen = False

    for idx, val in enumerate(rms):
        t = idx * 0.04
        if val > 0.025:
            speech_seen = True
            if cur_start is not None:
                dur = t - cur_start
                mid = (cur_start + t) / 2.0
                if dur >= 0.18 and min_sec <= mid <= hi_bound:
                    if best_gap is None or dur > best_gap[2]:
                        best_gap = (cur_start, t, dur, mid)
                cur_start = None
        elif speech_seen and val < 0.012:
            if cur_start is None:
                cur_start = t

    if best_gap:
        # Place split slightly toward the end of the silence so Naruto's call finishes cleanly and quote starts right away
        split_pt = round(best_gap[0] + best_gap[2] * 0.65, 2)
        return split_pt, round(total_sec, 2)

    # Fallback: find minimum energy window in [min_sec, hi_bound]
    s_idx = max(0, int(min_sec / 0.04))
    e_idx = min(len(rms), int(hi_bound / 0.04))
    if e_idx > s_idx:
        min_i = s_idx + int(np.argmin(rms[s_idx:e_idx]))
        return round(min_i * 0.04, 2), round(total_sec, 2)
    return round(total_sec * 0.38, 2), round(total_sec, 2)

def synth_single(voice_name, style_en, text_ja, max_expected_sec=20.0):
    prompt = f"""# AUDIO PROFILE: Character
## THE SCENE: High-energy Japanese anime scene!
### DIRECTOR'S NOTES
Style: {style_en} Speak naturally in Japanese anime voice acting style. Do NOT read headers or notes.

#### TRANSCRIPT
{text_ja}"""
    backoff = [8, 18, 35, 60]
    for attempt in range(len(backoff) + 1):
        try:
            wait_rate_limit()
            resp = client.models.generate_content(
                model=TTS_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_modalities=['AUDIO'],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name)
                        )
                    )
                )
            )
            pcm = extract_pcm(resp.candidates[0].content.parts[0].inline_data.data)
            dur = len(pcm) / 48000.0
            if dur > max_expected_sec and attempt < len(backoff):
                print(f"  [Warn] Single clip unexpectedly long ({dur:.1f}s > {max_expected_sec}s), retrying...")
                continue
            return pcm
        except Exception as e:
            if attempt < len(backoff):
                w = backoff[attempt]
                print(f"  [Retry] {e} -> waiting {w}s...")
                time.sleep(w)
            else:
                raise

def synth_multi(char_voice, char_style_en, naruto_line_ja, char_line_ja, max_expected_sec=25.0):
    prompt = f"""# AUDIO PROFILE: Naruto & Shinobi
## THE SCENE: High-energy Japanese shonen anime summon battle!
### DIRECTOR'S NOTES
Style: Authentic Japanese anime dubbing! Do NOT read speaker names, headers, or notes.
Naruto: Energetic, slightly raspy, hot-blooded young boy ninja shouting with excitement!
Shinobi: {char_style_en}

#### TRANSCRIPT
Naruto: {naruto_line_ja}
Shinobi: {char_line_ja}"""
    backoff = [8, 18, 35, 60]
    for attempt in range(len(backoff) + 1):
        try:
            wait_rate_limit()
            resp = client.models.generate_content(
                model=TTS_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_modalities=['AUDIO'],
                    speech_config=types.SpeechConfig(
                        multi_speaker_voice_config=types.MultiSpeakerVoiceConfig(
                            speaker_voice_configs=[
                                types.SpeakerVoiceConfig(
                                    speaker='Naruto',
                                    voice_config=types.VoiceConfig(
                                        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name='Aoede')
                                    )
                                ),
                                types.SpeakerVoiceConfig(
                                    speaker='Shinobi',
                                    voice_config=types.VoiceConfig(
                                        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=char_voice)
                                    )
                                ),
                            ]
                        )
                    )
                )
            )
            pcm = extract_pcm(resp.candidates[0].content.parts[0].inline_data.data)
            dur = len(pcm) / 48000.0
            if dur > max_expected_sec and attempt < len(backoff):
                print(f"  [Warn] Multi clip unexpectedly long ({dur:.1f}s > {max_expected_sec}s), retrying...")
                continue
            return pcm
        except Exception as e:
            if attempt < len(backoff):
                w = backoff[attempt]
                print(f"  [Retry] {e} -> waiting {w}s...")
                time.sleep(w)
            else:
                raise

def col_letter_ja(num_id):
    return ["ビー", "アイ", "エヌ", "ジー", "オー"][(num_id - 1) // 15]

# Excitement prefixes for Naruto's summon call
CALL_PREFIXES = [
    "口寄せ成功！",
    "いくぜっ！",
    "でたぁっ！",
    "よっしゃあ！",
    "チャクラ全開！",
]

# All 75 characters with voice casting, anime acting direction, and clean Japanese TTS scripts
CHARACTERS_75 = [
    # B (1-15)
    (1, "うずまきナルト", "Aoede", "SAME_AOEDE",
     "Passionate, raspy, determined young shonen hero declaring his ninja way with fiery spirit!",
     "仙法、超大玉螺旋多連ガン！ まっすぐ自分の言葉は曲げねェ…それがオレの忍道だってばよ！！"),
    (2, "うちはサスケ", "Orus", "MULTI",
     "Cool, composed, intense young rival ninja with a sharp, quiet, charismatic low voice.",
     "永遠の万華鏡写輪眼！ …オレは過去を断ち切る。お前はオレにとっての新たな光だ！"),
    (3, "春野サクラ", "Kore", "MULTI",
     "Energetic, fierce, determined young kunoichi heroine shouting with power and pride!",
     "百豪の術、桜花衝！ しゃーんなろー！！ やっと二人の背中に追いついた！"),
    (4, "はたけカカシ", "Charon", "MULTI",
     "Cool, laid-back yet deeply charismatic veteran elite ninja speaking with quiet conviction.",
     "万華鏡写輪眼、カムイ！ …仲間を大切にしない奴は、それ以上のクズだ！"),
    (5, "波風ミナト", "Zephyr", "MULTI",
     "Refreshing, gentle yet heroic and lightning-fast young Hokage speaking warmly and bravely.",
     "ヒライシンの術、二の段！ 木ノ葉の黄色い閃光！ ここからは誰にも触れさせないよ！"),
    (6, "自来也、ガマ仙人", "Algenib", "MULTI",
     "Hearty, bold, gravelly legendary sage master laughing with kabuki-like heroic swagger!",
     "仙法、五右衛門、超大玉螺旋丸！ 忍びとは耐え忍ぶ者のことなんだよ…諦めねェど根性だ！"),
    (7, "五代目火影、綱手", "Gacrux", "MULTI",
     "Powerful, commanding, fearless female Hokage leader shouting with fierce authority!",
     "創造再生、百豪の極み！ 火影の称号をナメるなよ！ 命を懸けて里を守る！"),
    (8, "マイト・ガイ", "Puck", "MULTI",
     "Explosively passionate, ultra-hot-blooded martial arts master screaming about youth!",
     "八門遁甲の陣、ヤガイ！ 紅き春の蒸気！ 青春のクライマックスだァァ！！"),
    (9, "ロック・リー", "Puck", "MULTI",
     "Earnest, polite, ultra-passionate young martial artist shouting with pure determination!",
     "八門遁甲、表蓮華、裏蓮華！ 努力の天才だと証明してみせます！ 僕の忍道です！！"),
    (10, "奈良シカマル", "Iapetus", "MULTI",
     "Laid-back, sighing, super-smart young strategist who gets serious for his comrades.",
     "影真似、影首縛りの術！ …めんどくせーが、やるしかねェだろ。仲間のためだ！"),
    (11, "日向ネジ", "Orus", "MULTI",
     "Calm, noble, stoic young prodigy speaking with deep gratitude and sharp focus.",
     "八卦六十四掌、回天！ …ナルト、お前はオレを闇から救い出してくれたんだ。"),
    (12, "日向ヒナタ", "Leda", "MULTI",
     "Gentle, soft-spoken, pure-hearted girl gathering tremendous courage for the one she loves.",
     "白眼、柔歩双獅拳！ 私だって…ナルトくんの隣を歩きたいから！"),
    (13, "サイ", "Zephyr", "MULTI",
     "Soft, calm, polite young artist boy speaking with newfound warmth and sincerity.",
     "超獣偽画、狛犬！ 仲間との繋がり…それが僕に笑顔を教えてくれた。"),
    (14, "ヤマト隊長", "Charon", "MULTI",
     "Dependable, serious, composed ANBU captain speaking with steady resolve.",
     "木遁、樹界降誕！ 九尾のチャクラは、僕が木遁で完全に抑え込む！"),
    (15, "猿飛アスマ", "Algenib", "MULTI",
     "Gruff, warm-hearted, rugged veteran sensei speaking with protective wisdom.",
     "風遁、翠嵐烈風！ 木ノ葉の玉を守り抜く…それが未来を繋ぐ忍の務めだ。"),

    # I (16-30)
    (16, "秋道チョウジ", "Iapetus", "MULTI",
     "Kind-hearted boy getting fired up to protect his best friends with explosive power!",
     "超倍化の術、蝶弾爆撃！ 仲間の悪口を言う奴は絶対に許さない！ カロリー解放！！"),
    (17, "山中イノ", "Kore", "MULTI",
     "Bright, confident, stylish kunoichi speaking with upbeat spirit and leadership!",
     "心転身の術、忍連合通信！ 忍連合軍全員の心を、ひとつに繋ぐわよ！！"),
    (18, "犬塚キバと赤丸", "Puck", "MULTI",
     "Wild, cocky, energetic beast-tamer boy shouting excitedly with feral energy!",
     "ガロウガ、尾追いガツウガ！ いくぜ赤丸！ オレたちも火影を狙うぞ！！"),
    (19, "油女シノ", "Enceladus", "MULTI",
     "Quiet, mysterious, deadpan stoic boy speaking calmly and logically.",
     "秘術、蟲玉…オレのキカイチュウからは誰一人として逃れられない。なぜならだ。"),
    (20, "テンテン", "Kore", "MULTI",
     "Lively, tomboyish weapons master kunoichi speaking with spirited determination!",
     "双昇龍、バショウセン解放！ 六道仙人の宝具だって使いこなしてみせるわよ！"),
    (21, "猿飛木ノ葉丸", "Aoede", "SAME_AOEDE",
     "Cheeky, energetic little brother ninja shouting enthusiastically to rival Naruto!",
     "火遁、灰積焼と螺旋丸！ ナルト兄ちゃん直伝の螺旋丸！ これに決めたコレ！！"),
    (22, "うみのイルカ先生", "Zephyr", "MULTI",
     "Warm, emotional, caring teacher shouting with pride and tears for his beloved student!",
     "木ノ葉隠れ、絆の教え！ ナルトは…オレが認めた最高の生徒だ！！"),
    (23, "シズネとトントン", "Leda", "MULTI",
     "Earnest, brisk, reliable medical kunoichi reporting dutifully!",
     "毒霧、仕込み千本！ 綱手様！ 医療部隊の準備、いつでも万全です！"),
    (24, "五代目風影、我愛羅", "Orus", "MULTI",
     "Calm, quiet, deeply resonant young Kazekage delivering an inspiring speech to all shinobi.",
     "砂瀑大葬、絶対防御！ …ここに敵はいない。我らはすべて、忍だ！！"),
    (25, "カンクロウ", "Iapetus", "MULTI",
     "Confident, tough older brother puppeteer speaking with bold swagger!",
     "黒秘技、機々一発！ 傀儡師の頂点、その真髄を見せてやるぜ！"),
    (26, "テマリ", "Gacrux", "MULTI",
     "Fierce, sassy, commanding wind-user kunoichi sister shouting proudly!",
     "風遁、大カマイタチの術！ 忍連合軍で私の風遁を超える使い手はいないよ！"),
    (27, "キラービー", "Sadachbia", "MULTI",
     "Funky, rhythmic, high-energy anime rapper ninja chanting his lines with musical flow!",
     "ライリ熱刀、ラリアット！ バカヤロー！ コノヤロー！ 八本目の剣で韻を踏むぜ、イェー！！"),
    (28, "四代目雷影、エー", "Fenrir", "MULTI",
     "Booming, hot-tempered, muscular lightning warlord roaring with thunderous power!",
     "雷遁チャクラモード、ライギャク水平！ オレのスピードについて来られる忍など存在せん！！"),
    (29, "三代目土影、オオノキ", "Algenib", "MULTI",
     "Feisty, gravelly, proud elderly Tsuchikage grandpa shouting with stubborn heroism!",
     "塵遁、原界剥離の術！ 己を捨てず、誇りを胸に戦う！ 両天秤のオオノキじゃ！"),
    (30, "五代目水影、照美メイ", "Pulcherrima", "MULTI",
     "Elegant, alluring, mature female Mizukage speaking with graceful yet deadly charm.",
     "溶遁、溶怪の術とフットン！ 霧隠れの水影として、ここで全てを溶かし尽くすわ！"),

    # N (31-45)
    (31, "うちはイタチ", "Charon", "MULTI",
     "Deep, sorrowful, gentle yet awe-inspiring older brother speaking with infinite love.",
     "天照、月読、スサノオ…許せサスケ。お前がこれからどうなろうと、オレはお前をずっと愛している。"),
    (32, "ペイン天道", "Fenrir", "MULTI",
     "Godlike, cold, echoing, solemn baritone commanding the world with overwhelming majesty.",
     "神羅天征、地爆天星！ …痛みを考えろ、痛みを知れ。ここより世界に痛みを！！"),
    (33, "うずまき長門", "Schedar", "MULTI",
     "Weary, quiet, sincere voice entrusting hope and peace to Naruto.",
     "外道、輪廻天生の術…ナルト、お前なら本当に平和を掴み取れるかもしれんな。"),
    (34, "暁の小南", "Despina", "MULTI",
     "Calm, serene, poetic angel kunoichi speaking with quiet unbreakable resolve.",
     "神のシシャの術、六千億枚の起爆札！ 今度こそ…枯れない希望の花になるわ。"),
    (35, "デイダラ", "Puck", "MULTI",
     "Wild, theatrical, manic young bomber artist shouting joyfully about explosive art!",
     "起爆粘土、シーフォー・カルラ！ 芸術は爆発だ！！ 一瞬の煌めきこそが究極の美だ、うん！"),
    (36, "赤砂のサソリ", "Enceladus", "MULTI",
     "Cool, detached, eerie young master puppeteer speaking with quiet arrogance.",
     "赤秘技、百機の操演…芸術とは、永遠に美しく残るものだ。百機を見ろ。"),
    (37, "干柿鬼鮫", "Schedar", "MULTI",
     "Rough, shark-like, fearless swordsman chuckling darkly with warrior honor.",
     "水遁、大コウ弾の術！ イタチさん…どうやら私は、ロクでもない人間でもなかったようですよ。"),
    (38, "暁の飛段", "Puck", "MULTI",
     "Wild, loud, unhinged fanatic villain laughing and shouting recklessly!",
     "呪術、死司ヒョウケツ！ ひゃっはー！ ジャシン様への儀式が始まるぜェ！！"),
    (39, "暁の角都", "Fenrir", "MULTI",
     "Low, menacing, gravelly immortal bounty hunter speaking coldly.",
     "ジオング、五属性複合忍術…地獄の沙汰も金次第だ。お前の心臓をもらうぞ。"),
    (40, "黒ゼツと白ゼツ", "Enceladus", "MULTI",
     "Creepy, sinister, shadowy manipulator whispering from the darkness of history.",
     "カゲロウ、胞子の術…忍の歴史はすべて、この瞬間のためにあったのだ。"),
    (41, "うちはオビト", "Schedar", "MULTI",
     "Deeply emotional fallen hero entrusting his childhood dream to Naruto with raw feeling.",
     "カムイ、六道十尾キュウイン！ …ナルト、お前は必ず、火影になれよ！！"),
    (42, "うちはマダラ", "Fenrir", "MULTI",
     "Supreme, arrogant, god-tier legendary warlord speaking with overwhelming deep authority.",
     "テンガイシンセイ、完成体スサノオ！ …お前も舞うか？ 二つの隕石をどうする、オオノキよ！"),
    (43, "大蛇丸", "Enceladus", "MULTI",
     "Silky, eerie, serpentine, enigmatic villain speaking with soft chilling fascination.",
     "ヤマタの術、口寄せエドテンセイ…すべての忍術の真理を解き明かす。サスケくんの風を見届けよう。"),
    (44, "薬師カブト", "Zephyr", "MULTI",
     "Smug, intellectual, calculating Dragon Sage speaking with eerie polite confidence.",
     "仙法、ハクゲキの術！ 蛇から龍へと昇華した、ボクの仙術を見せてあげるよ！"),
    (45, "うちはシスイ", "Orus", "MULTI",
     "Noble, warm, selfless young Uchiha prodigy entrusting the village to his best friend.",
     "万華鏡写輪眼、コトアマツカミ！ うちはの名と木ノ葉の平和…イタチ、お前に託す！"),

    # G (46-60)
    (46, "初代火影、千手柱間", "Fenrir", "MULTI",
     "Heroic, booming, legendary God of Shinobi speaking with towering resolve!",
     "仙法木遁、真数千手、チョウジョウケブツ！ 里を傷つける者は、たとえ友や我が子であろうと許さん！！"),
    (47, "二代目火影、千手扉間", "Schedar", "MULTI",
     "Stern, sharp, commanding tactician Hokage barking orders on the battlefield!",
     "水遁水断波、互乗起爆札！ ヒライシンも影分身もワシが創った術だ！ いくぞ猿よ！"),
    (48, "三代目火影、猿飛ヒルゼン", "Algenib", "MULTI",
     "Wise, warm, dignified grandfather Hokage speaking with the Will of Fire!",
     "五遁大連弾の術、金剛ニョイ！ 木の葉舞うところに火は燃ゆる…火の影は里を照らす！"),
    (49, "うずまきクシナ", "Kore", "MULTI",
     "Fiery yet overflowing with maternal love, crying warm tears as she hugs her son!",
     "金剛封鎖、赤い血潮のハバネロ！ ナルト…大好きだってばね！！"),
    (50, "九尾、クラマ", "Fenrir", "MULTI",
     "Colossal, ferocious, gravelly nine-tailed fox beast roaring alongside his partner Naruto!",
     "超大玉尾獣玉、九尾チャクラモード！ 行くぞナルト！！ ワシのチャクラを全部持っていきやがれ！！"),
    (51, "一尾、シュカク", "Puck", "MULTI",
     "Wild, cackling, rowdy sand tanuki beast shouting boastfully!",
     "風遁練空弾、砂漠層大葬封印！ ガアラと組めば最強の絶対防御と封印術だぜ！！"),
    (52, "二尾、マタタビ", "Pulcherrima", "MULTI",
     "Dignified, fierce mystical blue-flame cat spirit speaking with polite power.",
     "青炎の火鼠玉！ 蒼き劫火ですべてを焼き尽くします！"),
    (53, "三尾、イソブ", "Leda", "MULTI",
     "Timid yet resilient giant turtle beast speaking gently.",
     "サンゴ掌、大水弾！ 霧隠れの鉄壁、サンゴの盾を突破できるかな？"),
    (54, "四尾、ソンゴクウ", "Algenib", "MULTI",
     "Proud, booming Great Sage Ape King roaring with respect for Naruto!",
     "仙法、熔遁螺旋手裏剣！ 水簾洞の美猴王！ ナルトよ、オレの力を貸してやる！！"),
    (55, "五尾、コクオウ", "Schedar", "MULTI",
     "Noble, polite, serene white steed beast speaking with formal dignity.",
     "フットン、怪力無双！ 蒸気チャクラを沸点まで高め、一撃で粉砕いたします！"),
    (56, "六尾、サイケン", "Leda", "MULTI",
     "Cute, cheerful, polite slug beast speaking with energetic charm!",
     "水遁、泡沫の術！ シャボン玉の舞いとともに、すべてを溶かすであります！"),
    (57, "七尾、チョウメイ", "Puck", "MULTI",
     "Upbeat, cheerful, lucky-seven beetle beast shouting happily!",
     "秘伝、リンプン隠れの術！ ラッキーセブン重明だ！ 空を駆け抜けて友達百人作るっス！！"),
    (58, "八尾、ギュウキ", "Fenrir", "MULTI",
     "Rough, dependable giant ox-octopus beast roaring encouragement to Bee and Naruto!",
     "尾獣ハチマキ、連続尾獣玉！ ビー！ ナルト！ お前ら二人のコンビネーションで決めるぞ！！"),
    (59, "外道魔像、十尾", "Fenrir", "MULTI",
     "Ancient, earth-shaking primordial monstrosity rumbling ominously.",
     "天変地異、神樹降臨…すべてのチャクラの根源が今、大地を揺るがす…！！"),
    (60, "ガマブン太とガマ吉", "Algenib", "MULTI",
     "Tough, yakuza-boss giant toad chief shouting boldly with his son!",
     "火遁、ガマユ炎弾！ 親分ガマブン太とガマ吉の親子連携、見せてやるぜ！！"),

    # O (61-75)
    (61, "六道仙人モード、うずまきナルト", "Aoede", "SAME_AOEDE",
     "God-tier Six Paths Naruto shouting his ultimate attack with blazing heroic passion!",
     "六道、超大玉螺旋手裏剣！ 仲間の想いを全部乗せた、オレの最強の螺旋手裏剣だってばよ！！"),
    (62, "輪廻写輪眼、うちはサスケ", "Orus", "MULTI",
     "Supreme Six Paths Sasuke speaking with razor-sharp thunderous intensity!",
     "インドラの矢、アメノテヂカラ！ 全尾獣のチャクラをスサノオに集束させた、最強の一矢だ！！"),
    (63, "威装・スサノオ", "Fenrir", "MULTI",
     "Epic, legendary battle narrator roaring the ultimate fusion of Naruto and Sasuke!",
     "九尾と完成体スサノオ合体！ ナルトとサスケ、二人の力が重なった究極の鎧だ！！"),
    (64, "風遁・螺旋手裏剣", "Zephyr", "MULTI",
     "Excited, awe-struck elite ninja marveling at the ultimate S-rank wind technique!",
     "超高密度チャクラの刃！ 四代目火影すら到達できなかった、形態変化と性質変化の融合だ！！"),
    (65, "雷切・千鳥・キリン", "Orus", "MULTI",
     "Fierce lightning master calling down thunder from the heavens!",
     "千鳥流し、雷遁キリン！ 雷鳴とともに敵を貫く！ 消えろ、キリンとともに！！"),
    (66, "六道仙人、大筒木ハゴロモ", "Schedar", "MULTI",
     "Ancient, transcendent, wise Sage of Six Paths speaking with sacred calm.",
     "万物創造、六道地爆天星…忍宗の絆、ナルトとサスケよ、お前たちに未来を託すぞ。"),
    (67, "大筒木カグヤ", "Despina", "MULTI",
     "Icy, divine, otherworldly Rabbit Goddess speaking with regal archaic majesty.",
     "アメノミナカ、膨張グドウダマ…この空間もすべてのチャクラも、わらわ一人のものぞ…！"),
    (68, "両目万華鏡、はたけカカシ", "Charon", "MULTI",
     "Heroic sensei powered by his best friend's spirit, shouting fiercely to protect Team 7!",
     "カムイ雷切、完成体スサノオ！ オビトのプレゼントだ…第七班、教え子たちを舐めるなよ！！"),
    (69, "新三竦み、第七班集結", "Kore", "MULTI",
     "Triumphant, exhilarated Team 7 battle cry as Naruto, Sasuke, and Sakura reunite!",
     "ガマ吉、アオダ、カツユ同時口寄せ！ 第七班、ここに完全復活！！ いくぞサスケ、サクラ！！"),
    (70, "ダルイとミフネ", "Charon", "MULTI",
     "Cool, composed Cloud general and honorable Samurai commander striking in unison!",
     "嵐遁レーザーサーカスと居合斬り！ 黒い雷と侍の信念で、エドテンセイを斬り伏せる！！"),
    (71, "チヨバアとサクラ", "Despina", "MULTI",
     "Warm, battle-hardened elderly puppet master grandmother smiling as she entrusts the future.",
     "白秘技、チカマツ十人衆！ 次の世代はきっと昔のワシらとは違う…未来に託すぞい！"),
    (72, "桃地ザブザとハク", "Charon", "MULTI",
     "Fierce yet deeply moved Demon of the Hidden Mist remembering young Naruto's bond.",
     "魔鏡氷晶、霧隠れの術…ナルトよ、お前はあの日からずっと変わらぬまま成長したな。"),
    (73, "忍連合軍の術", "Puck", "MULTI",
     "Passionate united war cry of all five great ninja nations charging together!",
     "五大国全忍、大同団結！ 無限月読を打ち破るのは、オレたち全員の忍連合の術だ！！"),
    (74, "一楽のラーメン", "Aoede", "SAME_AOEDE",
     "Super happy, drooling, overjoyed shonen boy Naruto celebrating his favorite ramen!",
     "特製チャーシュー大盛り！ 任務帰りの一杯！ チャクラ全回復の最強グルメだってばよ！！"),
    (75, "終末の谷・和解の印", "Aoede", "SAME_AOEDE",
     "Emotional, exhausted yet smiling Naruto speaking from the bottom of his heart to his best friend Sasuke!",
     "ナルトとサスケ、魂の決着！ サスケ…お前が痛ェとオレも痛ェんだ…帰ろうぜ、木ノ葉へ！！"),
]

# 12 Selectable Oshi Character Cards (select line + bingo victory line)
LEADERS_12 = [
    ("naruto", "Aoede", "Energetic, raspy shonen anime hero boy shouting happily!",
     "オレのカードを選んだな！ まっすぐ自分の言葉は曲げねェ！ 絶対ビンゴするってばよ！！",
     "やったー！！ 超S級任務達成！ オレたちの最強ビンゴだってばよぉぉ！！"),
    ("sasuke", "Orus", "Cool, sharp, confident young Uchiha prodigy.",
     "フン…オレのカードを選んだか。見せてやる…うちはの本当の力を！",
     "当然の結果だ。万華鏡写輪眼の前に死角はない…見事なビンゴだな！"),
    ("sakura", "Kore", "Bright, fierce, punchy kunoichi heroine!",
     "私のカードね！ 百豪のチャクラ全開でいくわよ！ しゃーんなろー！！",
     "やったわー！！ しゃーんなろー！！ 百豪ビンゴ、完全達成よ！！"),
    ("kakashi", "Charon", "Laid-back, cool, charismatic silver-haired elite sensei.",
     "おっ、オレのカードかい？ ま、本気を出せば神威ですぐにビンゴしちゃうよ。",
     "お見事！ さすがはオレが見込んだだけのことはあるね。超S級ビンゴ達成だ！"),
    ("minato", "Zephyr", "Warm, heroic, lightning-fast Fourth Hokage.",
     "四代目火影、波風ミナトだ！ 黄色い閃光のスピードで一番乗りを目指すよ！",
     "すごいよ！ ヒライシンの術みたいな最速ビンゴ達成だね！ おめでとう！！"),
    ("itachi", "Charon", "Calm, deep, gentle yet mysterious older brother.",
     "オレのカードを選ぶとはな…焦ることはない、勝利の道筋はすでに見えている。",
     "見事だ…お前の瞳には、しっかりと勝利の光が映っていたようだな。"),
    ("gaara", "Orus", "Calm, solemn, noble young Kazekage of the Sand.",
     "砂の風影、我愛羅だ。絶対防御の砂で、お前の勝利を最後まで守り抜こう。",
     "見事な絆の力だ…砂の誇りにかけて、このビンゴ達成を祝福しよう！"),
    ("hinata", "Leda", "Gentle, sweet girl speaking with warm determination.",
     "あ、あの…私のカードを選んでくれてありがとう！ 白眼でしっかり見極めるね！",
     "やったぁ…！ あきらめないでよかった…最高のビンゴ達成だね！！"),
    ("jiraiya", "Algenib", "Boisterous, hearty, heroic Toad Sage master!",
     "ガッハッハ！ 妙木山のガマ仙人、自来也様のカードとはお目が高いのう！",
     "よぉーっし！ ど根性ビンゴ達成じゃ！ これぞ伝説の三忍の豪運よ！！"),
    ("shikamaru", "Iapetus", "Clever, laid-back strategist cracking a confident grin.",
     "めんどくせーが…選ばれたからには200手先まで読んで勝たせてやるよ！",
     "チェックメイトだ！ 作戦通り、完璧なビンゴ達成だぜ！"),
    ("guy_lee", "Puck", "Explosively hot-blooded martial artist screaming about youth!",
     "ナイスガイ！！ 青春フルパワー全開で、熱血ビンゴへ突き進むぞぉぉ！！",
     "うおおおぉぉ！！ 青春のクライマックス！！ 熱血ビンゴ達成だァァ！！"),
    ("madara", "Fenrir", "Commanding, supreme legendary warlord speaking with awe.",
     "ほう…このうちはマダラのカードを選ぶか。ならば圧倒的な力で舞うとしよう！",
     "フハハハハ！ これぞ完成体スサノオの威光！ 見事なビンゴであったぞ！！"),
]

# System / Excitement clips (Naruto announcer = Aoede)
SYS_CLIPS = [
    ("test", "Aoede", "Energetic, raspy shonen anime boy shouting cheerfully!",
     "チャクラ充填完了！ うずまきナルト、準備バッチリだ！ 忍界大戦ビンゴ大会、いくってばよ！！"),
    ("hit", "Aoede", "Excited shonen anime boy cheering!",
     "よしっ！ カードにヒットしたってばよ！"),
    ("double_hit", "Aoede", "Super excited shonen anime boy cheering!",
     "すげぇぞ！ ダブルヒットだってばよ！！"),
    ("triple_hit", "Aoede", "Explosively hyped shonen anime boy cheering!",
     "うおおぉっ！ 全員同時ヒットの神引きだってばよぉぉ！！"),
    ("reach", "Aoede", "Thrilled, tense shonen anime boy shouting!",
     "きたきたぁっ！ リーチ突入だ！ あと一つでビンゴだってばよ！！"),
    ("bingo", "Aoede", "Ecstatic, triumphant shonen anime boy screaming with joy!",
     "やったぁぁー！！ 超S級任務達成！ ビンゴだってばよぉぉ！！"),
    ("reset", "Aoede", "Energetic shonen anime boy starting a new match!",
     "忍界リセットの術！ 新しいビンゴカードで勝負開始だってばよ！！"),
    ("complete", "Aoede", "Moved, triumphant shonen anime boy celebrating full completion!",
     "全75人の忍が全員集結したぞ！ 最高の忍界大戦だったってばよ！！"),
]

def main():
    manifest_path = os.path.join(AUDIO_DIR, 'manifest.json')
    if os.path.exists(manifest_path):
        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest = json.load(f)
    else:
        manifest = {"summon": {}, "leaders": {}, "sys": {}}

    # 1. Generate System Clips (8)
    print("=== Phase 1: Generating System Voice Clips (8) ===")
    for key, voice, style, text in SYS_CLIPS:
        mp3_rel = f"assets/audio/sys/{key}.mp3"
        mp3_abs = os.path.join(SYS_DIR, f"{key}.mp3")
        if os.path.exists(mp3_abs) and os.path.getsize(mp3_abs) > 1000 and key in manifest["sys"]:
            print(f"[Skip] sys/{key}.mp3 already exists.")
            continue
        print(f"[Synth] sys/{key}.mp3 ...")
        pcm = synth_single(voice, style, text, max_expected_sec=16.0)
        pcm_to_mp3(pcm, mp3_abs)
        manifest["sys"][key] = {"src": mp3_rel, "duration": round(len(pcm) / 48000.0, 2)}
        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

    # 2. Generate 12 Oshi Leader Clips (select + bingo)
    print("=== Phase 2: Generating 12 Oshi Leader Voices ===")
    for lid, voice, style, select_text, bingo_text in LEADERS_12:
        sel_abs = os.path.join(LEADERS_DIR, f"{lid}_select.mp3")
        bin_abs = os.path.join(LEADERS_DIR, f"{lid}_bingo.mp3")
        if (
            os.path.exists(sel_abs) and os.path.getsize(sel_abs) > 1000
            and os.path.exists(bin_abs) and os.path.getsize(bin_abs) > 1000
            and lid in manifest["leaders"]
        ):
            print(f"[Skip] leader {lid} already exists.")
            continue
        print(f"[Synth] leader {lid} ({voice}) ...")
        pcm_sel = synth_single(voice, style, select_text, max_expected_sec=16.0)
        pcm_to_mp3(pcm_sel, sel_abs)
        pcm_bin = synth_single(voice, style, bingo_text, max_expected_sec=16.0)
        pcm_to_mp3(pcm_bin, bin_abs)
        manifest["leaders"][lid] = {
            "select": f"assets/audio/leaders/{lid}_select.mp3",
            "bingo": f"assets/audio/leaders/{lid}_bingo.mp3",
        }
        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

    # 3. Generate 75 Character Summon + Dialogue Clips
    print("=== Phase 3: Generating 75 Character Summon + Quote Voices ===")
    for num_id, spoken_name, voice, mode, style, quote_line in CHARACTERS_75:
        sid = f"{num_id:02d}"
        mp3_rel = f"assets/audio/summon/{sid}.mp3"
        mp3_abs = os.path.join(SUMMON_DIR, f"{sid}.mp3")
        if os.path.exists(mp3_abs) and os.path.getsize(mp3_abs) > 2000 and str(num_id) in manifest["summon"]:
            print(f"[Skip] summon/{sid}.mp3 already exists.")
            continue

        col_ja = col_letter_ja(num_id)
        prefix = CALL_PREFIXES[(num_id - 1) % len(CALL_PREFIXES)]
        naruto_call = f"{prefix} {col_ja}の{num_id}番、{spoken_name}だってばよ！！"

        print(f"[Synth {num_id}/75] {spoken_name} (voice={voice}, mode={mode}) ...")
        if mode == "SAME_AOEDE":
            # Synthesize Naruto announcer call + 0.55s pure silence + character quote separately for 100% clean split
            pcm_call = synth_single(
                "Aoede",
                "Energetic, raspy, hot-blooded young boy ninja shouting the bingo summon!",
                naruto_call,
                max_expected_sec=14.0
            )
            silence_pcm = b'\x00' * int(24000 * 2 * 0.55)
            pcm_quote = synth_single(voice, style, quote_line, max_expected_sec=18.0)
            full_pcm = pcm_call + silence_pcm + pcm_quote
            split_sec = round((len(pcm_call) + int(len(silence_pcm) * 0.7)) / 48000.0, 2)
            total_sec = round(len(full_pcm) / 48000.0, 2)
        else:
            try:
                full_pcm = synth_multi(voice, style, naruto_call, quote_line, max_expected_sec=25.0)
            except Exception as err:
                print(f"  [Fallback Voice] {voice} failed ({err}), falling back to Charon/Kore")
                fb = "Kore" if voice in ("Pulcherrima", "Gacrux", "Despina", "Leda") else "Charon"
                full_pcm = synth_multi(fb, style, naruto_call, quote_line, max_expected_sec=25.0)
            split_sec, total_sec = find_inter_speaker_split(full_pcm)

        pcm_to_mp3(full_pcm, mp3_abs, bitrate='48k')
        manifest["summon"][str(num_id)] = {
            "src": mp3_rel,
            "splitSec": split_sec,
            "duration": total_sec,
            "voice": voice
        }
        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        print(f"  -> Saved {mp3_rel} (split={split_sec}s, total={total_sec}s)")

    print("=== ALL AUDIO SYNTHESIS COMPLETED SUCCESSFULLY! ===")

if __name__ == '__main__':
    main()
