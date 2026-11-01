"""harness-evolve 的两项检查。agent 只调用，不修改。

results.jsonl 每行一道题：{"qid": "...", "correct": 0 或 1}

  python eval/check.py check-train <当前版本 eval_train/results.jsonl> <本次版本 eval_train_targets/results.jsonl> --out check_train.json
  python eval/check.py check-val   <当前版本 eval_val/results.jsonl>   <本次版本 eval_val/results.jsonl> --alpha 0.05 --out check_val.json
"""
import argparse
import json
import math
import sys


def load(path):
    with open(path, encoding="utf-8") as f:
        return {r["qid"]: int(r["correct"]) for r in map(json.loads, filter(str.strip, f))}


def diff(old, new):
    """在两边都有结果的题上，统计变对（原来错、现在对）和变错（原来对、现在错）的题数。"""
    common = old.keys() & new.keys()
    fixed = sum(1 for q in common if old[q] == 0 and new[q] == 1)
    broken = sum(1 for q in common if old[q] == 1 and new[q] == 0)
    return fixed, broken


def mcnemar_p(fixed, broken):
    """单侧精确 McNemar 检验。H0：新旧版本正确率相同；H1：新版本更高。"""
    n = fixed + broken
    return sum(math.comb(n, i) for i in range(fixed, n + 1)) / 2 ** n if n else 1.0


def write(result, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(json.dumps(result, indent=2))


def check_train(old_path, new_path, out):
    # 这些题在当前版本上都是错题，至少变对一道才通过
    fixed, _ = diff(load(old_path), load(new_path))
    write({"pass": fixed > 0, "fixed": fixed}, out)


def check_val(old_path, new_path, alpha, out):
    old, new = load(old_path), load(new_path)
    missing = old.keys() - new.keys()
    if missing:
        sys.exit(f"本次版本缺少 {len(missing)} 道题的结果，例如 {sorted(missing)[:5]}")
    fixed, broken = diff(old, new)
    p = mcnemar_p(fixed, broken)
    write({
        "pass": p < alpha,
        "p_value": round(p, 4),
        "acc_before": round(sum(old.values()) / len(old), 4),
        "acc_after": round(sum(new[q] for q in old) / len(old), 4),
        "fixed": fixed,
        "broken": broken,
    }, out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("check-train")
    v = sub.add_parser("check-val")
    for p in (t, v):
        p.add_argument("old")
        p.add_argument("new")
        p.add_argument("--out", required=True)
    v.add_argument("--alpha", type=float, default=0.05)
    a = ap.parse_args()
    if a.cmd == "check-train":
        check_train(a.old, a.new, a.out)
    else:
        check_val(a.old, a.new, a.alpha, a.out)
