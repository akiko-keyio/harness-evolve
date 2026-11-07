# 接入规范

接入一个新任务，需要提供数据集划分、初始 harness 文件夹、评测脚本和配置 `evolve.json`，可以另外提供候选检查脚本和任务说明。

```
project/
├── harness/        初始 harness 文件夹：所有待优化的 harness 代码
├── eval.py         评测脚本
├── evolve.json     配置
├── data/
│   ├── train.txt   训练集题号，每行一个
│   └── val.txt     验证集题号，每行一个
├── check.py        候选检查脚本（可选）
└── task.md         任务说明（可选）
```

## 数据集

把题目分为训练集和验证集，各写一个题号文件，每行一个题号。来源相同的题（例如同一篇文档的多道题）放在同一份里，避免信息从训练集泄露到验证集。

## harness 文件夹

- 包含所有待优化的 harness 代码：system prompt、工具、上下文管理等。
- 每个版本都是这个文件夹的一份副本，放在 `runs/candidates/<版本>/` 中。harness 读取自己的文件时，要按自身位置定位（例如 `Path(__file__).parent`），不能按工作目录定位，否则读到的是初始版本。
- 对外提供一个固定的入口，供评测脚本调用。proposer 不能改变入口的参数和返回格式。
- 模型和推理参数（温度、reasoning effort 等）由评测脚本设定，通过入口传给 harness，harness 不能修改。token 用量、步数和超时由 harness 自己决定，只做记录。
- 评测时，harness 代码在宿主机上运行，不受沙箱限制。需要限制修改范围时（例如只允许改 prompt），用候选检查脚本检查。

示例：

```
harness/
├── agent.py        入口：run(question, llm) -> {"answer", "tokens", "steps", "trajectory"}
├── prompts/
│   └── system.md
└── tools/
    └── search.py
```

## 评测脚本

评测脚本在指定的题目上评测指定的 harness，写出得分文件和轨迹。命令在 `evolve.json` 的 `eval` 中给出，可以带任意自己的参数，其中这些占位符会被替换：

| 占位符 | 含义 |
|---|---|
| `{harness}` | 要评测的 harness 文件夹 |
| `{questions}` | 题号文件，每行一个题号，只评测这些题 |
| `{scores}` | 得分文件，每行一道题 |
| `{trajectory}` | 轨迹目录，每道题一个文件，文件名为题号，例如 `q001.json` |

得分文件每行的字段：

| 字段 | 含义 |
|---|---|
| `qid` | 题号，和题号文件一致，每道题一行 |
| `correct` | 是否答对，0 或 1 |
| `tokens` | 这道题消耗的 token 数 |
| `steps` | agent 运行的步数 |

示例：

```json
{"qid": "q001", "correct": 1, "tokens": 5230, "steps": 7}
```

- 轨迹文件要包含 proposer 分析错误所需的全部信息：题目、标准答案、agent 的完整消息和工具调用、最终答案。
- 不要把标准答案传给 harness。
- harness 出错（包括无法导入）时，这道题记为答错，错误信息写进轨迹，脚本继续运行。评测脚本自身或模型服务出错时以非零状态退出，此时 `evolve.py` 会停止，重新运行时会重做这次评测。
- 同一个版本会在同一批题上评测多次，每次都要重新运行，不能复用上一次的结果。
- 需要逐题续跑时，由评测脚本自己缓存这一次评测的逐题结果。缓存放在 proposer 看不到的地方（不要放在 `runs/train/` 下），轨迹中也不要放 proposer 不该看的内容。

示例 `eval.py`：

