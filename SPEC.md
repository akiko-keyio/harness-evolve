# 接入规范

接入一个新任务，需要提供三样东西：评测数据集的划分、初始 harness 文件夹和评测脚本 `eval.py`。

```
project/
├── harness/        初始 harness 文件夹：所有待优化的 harness 代码
├── eval.py         评测脚本
├── data/           评测数据集
├── evolve.py
└── proposer.md
```

## 评测数据集

划分为 train、val、test 三份，由 `eval.py` 按 `--split` 读取。来源相同的题（例如同一个视频的多道题）放在同一份里，避免信息从训练集泄露到验证集。

示例 `data/splits.json`：

```json
{"train": ["q001", "q002", "..."], "val": ["q101", "..."], "test": ["q201", "..."]}
```

## harness 文件夹

- 包含所有待优化的 harness 代码：system prompt、工具、上下文管理等。proposer 只能修改这个文件夹内的文件。
- 对外提供一个固定的入口，供 `eval.py` 调用。proposer 不能改变入口的参数和返回格式。
- 评测脚本和数据集不放在这个文件夹里。

示例：

```
harness/
├── agent.py        入口：run(question) -> {"answer", "tokens", "steps", "trace"}
├── prompts/
│   └── system.md
└── tools/
    └── video.py
```

## 评测脚本

调用方式：

```
python eval.py --split train --out runs/v0.0/eval_train [--qids q001,q002]
```

- `--split`：train、val 或 test。
- `--out`：输出目录。
- `--qids`：可选，逗号分隔的题号，只运行这些题。

输出：

```
<out>/
├── results.jsonl   每行一道题
└── traces/         每道题一个轨迹文件，文件名为题号，例如 q001.json
```

`results.jsonl` 每行的字段：

| 字段 | 含义 |
|---|---|
| `qid` | 题号 |
| `correct` | 是否答对，0 或 1 |
| `tokens` | 这道题消耗的 token 数 |
| `steps` | agent 运行的步数 |

示例：

```json
{"qid": "q001", "correct": 1, "tokens": 5230, "steps": 7}
```

轨迹文件要包含 proposer 分析错误所需的全部信息：题目、标准答案、agent 的完整消息和工具调用、最终答案。

示例 `eval.py`：

```python
import argparse
import json
from pathlib import Path

from harness.agent import run

ap = argparse.ArgumentParser()
ap.add_argument("--split", choices=["train", "val", "test"], required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--qids")
args = ap.parse_args()

qids = set(json.load(open("data/splits.json"))[args.split])
if args.qids:
    qids &= set(args.qids.split(","))
questions = [q for q in map(json.loads, open("data/questions.jsonl")) if q["qid"] in qids]

out = Path(args.out)
(out / "traces").mkdir(parents=True, exist_ok=True)
with open(out / "results.jsonl", "w") as f:
    for q in questions:
        r = run(q)
        correct = int(r["answer"] == q["answer"])
        f.write(json.dumps({"qid": q["qid"], "correct": correct,
                            "tokens": r["tokens"], "steps": r["steps"]}) + "\n")
        trace = {"question": q, "answer": r["answer"], "correct": correct, "trace": r["trace"]}
        (out / "traces" / f"{q['qid']}.json").write_text(json.dumps(trace, ensure_ascii=False, indent=2))
```

单道题运行出错时，记为答错并把错误信息写进轨迹，不要让整个脚本退出。
