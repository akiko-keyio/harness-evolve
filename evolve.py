"""harness-evolve：让 proposer 修改 harness，只保留在训练集和验证集上都显著变好的修改。

在项目根目录运行，配置读取 evolve.json（见 SPEC.md）：
  python <harness-evolve 目录>/evolve.py
中途停止后再次运行，已完成的步骤不会重做。创建 runs/stop 文件，会在当前提交完成后停下。
"""
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path
from statistics import NormalDist

try:
    import fcntl
except ImportError:  # Windows 上没有 fcntl，不加锁
    fcntl = None

DEFAULTS = {
    "harness": "harness",  # 初始 harness 文件夹
    "train": None,         # 训练集题号文件，每行一个题号，必填
    "val": None,           # 验证集题号文件，每行一个题号，必填
    "eval": None,          # 评测命令，必填
    "check": None,         # 候选检查命令，可选
    "task": None,          # 追加给 proposer 的任务说明文件，可选
    "eval_files": [],      # 其他影响评测结果的文件，例如评测脚本、模型配置
    "proposer": [          # proposer 命令：在容器中运行 pi（镜像见 Dockerfile.pi），最后追加 prompt
        "docker", "run", "--rm", "--user", "{user}", "-e", "HOME=/tmp", "-e", "ANTHROPIC_API_KEY",
        "-v", "{runs}/history.jsonl:/workspace/runs/history.jsonl:ro",
        "-v", "{runs}/candidates:/workspace/runs/candidates:ro",
        "-v", "{runs}/candidates/{new}:/workspace/runs/candidates/{new}",
        "-v", "{runs}/train:/workspace/runs/train:ro",
        "pi-sandbox", "--mode", "json", "--no-session", "--model", "claude-opus-4-6", "-p",
    ],
    "screen_runs": 3,      # S：筛选题目时，v0.0 在全部题目上评测几次
    "repeats": 3,          # R：每个版本在保留的题目上评测几次
    "alpha": 0.2,          # 检查的显著性水平
    "max_rounds": 5,       # K：最多轮数，每保留一个新版本进入下一轮
    "max_tries": 5,        # J：每轮最多提交次数，连续 J 次没有改进时停止
}

SPLITS = ("train", "val")
RUNS = Path("runs")
HISTORY = RUNS / "history.jsonl"
PROMPT = Path(__file__).with_name("proposer.md")
ENV = os.environ | {"PYTHONDONTWRITEBYTECODE": "1"}  # 不在 harness 副本中生成 __pycache__
CFG = {}


def fill(template, **values):
    return [str(arg).format(**values) for arg in template]


