import os
import numpy as np
from PIL import Image

BRAIN_DIR = r"C:\Users\mattu\.gemini\antigravity\brain\a6b5592b-5506-4288-9b70-7f6e4fcaf31e"
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CARDS_DIR = os.path.join(PROJECT_ROOT, "assets", "cards")
ICONS_DIR = os.path.join(PROJECT_ROOT, "assets", "icons")
os.makedirs(CARDS_DIR, exist_ok=True)
os.makedirs(ICONS_DIR, exist_ok=True)

SHEETS = [
    ("anime_shinobi_3x3_grid_1794871020210.jpg", [f"char_{i:02d}" for i in range(1, 10)]),
    ("ninja_characters_3x3_grid_1794871186081.jpg", [f"char_{i:02d}" for i in range(10, 19)]),
    ("shonen_ninja_3x3_grid_1794871189368.jpg", [f"char_{i:02d}" for i in range(19, 28)]),
    ("anime_ninja_3x3_grid_1794871191047.jpg", [f"char_{i:02d}" for i in range(28, 37)]),
    ("anime_villains_3x3_grid_1794871194337.jpg", [f"char_{i:02d}" for i in range(37, 46)]),
    ("shonen_hokage_bijuu_3x3_grid_1794871264535.jpg", [f"char_{i:02d}" for i in range(46, 55)]),
    ("naruto_beasts_heroes_3x3_grid_1794871263524.jpg", [f"char_{i:02d}" for i in range(55, 64)]),
    ("anime_ninja_3x3_grid_1794871270869.jpg", [f"char_{i:02d}" for i in range(64, 73)]),
    ("ninja_shonen_3x3_grid_1794871264953.jpg", [
        "char_73", "char_74", "char_75",
        "free", "app_icon", "seal_naruto",
        "seal_sasuke", "seal_sakura", "seal_kakashi"
    ]),
]

# Leader ID -> source char index (1-75)
LEADER_CHAR_MAP = {
    "naruto": 1,
    "sasuke": 2,
    "sakura": 3,
    "kakashi": 4,
    "minato": 5,
    "itachi": 31,
    "gaara": 24,
    "hinata": 12,
    "jiraiya": 6,
    "shikamaru": 10,
    "guy_lee": 8,
    "madara": 42,
}

def find_dividers(img_arr):
    """Find exact x1, x2 and y1, y2 black divider centers near 1/3 and 2/3 of image size."""
    h, w, _ = img_arr.shape
    gray = img_arr.mean(axis=2)

    def best_line(profile, approx):
        lo = max(0, int(approx - len(profile) * 0.04))
        hi = min(len(profile), int(approx + len(profile) * 0.04))
        return lo + int(np.argmin(profile[lo:hi]))

    col_prof = gray.mean(axis=0)
    row_prof = gray.mean(axis=1)

    x1 = best_line(col_prof, w / 3.0)
    x2 = best_line(col_prof, 2.0 * w / 3.0)
    y1 = best_line(row_prof, h / 3.0)
    y2 = best_line(row_prof, 2.0 * h / 3.0)
    return [0, x1, x2, w], [0, y1, y2, h]

def main():
    raw_crops = {}
    for filename, names in SHEETS:
        src_path = os.path.join(BRAIN_DIR, filename)
        img = Image.open(src_path).convert("RGB")
        arr = np.array(img)
        xs, ys = find_dividers(arr)
        pad = max(6, int(img.width * 0.008))  # Trim black divider & outer edge cleanly

        idx = 0
        for r in range(3):
            for c in range(3):
                name = names[idx]
                idx += 1
                left = xs[c] + (pad if c > 0 else pad // 2)
                right = xs[c + 1] - (pad if c < 2 else pad // 2)
                top = ys[r] + (pad if r > 0 else pad // 2)
                bottom = ys[r + 1] - (pad if r < 2 else pad // 2)
                cell_img = img.crop((left, top, right, bottom))
                raw_crops[name] = cell_img

                if name == "app_icon":
                    cell_img.resize((512, 512), Image.Resampling.LANCZOS).save(
                        os.path.join(ICONS_DIR, "icon-512.png"), "PNG", optimize=True
                    )
                    cell_img.resize((192, 192), Image.Resampling.LANCZOS).save(
                        os.path.join(ICONS_DIR, "icon-192.png"), "PNG", optimize=True
                    )
                    cell_img.resize((180, 180), Image.Resampling.LANCZOS).save(
                        os.path.join(ICONS_DIR, "apple-touch-icon.png"), "PNG", optimize=True
                    )
                else:
                    out_webp = os.path.join(CARDS_DIR, f"{name}.webp")
                    cell_img.resize((300, 300), Image.Resampling.LANCZOS).save(
                        out_webp, "WEBP", quality=85, method=6
                    )

    # Save higher-res 440x440 leader portraits for Oshi selector & BINGO cut-in
    for lid, cid in LEADER_CHAR_MAP.items():
        key = f"char_{cid:02d}"
        if key in raw_crops:
            out_leader = os.path.join(CARDS_DIR, f"leader_{lid}.webp")
            raw_crops[key].resize((440, 440), Image.Resampling.LANCZOS).save(
                out_leader, "WEBP", quality=88, method=6
            )

    print(f"Successfully sliced {len(raw_crops)} panels + {len(LEADER_CHAR_MAP)} high-res leader portraits + 3 PWA icons!")

if __name__ == "__main__":
    main()
