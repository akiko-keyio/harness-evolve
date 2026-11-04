---
name: harness-evolve
description: 循环修改一个 agent 的 harness，并用验证集检验每次修改是否提高了正确率。用户说"开始或继续 harness 优化"时使用。
---

# Harness 优化循环

目标：模型不变，通过修改 harness 提高 agent 的正确率。

你是 orchestrator，负责按下面的步骤运行命令、调用 proposer（子 agent）。不要自己修改 harness，也不要自己判断修改好坏，一律以 `eval/check.py` 的输出为准。

每次尝试都有一个版本号 vK.J：K 是轮次，J 是本轮第几次尝试（从 0 开始），v0.0 是初始版本。每次尝试中，proposer 先修改 harness，然后做训练集检查和验证集检查。两项都通过，修改成为新的当前版本，进入下一轮；否则撤销修改，本轮再试。

## 配置

- harness 文件（允许修改的文件）：`<例如 agent/prompts/*.md>`
- 评测命令：`<例如 python eval/run.py --split {split} --out {out} [--qids {qids}]>`
  - `split` 取 train 或 val；`--qids` 是逗号分隔的题号，传入时只运行这些题
  - 命令输出 `{out}/results.jsonl`（每行一道题：`{"qid": ..., "correct": 0 或 1}`）和 `{out}/traces/`（每道题一个轨迹文件，文件名包含题号）
- 显著性水平：0.05
- 最多轮数：5
- 每轮最多尝试次数：3

## 准备（由人完成）

1. 把评测数据集分成训练集、验证集和测试集。来源相同的题（例如同一个视频的多道题）放在同一份里。
2. 在专用分支上提交当前代码，执行 `git tag v0.0`，并把 `runs/` 加入 `.gitignore`。
3. 用评测命令运行 v0.0：训练集输出到 `runs/v0.0/eval_train/`，验证集输出到 `runs/v0.0/eval_val/`。

## 确定进度

每次尝试开始前，先确定：

- 当前版本 `{current}`：执行 `git describe --tags --abbrev=0` 得到的标签。
- 轮次 K：`{current}` 的轮次加 1。例如当前版本为 v1.1 时，K 为 2。
- 本次尝试的版本 `{new}`：vK.J，其中 J 是 `runs/` 下已有的 vK.* 目录个数。例如已有 `runs/v2.0/` 时，本次版本为 v2.1。

如果 K 超过最多轮数，或者 J 达到每轮最多尝试次数，停止。

## 一次尝试

1. 确认 `git status --porcelain` 没有输出。有输出说明工作区有未提交的改动，停止。
2. 调用 proposer，传给它 `{current}`、`{new}` 和 harness 文件（它会自己读取 `runs/` 中以前各次尝试的记录）。它返回后，确认：
   - `runs/{new}/proposal.json` 已经写出；
   - `git status --porcelain` 中只出现 harness 文件，且状态都是 M（只修改，没有新建或删除）。

   任一项不满足，停止。
3. 训练集检查：用评测命令在训练集上只运行 `proposal.json` 中 `targets` 列出的题，输出到 `runs/{new}/eval_train_targets/`，然后执行：
   `python eval/check.py check-train runs/{current}/eval_train/results.jsonl runs/{new}/eval_train_targets/results.jsonl --out runs/{new}/check_train.json`
4. 验证集检查（仅当 `check_train.json` 中 `pass` 为 true）：用评测命令运行整个验证集，输出到 `runs/{new}/eval_val/`，然后执行：
   `python eval/check.py check-val runs/{current}/eval_val/results.jsonl runs/{new}/eval_val/results.jsonl --alpha <显著性水平> --out runs/{new}/check_val.json`
5. 收尾：
   - 两项检查都通过：用评测命令运行整个训练集，输出到 `runs/{new}/eval_train/`，然后执行 `git commit -am {new} && git tag {new}`。
   - 否则：执行 `git restore .` 撤销修改。

任何命令出错，停止。

## 停止后报告

- 通过的各个版本，以及每个版本的 `change`、`acc_before` 和 `acc_after`；
- 没有通过的版本，以及没有通过哪一项检查；
- 如果因为出错或检查不满足而停止，说明原因，并给出相关的命令和输出。

## 不要做的事

- 不要读取任何 `eval_val/` 目录和测试集。
- 不要修改评测命令、评测数据集和 `eval/check.py`。