def read_lines(path):
    return [line.strip() for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def harness_dir(version):
    return RUNS / "candidates" / version / Path(CFG["harness"]).name


def selected_file(split):
    """筛选后保留的题目。"""
    return RUNS / split / "selected_questions.txt"


def read_scores(path, qids):
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    scores = {r["qid"]: r for r in rows}
    if len(scores) != len(rows) or scores.keys() != set(qids) or not all(
            type(r["correct"]) is int and r["correct"] in (0, 1) for r in rows):
        sys.exit(f"{path} 格式不对：题号文件中的每道题一行、不重复，correct 要是整数 0 或 1")
    return scores


def evaluate(version, questions, out, n):
    """在题号文件 questions 中的题目上评测 version n 次，第 i 次的结果放在 out/i/；已有的结果直接读取。"""
    qids = read_lines(questions)
    runs = []
    for i in range(1, n + 1):
        d = out / str(i)
        if not (d / "scores.jsonl").exists():
            d.mkdir(parents=True, exist_ok=True)
            cmd = fill(CFG["eval"], harness=harness_dir(version), questions=questions,
                       scores=d / "scores.tmp", trajectory=d / "trajectory")
            subprocess.run(cmd, check=True, env=ENV)
            read_scores(d / "scores.tmp", qids)  # 格式正确才作为完整结果保存
            (d / "scores.tmp").replace(d / "scores.jsonl")
        runs.append(read_scores(d / "scores.jsonl", qids))
    return runs


def results(version, split):
    """version 在保留的题目上的 R 次评测。"""
    return evaluate(version, selected_file(split), RUNS / split / version, CFG["repeats"])


def average(runs):
    """每道题在多次评测中的平均分。"""
    return {q: sum(r[q]["correct"] for r in runs) / len(runs) for q in runs[0]}


def mean(rows, key):
    vals = [r[key] for r in rows if key in r]
    return round(sum(vals) / len(vals), 1) if vals else None


def p_value(diffs):
    """单侧精确检验：假如修改无效，每道题的变化取正、取负的可能性相同；p 是变化之和不小于实际值的概率。"""
    diffs = [d for d in diffs if d]
    top = sum(abs(d) for d in diffs)
    ways = [0] * top + [1] + [0] * top  # ways[top + s]：变化之和为 s 的正负号组合数
    for d in map(abs, diffs):
        ways = [x + y for x, y in zip([0] * d + ways[:-d], ways[d:] + [0] * d)]
    return sum(ways[top + sum(diffs):]) / 2 ** len(diffs)


def compare(before, after):
    """逐题比较两个版本在 R 次评测中答对的次数。"""
    diff = {q: sum(r[q]["correct"] for r in after) - sum(r[q]["correct"] for r in before) for q in before[0]}
    fixed = sorted(q for q, d in diff.items() if d > 0)
    broken = sorted(q for q, d in diff.items() if d < 0)
    p = p_value(list(diff.values()))
    result = {"pass": p < CFG["alpha"], "p_value": float(f"{p:.3g}"), "fixed": fixed, "broken": broken}
    for name, runs in (("before", before), ("after", after)):
        rows = [row for r in runs for row in r.values()]
        result[name] = {"acc": round(sum(r["correct"] for r in rows) / len(rows), 4),
                        "tokens": mean(rows, "tokens"), "steps": mean(rows, "steps")}
    return result


def same_tree(a, b):
    files = lambda d: {p.relative_to(d): p.read_bytes() for p in d.rglob("*") if p.is_file() and "__pycache__" not in p.parts}
    return files(a) == files(b)


def eval_hash():
    """评测命令、题号文件和 eval_files 内容的哈希。"""
    h = hashlib.sha256(json.dumps(CFG["eval"]).encode())
    for f in [CFG["train"], CFG["val"], *CFG["eval_files"]]:
        h.update(f.encode() + Path(f).read_bytes())
    return h.hexdigest()


def detection_rates():
    """用 v0.0 在保留题目上的评测估计结果的波动，写出不同 R 和 α 下版本被保留的概率。"""
    r0 = CFG["repeats"]
    if r0 < 2:  # 至少评测两次才能估计波动
        return
    spread = []  # 每份数据：（两个相同版本各评测一次，保留题目上答对题数之差的标准差；全部题数）
    for split in SPLITS:
        var = sum(m * (1 - m) for m in average(results("v0.0", split)).values()) * r0 / (r0 - 1)
        spread.append((math.sqrt(2 * var) or 1e-9, len(read_lines(CFG[split]))))
    z = NormalDist()

    def keep(points, r, alpha):  # 全部题目上提升 points 个点的版本，评测 r 次时通过两项检查的概率
        return math.prod(z.cdf(points * total / 100 / (sd / math.sqrt(r)) - z.inv_cdf(1 - alpha))
                         for sd, total in spread)

    alphas = (0.05, 0.1, 0.2)
    lines = ["按 v0.0 在保留题目上的评测估计。提升按全部题目计算。", "",
             "| 被保留的概率 | " + " | ".join(f"α = {a}" for a in alphas) + " |", "|---|" + "---|" * len(alphas)]
    lines += [f"| 提升 {d} 个点，R = {r} | " + " | ".join(f"{keep(d, r, a):.0%}" for a in alphas) + " |"
              for d in (1, 2) for r in range(1, 6)]
    lines.append("| 没有改进（上限） | " + " | ".join(f"{100 * a * a:g}%" for a in alphas) + " |")
    (RUNS / "detection_rates.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def prepare():
    """筛选出 v0.0 不能稳定答对的题目，再在这些题目上评测 v0.0。"""
    for split in SPLITS:
        screen = evaluate("v0.0", CFG[split], RUNS / split / "v0.0" / "screen", CFG["screen_runs"])
        if not selected_file(split).exists():
            kept = [q for q in read_lines(CFG[split]) if not all(r[q]["correct"] for r in screen)]
            if not kept:
                sys.exit(f"v0.0 在 {split} 的每次评测中都全部答对，没有需要优化的题目")
            selected_file(split).write_text("\n".join(kept) + "\n", encoding="utf-8")
        results("v0.0", split)
    detection_rates()


def rejected(reason):
    return {"result": "rejected", "reason": reason}


def attempt(current, new, previous):
    """previous 是本轮上一次提交的记录；本轮第一次提交时为 None。"""
    cand = RUNS / "candidates" / new
    parent = previous["version"] if previous else current  # 同一轮的提交接着上一次提交修改

    # 1. proposer 在 parent 的副本上修改 harness；proposer.jsonl 存在表示这一步已完成
    if not (cand / "proposer.jsonl").exists():
        for split in SPLITS:
            shutil.rmtree(RUNS / split / new, ignore_errors=True)
        (cand / "proposal.json").unlink(missing_ok=True)
        resumed = harness_dir(new).exists()  # 上次运行中断时，保留已有的修改，和 proposer 会话保持一致
        if not resumed:
            shutil.copytree(harness_dir(parent), harness_dir(new))
        prompt = PROMPT.read_text(encoding="utf-8")
        if CFG["task"]:
            prompt += "\n\n" + Path(CFG["task"]).read_text(encoding="utf-8")
        if previous:
            prompt += f"\n\n## 上一次提交\n\n{parent} 没有通过：{previous['reason']}。{new} 是 {parent} 的副本，可以接着修改。"
        if resumed:
            prompt += f"\n\n上一次修改 {new} 的运行中断了，{new} 中可能已有部分修改。"
        for k, v in {"{current}": current, "{parent}": parent, "{new}": new, "{name}": Path(CFG["harness"]).name}.items():
            prompt = prompt.replace(k, v)
        user = f"{os.getuid()}:{os.getgid()}" if hasattr(os, "getuid") else "0:0"
        with open(cand / "proposer.tmp", "w", encoding="utf-8") as f:
            cmd = fill(CFG["proposer"], runs=RUNS.resolve(), current=current, new=new, user=user)
            subprocess.run(cmd + [prompt], stdout=f, check=True)
        (cand / "proposer.tmp").replace(cand / "proposer.jsonl")

    # 没有写出 proposal.json 多半是模型服务出错，不计为一次提交；重新运行时重做这一步
    if not (cand / "proposal.json").exists():
        (cand / "proposer.jsonl").replace(cand / "proposer.failed.jsonl")
        sys.exit(f"{new}：proposer 没有写出 proposal.json，可能是模型服务出错。"
                 f"查看 {cand / 'proposer.failed.jsonl'} 后重新运行")

    # 2. 检查提议：harness 有改动，proposal.json 格式正确，targets 是当前版本没有全部答对的训练题
    if same_tree(harness_dir(parent), harness_dir(new)):
        return {"parent": parent} | rejected("没有修改 harness")
    try:
        proposal = json.loads((cand / "proposal.json").read_text(encoding="utf-8"))
        entry = {"parent": parent, "problem": proposal["problem"], "change": proposal["change"]}
        targets = proposal["targets"]
        if not isinstance(targets, list):
            raise TypeError
        targets = sorted(set(targets))
    except (OSError, ValueError, KeyError, TypeError):
        return {"parent": parent} | rejected("proposal.json 缺失或格式不对")
    wrong = {q for q, m in average(results(current, "train")).items() if m < 1}
    if not targets or not set(targets) <= wrong:
        return entry | rejected("targets 要是当前版本在保留的训练题中没有全部答对的题号")
    if CFG["check"]:
        r = subprocess.run(fill(CFG["check"], harness=harness_dir(new), base=harness_dir(current)),
                           capture_output=True, text=True, env=ENV)
        if r.returncode != 0:
            return entry | rejected("候选检查未通过：" + (r.stdout + r.stderr).strip()[-300:])

    # 3. 训练集检查：在保留的训练题上，平均分显著高于当前版本
    check = compare(results(current, "train"), results(new, "train"))
    (RUNS / "train" / new / "check.json").write_text(json.dumps(check, indent=2))
    fixed, broken = len(check["fixed"]), len(check["broken"])
    entry["train"] = {"fixed": fixed, "broken": broken}
    if not check["pass"]:
        return entry | rejected(f"训练集检查未通过：和 {current} 相比，{fixed} 题平均分升高、{broken} 题降低，p={check['p_value']}")

    # 4. 验证集检查：在保留的验证题上，平均分也显著高于当前版本
    check = compare(results(current, "val"), results(new, "val"))
    (RUNS / "val" / new / "check.json").write_text(json.dumps(check, indent=2))
    if not check["pass"]:
        return entry | rejected("训练集检查通过，但验证集检查未通过：平均分没有显著提高")
    return entry | {"result": "kept"}


def final(current):
    """v0.0 和最终版本在全部题目上各评测 R 次并比较，并列出筛掉的题目中变差的题。"""
    if current == "v0.0":
        print("没有保留任何修改")
        return
    for split in SPLITS:
        out = RUNS / "final" / split
        before = evaluate("v0.0", CFG[split], out / "v0.0", CFG["repeats"])
        after = evaluate(current, CFG[split], out / current, CFG["repeats"])
        check = compare(before, after)
        kept = set(read_lines(selected_file(split)))
        check["broken_screened_out"] = [q for q in check["broken"] if q not in kept]  # 筛掉的题目中平均分降低的
        (out / current / "check.json").write_text(json.dumps(check, indent=2))
        print(f"{split}：正确率 {check['before']['acc']} → {check['after']['acc']}，p={check['p_value']}；"
              f"筛掉的题目中 {len(check['broken_screened_out'])} 题平均分降低")


def main():
    try:
        CFG.update(DEFAULTS | json.loads(Path("evolve.json").read_text(encoding="utf-8")))
    except FileNotFoundError:
        sys.exit("请在项目根目录运行，并准备好 evolve.json")
    RUNS.mkdir(exist_ok=True)
    lock = open(RUNS / "lock", "w")  # 同一时间只允许一个 evolve.py 使用 runs/
    if fcntl:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            sys.exit("另一个 evolve.py 正在使用 runs/")

    # 初始版本：复制 harness 作为 v0.0；评测方式改过时停止，不混用新旧结果
    if not harness_dir("v0.0").exists():
        tmp = RUNS / "candidates" / "v0.0.tmp"  # 复制完成后再改名，中断时不会留下不完整的初始版本
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.copytree(CFG["harness"], tmp / Path(CFG["harness"]).name, ignore=shutil.ignore_patterns("__pycache__"))
        tmp.rename(RUNS / "candidates" / "v0.0")
    if not (RUNS / "eval_hash.txt").exists():
        (RUNS / "eval_hash.txt").write_text(eval_hash())
    elif (RUNS / "eval_hash.txt").read_text() != eval_hash():
        sys.exit("评测方式改过了（eval、train、val 或 eval_files），旧结果不能再用，请把 runs/ 改名后重新开始")
    (RUNS / "sessions").mkdir(exist_ok=True)  # proposer 会话文件，可选
    HISTORY.touch()
    prepare()

    history = [json.loads(line) for line in HISTORY.read_text(encoding="utf-8").splitlines()]
    while True:
        # 版本号 vK.J：K 是轮次，J 是本轮第几次提交；当前版本是最近一个被保留的版本
        current = next((h["version"] for h in reversed(history) if h["result"] == "kept"), "v0.0")
        k = int(current[1:].split(".")[0]) + 1
        j = sum(h["version"].startswith(f"v{k}.") for h in history)
        if k > CFG["max_rounds"] or j >= CFG["max_tries"]:
            break
        if all(m == 1 for m in average(results(current, "train")).values()):
            print("当前版本在保留的训练题上已经全部答对")
            break
        if (RUNS / "stop").exists():
            (RUNS / "stop").unlink()
            sys.exit("看到 runs/stop，已停止；再次运行会接着继续")
        new = f"v{k}.{j + 1}"
        previous = next((h for h in reversed(history) if h["version"].startswith(f"v{k}.")), None)
        entry = {"version": new} | attempt(current, new, previous)
        history.append(entry)
        with open(HISTORY, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        print(json.dumps(entry, ensure_ascii=False))

    print(f"优化结束。最终版本 {current} 的 harness 在 {harness_dir(current)}。")
    final(current)


if __name__ == "__main__":
    main()
