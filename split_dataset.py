import os
import random
import shutil
from pathlib import Path

random.seed(42)

SOURCE = Path("/Users/tanishqjadhav/Desktop/Images")
DEST = Path("dataset")

all_ok = []
all_defected = []

for root, dirs, files in os.walk(SOURCE):

    if "NoDefects" in root:
        for f in files:
            if f.lower().endswith((".jpg", ".jpeg", ".png", ".bmp")):
                all_ok.append(os.path.join(root, f))

    elif "Defects" in root:
        for f in files:
            if f.lower().endswith((".jpg", ".jpeg", ".png", ".bmp")):
                all_defected.append(os.path.join(root, f))

random.shuffle(all_ok)
random.shuffle(all_defected)

def split_files(files):
    n = len(files)

    train = files[:int(0.70*n)]
    val   = files[int(0.70*n):int(0.85*n)]
    test  = files[int(0.85*n):]

    return train, val, test

ok_train, ok_val, ok_test = split_files(all_ok)
def_train, def_val, def_test = split_files(all_defected)

splits = [
    ("train", "ok_wire", ok_train),
    ("val", "ok_wire", ok_val),
    ("test", "ok_wire", ok_test),

    ("train", "defected", def_train),
    ("val", "defected", def_val),
    ("test", "defected", def_test),
]

for split, cls, files in splits:

    target = DEST / split / cls
    target.mkdir(parents=True, exist_ok=True)

    for file in files:
        shutil.copy2(file, target)

print("Done!")
print(f"OK images: {len(all_ok)}")
print(f"Defected images: {len(all_defected)}")
