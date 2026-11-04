"""harness-evolve：让 pi 修改 harness，只保留在验证集上显著变好的修改。

在被优化的项目根目录运行：python evolve.py
中途停止后再次运行，会从上次的进度继续。
"""
import fnmatch
import json
import math
import subprocess
import sys
from pathlib import Path

# ---------- 配置 ----------
HARNESS = ["agent/prompts/*.md", "agent/tools.py"]  # 允许 proposer 修改的文件（glob）
# 评测命令：输出 {out}/results.jsonl（每行 {"qid", "correct": 0/1, "tokens", "steps"}）和 {out}/traces/（每题一个轨迹文件，文件名包含题号）
EVAL = "python eval/run.py --split {split} --out {out}"
EVAL_QIDS = " --qids {qids}"  # 只运行部分题时追加，qids 为逗号分隔的题号
PROPOSER = ["pi", "--mode", "json", "--no-session", "--model", "claude-opus-4-6",
            "--tools", "read,grep,find,ls,edit,write", "-p"]  # 最后追加 prompt
ALPHA = 0.05        # 显著性水平
MAX_ATTEMPTS = 15   # 最多尝试次数
PATIENCE = 3        # 连续这么多次没有通过，停止
# --------------------------

RUNS = Path("runs")
HISTORY = RUNS / "history.jsonl"
PROMPT = Path(__file__).with_name("proposer.md")


def git(*args):
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def evaluate(split, out, qids=None):
    cmd = EVAL.format(split=split, out=out) + (EVAL_QIDS.format(qids=",".join(qids)) if qids else "")
    subprocess.run(cmd, shell=True, check=True)
    return load(out)


def load(out):
    with open(Path(out) / "results.jsonl", encoding="utf-8") as f:
        return {r["qid"]: r for r in map(json.loads, filter(str.strip, f))}


def mean(rows, key):
    vals = [r[key] for r in rows if key in r]
    return round(sum(vals) / len(vals), 1) if vals else None


def mcnemar_p(fixed, broken):
    """单侧精确 McNemar 检验：假如修改无效，至少 fixed 道题变对的概率。"""
    n = fixed + broken
    return sum(math.comb(n, i) for i in range(fixed, n + 1)) / 2 ** n if n else 1.0


def attempt(current, new):
    d = RUNS / new
    d.mkdir(parents=True, exist_ok=True)

    # 1. proposer 修改 harness
    prompt = PROMPT.read_text(encoding="utf-8")
    for k, v in {"{current}": current, "{new}": new, "{harness}": ", ".join(HARNESS)}.items():
        prompt = prompt.replace(k, v)
    with open(d / "proposer_trace.jsonl", "w", encoding="utf-8") as f:
        subprocess.run(PROPOSER + [prompt], stdout=f, check=True)
    (d / "change.diff").write_text(git("diff"), encoding="utf-8")

    def reject(reason):
        git("restore", ".")
        git("clean", "-fdq")  # 删除新建的文件（runs/ 被 .gitignore 忽略，不受影响）
        return {"result": "rejected", "reason": reason}

    status = git("status", "--porcelain").splitlines()
    if not status or not all(s[:2] == " M" and any(fnmatch.fnmatch(s[3:], p) for p in HARNESS) for s in status):
        return reject("没有修改，或者改动了 harness 文件以外的文件")
    try:
        proposal = json.loads((d / "proposal.json").read_text(encoding="utf-8"))
        targets = [str(q) for q in proposal["targets"]]
    except (OSError, ValueError, KeyError, TypeError):
        return reject("proposal.json 缺失或格式不对")
    entry = {"problem": proposal.get("problem"), "change": proposal.get("change")}

    # 2. 训练集检查：targets 中至少一道错题变对
    before = load(RUNS / current / "eval_train")
    after = evaluate("train", d / "eval_train_targets", targets)
    fixed = sum(1 for q in targets if before.get(q, {}).get("correct") == 0 and after.get(q, {}).get("correct") == 1)
    if fixed == 0:
        return entry | reject("训练集检查未通过：targets 中没有一道题变对")

    # 3. 验证集检查：正确率显著高于当前版本
    before = load(RUNS / current / "eval_val")
    after = evaluate("val", d / "eval_val")
    missing = before.keys() - after.keys()
    if missing:
        sys.exit(f"{new} 的验证集结果缺少 {len(missing)} 道题")
    fixed = sum(1 for q in before if before[q]["correct"] == 0 and after[q]["correct"] == 1)
    broken = sum(1 for q in before if before[q]["correct"] == 1 and after[q]["correct"] == 0)
    p = mcnemar_p(fixed, broken)
    check = {"p_value": float(f"{p:.3g}"), "fixed": fixed, "broken": broken}
    for name, rows in (("before", before), ("after", after)):
        rows = [rows[q] for q in before]
        check[name] = {"acc": round(sum(r["correct"] for r in rows) / len(rows), 4),
                       "tokens": mean(rows, "tokens"), "steps": mean(rows, "steps")}
    (d / "check_val.json").write_text(json.dumps(check, indent=2), encoding="utf-8")
    if p >= ALPHA:
        return entry | reject("验证集检查未通过：正确率没有显著提高")

    # 4. 保留：在整个训练集上运行，供下一次分析
    evaluate("train", d / "eval_train")
    git("commit", "-qam", new)
    git("tag", new)
    return entry | {"result": "kept"}


def main():
    if subprocess.run(["git", "check-ignore", "-q", "runs/"]).returncode != 0:
        sys.exit("请先把 runs/ 加入 .gitignore")
    if git("status", "--porcelain"):
        sys.exit("工作区有未提交的改动，请先处理")
    if not git("tag", "-l", "v0"):
        git("tag", "v0")
    for split in ("train", "val"):
        if not (RUNS / "v0" / f"eval_{split}" / "results.jsonl").exists():
            evaluate(split, RUNS / "v0" / f"eval_{split}")

    history = [json.loads(l) for l in HISTORY.read_text(encoding="utf-8").splitlines()] if HISTORY.exists() else []
    current = git("describe", "--tags", "--abbrev=0").strip()
    fails = 0
    for h in reversed(history):
        if h["result"] == "kept":
            break
        fails += 1

    while len(history) < MAX_ATTEMPTS and fails < PATIENCE:
        new = f"v{len(history) + 1}"
        entry = {"version": new, "base": current} | attempt(current, new)
        history.append(entry)
        with open(HISTORY, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        print(json.dumps(entry, ensure_ascii=False))
        if entry["result"] == "kept":
            current, fails = new, 0
        else:
            fails += 1

    print(f"停止。当前版本：{current}。在测试集上比较 {current} 和 v0 的工作由人完成。")


if __name__ == "__main__":
    main()