```python
import argparse
import json
import sys
import traceback
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--harness", required=True)
ap.add_argument("--questions", required=True)
ap.add_argument("--scores", required=True)
ap.add_argument("--trajectory", required=True)
args = ap.parse_args()

sys.path.insert(0, str(Path(args.harness).resolve().parent))  # 从指定的 harness 副本导入
llm = make_llm(model="claude-opus-4-6", temperature=1)  # 你自己的 LLM 客户端：模型和推理参数固定在这里

qids = set(Path(args.questions).read_text().split())
questions = [q for q in map(json.loads, open("data/questions.jsonl")) if q["qid"] in qids]

traj_dir = Path(args.trajectory)
traj_dir.mkdir(parents=True, exist_ok=True)
with open(args.scores, "w") as f:
    for q in questions:
        try:
            from harness.agent import run  # 在 try 中导入：harness 有语法错误时，也只是记为答错
            r = run({k: v for k, v in q.items() if k != "answer"}, llm)  # 不把标准答案传给 harness
        except LLMServiceError:  # 模型服务故障不是 harness 的错：让评测脚本退出
            raise
        except Exception:
            r = {"answer": None, "tokens": 0, "steps": 0, "trajectory": traceback.format_exc()}
        correct = int(r["answer"] == q["answer"])
        f.write(json.dumps({"qid": q["qid"], "correct": correct,
                            "tokens": r["tokens"], "steps": r["steps"]}) + "\n")
        traj = {"question": q, "answer": r["answer"], "correct": correct, "trajectory": r["trajectory"]}
        (traj_dir / f"{q['qid']}.json").write_text(json.dumps(traj, ensure_ascii=False, indent=2))
```

## 候选检查脚本（可选）

proposer 修改完成后、评测之前运行，用来检查修改范围或运行离线测试。占位符 `{harness}` 是候选版本，`{base}` 是它所基于的当前版本。以非零状态退出表示不通过，输出的最后几行会作为原因记录。

检查脚本不能修改候选；中断后重新运行时它会再运行一次，所以结果要确定。

## 任务说明（可选）

追加在 `proposer.md` 后面，一起交给 proposer。用来说明任务本身、harness 各部分的作用、轨迹怎么看，以及额外的修改限制。

## evolve.json

| 键 | 含义 | 默认值 |
|---|---|---|
| `harness` | 初始 harness 文件夹 | `"harness"` |
| `train` | 训练集题号文件 | 必填 |
| `val` | 验证集题号文件 | 必填 |
| `eval` | 评测命令，参数数组 | 必填 |
| `check` | 候选检查命令，参数数组 | 不检查 |
| `task` | 任务说明文件 | 无 |
| `eval_files` | 其他影响评测结果的文件，例如评测脚本、模型配置；它们、题号文件或 `eval` 改过时，`evolve.py` 会停止 | `[]` |
| `proposer` | proposer 命令，参数数组，最后会追加 prompt | 在容器中运行 pi，见 `evolve.py` |
| `screen_runs` | S：筛选题目时，v0.0 在全部题目上评测几次 | `3` |
| `repeats` | R：每个版本在保留的题目上评测几次 | `3` |
| `alpha` | α：检查的显著性水平 | `0.2` |
| `max_rounds` | K：最多轮数 | `5` |
| `max_tries` | J：每轮最多提交次数 | `5` |

示例：

```json
{
  "harness": "harness",
  "train": "data/train.txt",
  "val": "data/val.txt",
  "eval": ["python", "eval.py", "--harness", "{harness}", "--questions", "{questions}",
           "--scores", "{scores}", "--trajectory", "{trajectory}"],
  "check": ["python", "check.py", "{harness}", "{base}"],
  "task": "task.md",
  "eval_files": ["eval.py"]
}
```

`proposer` 中的占位符：`{runs}` 是 `runs/` 的绝对路径，`{current}` 是当前版本号，`{new}` 是本次版本号，`{user}` 是当前用户。

同一轮的提交可以接续同一个 proposer 会话，这样 proposer 记得自己之前的分析。会话文件放在 `runs/sessions/` 中，用 `{current}` 命名，同一轮共用一个，保留新版本后自然换新。以 pi 为例，在默认命令中加上 `"-v", "{runs}/sessions:/workspace/runs/sessions"`，并把 `--no-session` 换成 `"--session", "/workspace/runs/sessions/{current}.jsonl"`（参数以实际使用的 pi 版本为准）。默认命令只把 `runs/history.jsonl`、`runs/candidates/` 和 `runs/train/` 挂进容器，其中只有本次版本的 `runs/candidates/<版本>/` 可写。更换模型或 API key 时，复制默认命令修改即可。`Dockerfile.pi` 让 pi 在容器内最多运行 3 小时，超时或中断后容器会自动删除；重新运行时会接着已有的修改继续。
