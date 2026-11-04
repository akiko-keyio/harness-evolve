"""harness-evolve：让 proposer 修改 harness，只保留在验证集上显著变好的修改。

在项目根目录运行，配置读取 evolve.json（见 SPEC.md）：
  python <harness-evolve 目录>/evolve.py          运行优化；中途停止后再次运行，已完成的步骤不会重做
  python <harness-evolve 目录>/evolve.py final    在测试集上比较初始版本和当前版本；之后不能再继续优化
"""
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULTS = {
    "harness": "harness",  # 初始 harness 文件夹
    "eval": None,          # 评测命令，必填
    "check": None,         # 候选检查命令，可选
    "task": None,          # 追加给 proposer 的任务说明文件，可选
    "protocol": [],        # 决定评测结果的文件，例如评测脚本、数据划分、模型配置
    "proposer": [          # proposer 命令：在容器中运行 pi（镜像见 Dockerfile.pi），最后追加 prompt
        "docker", "run", "--rm", "--user", "{user}", "-e", "HOME=/tmp", "-e", "ANTHROPIC_API_KEY",
        "-v", "{runs}/history.jsonl:/workspace/runs/history.jsonl:ro",
        "-v", "{runs}/candidates:/workspace/runs/candidates:ro",
        "-v", "{runs}/candidates/{new}:/workspace/runs/candidates/{new}",
        "-v", "{runs}/train:/workspace/runs/train:ro",
        "pi-sandbox", "--mode", "json", "--no-session", "--model", "claude-opus-4-6", "-p",
    ],
    "alpha": 0.05,         # 显著性水平
    "max_rounds": 5,       # 最多轮数：每保留一次修改，进入下一轮
    "max_tries": 3,        # 每轮最多尝试次数：一轮都没有通过，停止
}

RUNS = Path("runs")
HISTORY = RUNS / "history.jsonl"
PROMPT = Path(__file__).with_name("proposer.md")
ENV = os.environ | {"PYTHONDONTWRITEBYTECODE": "1"}  # 不在 harness 副本中生成 __pycache__
CFG = {}


def fill(template, **values):
    return [str(arg).format(**values) for arg in template]


def harness_dir(version):
    return RUNS / "candidates" / version / Path(CFG["harness"]).name


def result_dir(version, name):
    """targets 的结果在 train/<版本>/targets/，train、val、test 的结果在 <name>/<版本>/。"""
    return RUNS / "train" / version / "targets" if name == "targets" else RUNS / name / version


def read_scores(path):
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    scores = {r["qid"]: r for r in rows}
    if len(scores) != len(rows) or not all(isinstance(q, str) and r["correct"] in (0, 1) for q, r in scores.items()):
        sys.exit(f"{path} 格式不对：题号要是不重复的字符串，correct 要是 0 或 1")
    return scores


def scores(version, name):
    return read_scores(result_dir(version, name) / "scores.jsonl")


def evaluate(version, name, split, qids=None):
    """评测 version 的 harness；结果已经存在时直接读取。"""
    d = result_dir(version, name)
    out, tmp = d / "scores.jsonl", d / "scores.tmp"
    if not out.exists():
        d.mkdir(parents=True, exist_ok=True)
        cmd = fill(CFG["eval"], harness=harness_dir(version), split=split, scores=tmp, trajectory=d / "trajectory")
        subprocess.run(cmd + (["--qids", ",".join(qids)] if qids else []), check=True, env=ENV)
        read_scores(tmp)  # 格式正确才作为完整结果保存
        tmp.replace(out)
    return scores(version, name)


def mean(rows, key):
    vals = [r[key] for r in rows if key in r]
    return round(sum(vals) / len(vals), 1) if vals else None


def mcnemar_p(fixed, broken):
    """单侧精确 McNemar 检验：假如修改无效，至少 fixed 道题变对的概率。"""
    n = fixed + broken
    return sum(math.comb(n, i) for i in range(fixed, n + 1)) / 2 ** n if n else 1.0


def compare(before, after):
    """在同一组题上逐题比较两个版本。"""
    if before.keys() != after.keys():
        sys.exit("两个版本评测的题目不一致")
    fixed = sum(before[q]["correct"] == 0 and after[q]["correct"] == 1 for q in before)
    broken = sum(before[q]["correct"] == 1 and after[q]["correct"] == 0 for q in before)
    p = mcnemar_p(fixed, broken)
    result = {"pass": p < CFG["alpha"], "p_value": float(f"{p:.3g}"), "fixed": fixed, "broken": broken}
    for name, rows in (("before", before), ("after", after)):
        rows = list(rows.values())
        result[name] = {"acc": round(sum(r["correct"] for r in rows) / len(rows), 4),
                        "tokens": mean(rows, "tokens"), "steps": mean(rows, "steps")}
    return result


def same_tree(a, b):
    files = lambda d: {p.relative_to(d): p.read_bytes() for p in d.rglob("*") if p.is_file() and "__pycache__" not in p.parts}
    return files(a) == files(b)


def protocol():
    """评测协议的指纹：评测命令和 protocol 中各文件的内容。"""
    h = hashlib.sha256(json.dumps(CFG["eval"]).encode())
    for f in CFG["protocol"]:
        h.update(f.encode() + Path(f).read_bytes())
    return h.hexdigest()


def rejected(reason):
    return {"result": "rejected", "reason": reason}


