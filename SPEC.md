# 接入规范

接入一个新任务，需要提供三样东西：评测数据集的划分、初始 harness 文件夹和评测脚本 `eval.py`。

```
project/
├── harness/        初始 harness 文件夹：所有待优化的 harness 代码
├── eval.py         评测脚本
├── data/           评测数据集
└── .gitignore      包含 data/、runs/
```

## 评测数据集

划分为 train、val、test 三份，由 `eval.py` 按 `--split` 读取。来源相同的题（例如同一个视频的多道题）放在同一份里，避免信息从训练集泄露到验证集。

数据集不提交到 git，否则 proposer 可以通过 git 历史看到验证集和测试集。

示例 `data/splits.json`：

```json
{"train": ["q001", "q002", "..."], "val": ["q101", "..."], "test": ["q201", "..."]}
```

## harness 文件夹

- 包含所有待优化的 harness 代码：system prompt、工具、上下文管理等。proposer 只能修改这个文件夹内的文件。
- 对外提供一个固定的入口，供 `eval.py` 调用。proposer 不能改变入口的参数和返回格式。
- 模型和推理参数（温度、reasoning effort 等）由 `eval.py` 设定，通过入口传给 harness，harness 不能修改。token 用量、步数和超时由 harness 自己决定，只做记录。
- 评测脚本和数据集不放在这个文件夹里。
- 运行时生成的文件（例如 `__pycache__/`、缓存）加入 `.gitignore`，否则会被当作 harness 的改动提交。

示例：

```
harness/
├── agent.py        入口：run(question, llm) -> {"answer", "tokens", "steps", "trajectory"}
├── prompts/
│   └── system.md
└── tools/
    └── video.py
```

## 评测脚本

调用方式：

```
python eval.py --split train --scores runs/train/v0.0/scores.jsonl --trajectory runs/train/v0.0/trajectory [--qids q001,q002]
```

- `--split`：train、val 或 test。
- `--scores`：得分文件，每行一道题。
- `--trajectory`：轨迹目录，每道题一个轨迹文件，文件名为题号，例如 `q001.json`。
- `--qids`：可选，逗号分隔的题号，只运行这些题。

得分文件每行的字段：

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

harness 出错（包括无法导入）时，这道题记为答错，错误信息写进轨迹，脚本继续运行。只有评测脚本自身出错时才以非零状态退出，此时 `evolve.py` 会停止。

示例 `eval.py`：

```python
import argparse
import json
import traceback
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--split", choices=["train", "val", "test"], required=True)
ap.add_argument("--scores", required=True)
ap.add_argument("--trajectory", required=True)
ap.add_argument("--qids")
args = ap.parse_args()

llm = make_llm(model="claude-opus-4-6", temperature=0)  # 你自己的 LLM 客户端：模型和推理参数固定在这里

qids = set(json.load(open("data/splits.json"))[args.split])
if args.qids:
    qids &= set(args.qids.split(","))
questions = [q for q in map(json.loads, open("data/questions.jsonl")) if q["qid"] in qids]

traj_dir = Path(args.trajectory)
traj_dir.mkdir(parents=True, exist_ok=True)
with open(args.scores, "w") as f:
    for q in questions:
        try:
            from harness.agent import run  # 在 try 中导入：harness 有语法错误时，也只是记为答错
            r = run(q, llm)
        except Exception:
            r = {"answer": None, "tokens": 0, "steps": 0, "trajectory": traceback.format_exc()}
        correct = int(r["answer"] == q["answer"])
        f.write(json.dumps({"qid": q["qid"], "correct": correct,
                            "tokens": r["tokens"], "steps": r["steps"]}) + "\n")
        traj = {"question": q, "answer": r["answer"], "correct": correct, "trajectory": r["trajectory"]}
        (traj_dir / f"{q['qid']}.json").write_text(json.dumps(traj, ensure_ascii=False, indent=2))
```

