# 接入规范

接入一个新任务，需要提供评测数据集、初始 harness 文件夹、评测脚本和配置 `evolve.json`，可以另外提供候选检查脚本和任务说明。

```
project/
├── harness/        初始 harness 文件夹：所有待优化的 harness 代码
├── eval.py         评测脚本
├── evolve.json     配置
├── data/           评测数据集
├── check.py        候选检查脚本（可选）
└── task.md         任务说明（可选）
```

## 评测数据集

划分为 train、val、test 三份，由评测脚本按 `--split` 读取。来源相同的题（例如同一个视频的多道题）放在同一份里，避免信息从训练集泄露到验证集。

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
    └── video.py
```

## 评测脚本

评测脚本在指定的 split 上评测指定的 harness，写出得分文件和轨迹。命令在 `evolve.json` 的 `eval` 中给出，可以带任意自己的参数，其中这些占位符会被替换：

| 占位符 | 含义 |
|---|---|
| `{harness}` | 要评测的 harness 文件夹 |
| `{split}` | train、val 或 test |
| `{scores}` | 得分文件，每行一道题 |
| `{trajectory}` | 轨迹目录，每道题一个文件，文件名为题号，例如 `q001.json` |

只运行部分题时，命令后面会追加 `--qids q001,q002`。

得分文件每行的字段：

| 字段 | 含义 |
|---|---|
| `qid` | 题号，字符串，不重复 |
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
- 需要逐题续跑时，由评测脚本自己缓存逐题结果。缓存放在 proposer 看不到的地方（不要放在 `runs/train/` 下），轨迹中也不要放 proposer 不该看的内容。

示例 `eval.py`：

```python
import argparse
import json
import sys
import traceback
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--harness", required=True)
ap.add_argument("--split", choices=["train", "val", "test"], required=True)
ap.add_argument("--scores", required=True)
ap.add_argument("--trajectory", required=True)
ap.add_argument("--qids")
args = ap.parse_args()

sys.path.insert(0, str(Path(args.harness).resolve().parent))  # 从指定的 harness 副本导入
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
| `eval` | 评测命令，参数数组 | 必填 |
| `check` | 候选检查命令，参数数组 | 不检查 |
| `task` | 任务说明文件 | 无 |
| `eval_files` | 影响评测结果的文件，例如评测脚本、数据划分、模型配置；它们或 `eval` 改过时，`evolve.py` 会停止 | `[]` |
| `proposer` | proposer 命令，参数数组，最后会追加 prompt | 在容器中运行 pi，见 `evolve.py` |
| `alpha` | 显著性水平 | `0.05` |
| `max_rounds` | 最多轮数 K | `5` |
| `max_tries` | 每轮最多尝试次数 J | `3` |

示例：

```json
{
  "harness": "harness",
  "eval": ["python", "eval.py", "--harness", "{harness}", "--split", "{split}",
           "--scores", "{scores}", "--trajectory", "{trajectory}"],
  "check": ["python", "check.py", "{harness}", "{base}"],
  "task": "task.md",
  "eval_files": ["eval.py", "data/splits.json"]
}
```

`proposer` 中的占位符：`{runs}` 是 `runs/` 的绝对路径，`{new}` 是本次版本号，`{user}` 是当前用户。默认命令只把 `runs/history.jsonl`、`runs/candidates/` 和 `runs/train/` 挂进容器，其中只有本次版本的 `runs/candidates/<版本>/` 可写。更换模型或 API key 时，复制默认命令修改即可。`Dockerfile.pi` 让 pi 在容器内最多运行 1 小时，超时或中断后容器会自动删除。