def attempt(current, new):
    cand = RUNS / "candidates" / new

    # 1. proposer 在当前版本的副本上修改 harness；proposer.jsonl 存在表示这一步已完成
    if not (cand / "proposer.jsonl").exists():
        for d in (cand, result_dir(new, "train"), result_dir(new, "val")):
            shutil.rmtree(d, ignore_errors=True)
        shutil.copytree(harness_dir(current), harness_dir(new))
        prompt = PROMPT.read_text(encoding="utf-8")
        if CFG["task"]:
            prompt += "\n\n" + Path(CFG["task"]).read_text(encoding="utf-8")
        for k, v in {"{current}": current, "{new}": new, "{name}": Path(CFG["harness"]).name}.items():
            prompt = prompt.replace(k, v)
        user = f"{os.getuid()}:{os.getgid()}" if hasattr(os, "getuid") else "0:0"
        with open(cand / "proposer.tmp", "w", encoding="utf-8") as f:
            subprocess.run(fill(CFG["proposer"], runs=RUNS.resolve(), new=new, user=user) + [prompt], stdout=f, check=True)
        (cand / "proposer.tmp").replace(cand / "proposer.jsonl")

    # 2. 检查提议：harness 有改动，proposal.json 格式正确，targets 是当前版本在训练集上的错题
    if same_tree(harness_dir(current), harness_dir(new)):
        return rejected("没有修改 harness")
    try:
        proposal = json.loads((cand / "proposal.json").read_text(encoding="utf-8"))
        entry = {"problem": proposal["problem"], "change": proposal["change"]}
        targets = sorted(set(proposal["targets"]))
    except (OSError, ValueError, KeyError, TypeError):
        return rejected("proposal.json 缺失或格式不对")
    wrong = {q for q, r in scores(current, "train").items() if r["correct"] == 0}
    if not targets or not set(targets) <= wrong:
        return entry | rejected("targets 要是当前版本在训练集上答错的题号")
    if CFG["check"]:
        r = subprocess.run(fill(CFG["check"], harness=harness_dir(new), base=harness_dir(current)),
                           capture_output=True, text=True, env=ENV)
        if r.returncode != 0:
            return entry | rejected("候选检查未通过：" + (r.stdout + r.stderr).strip()[-300:])

    # 3. 训练集检查：targets 中至少一道题变对
    after = evaluate(new, "targets", "train", targets)
    fixed = sum(after.get(q, {}).get("correct") == 1 for q in targets)
    (result_dir(new, "train") / "check.json").write_text(json.dumps({"pass": fixed > 0, "fixed": fixed}, indent=2))
    if fixed == 0:
        return entry | rejected("训练集检查未通过：targets 中没有一道题变对")

    # 4. 验证集检查：正确率显著高于当前版本
    check = compare(scores(current, "val"), evaluate(new, "val", "val"))
    (result_dir(new, "val") / "check.json").write_text(json.dumps(check, indent=2))
    if not check["pass"]:
        return entry | rejected("验证集检查未通过：正确率没有显著提高")

    # 5. 保留：在整个训练集上评测，供下一轮分析
    evaluate(new, "train", "train")
    return entry | {"result": "kept"}


def final(current):
    """在测试集上比较初始版本和当前版本。"""
    if current == "v0.0":
        sys.exit("没有保留任何修改")
    check = compare(evaluate("v0.0", "test", "test"), evaluate(current, "test", "test"))
    (result_dir(current, "test") / "check.json").write_text(json.dumps(check, indent=2))
    print(json.dumps(check, indent=2))


def main():
    try:
        CFG.update(DEFAULTS | json.loads(Path("evolve.json").read_text(encoding="utf-8")))
    except FileNotFoundError:
        sys.exit("请在项目根目录运行，并准备好 evolve.json")
    if (RUNS / "test").exists() and sys.argv[1:] != ["final"]:
        sys.exit("已经在测试集上评测过，不能再继续优化")

    # 初始版本：复制 harness 作为 v0.0；评测协议改变时，不复用已有的结果
    if not harness_dir("v0.0").exists():
        shutil.copytree(CFG["harness"], harness_dir("v0.0"), ignore=shutil.ignore_patterns("__pycache__"))
    if not (RUNS / "protocol.txt").exists():
        (RUNS / "protocol.txt").write_text(protocol())
    elif (RUNS / "protocol.txt").read_text() != protocol():
        sys.exit("评测协议变了（eval 命令或 protocol 中的文件）。请把 runs/ 改名保存后重新开始；"
                 "确认改动不影响评测结果的话，删除 runs/protocol.txt 再运行")
    for d in ("train", "val"):
        (RUNS / d).mkdir(exist_ok=True)
    HISTORY.touch()
    for split in ("train", "val"):
        evaluate("v0.0", split, split)

    history = [json.loads(line) for line in HISTORY.read_text(encoding="utf-8").splitlines()]
    while True:
        # 版本号 vK.J：K 是轮次，J 是本轮第几次尝试；当前版本是最近一个被保留的版本
        current = next((h["version"] for h in reversed(history) if h["result"] == "kept"), "v0.0")
        if sys.argv[1:] == ["final"]:
            return final(current)
        k = int(current[1:].split(".")[0]) + 1
        j = sum(h["version"].startswith(f"v{k}.") for h in history)
        if k > CFG["max_rounds"] or j >= CFG["max_tries"]:
            break
        new = f"v{k}.{j + 1}"
        entry = {"version": new, "base": current} | attempt(current, new)
        history.append(entry)
        with open(HISTORY, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        print(json.dumps(entry, ensure_ascii=False))

    print(f"停止。当前版本 {current} 的 harness 在 {harness_dir(current)}。"
          f"用 python {sys.argv[0]} final 在测试集上比较 {current} 和 v0.0。")


if __name__ == "__main__":
    main()
