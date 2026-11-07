# harness-evolve

harness-evolve 是一个极简的 harness 改进循环。

## 组成

- **Proposer**：改进 harness 的 meta agent，由 pi coding agent 和系统指令 `proposer.md` 构成。
- **Process control**：驱动 Proposer 提出修改，再评估并决定是否保留的优化流程（`evolve.py`）。
- **Sandbox**：限制 Proposer 能读写的内容、防止 reward hacking 的隔离环境（`Dockerfile.pi`）。

## 使用

1. 在项目根目录准备以下文件，要求见 [SPEC.md](SPEC.md) 中的对应小节：
   - [数据集](SPEC.md#数据集)，分为两份：
     - train set（训练集）：Proposer 用于分析错误案例以便改进 harness。
     - validation set（验证集）：Process control 用于判断改进是否真实有效。
   - [harness 文件夹](SPEC.md#harness-文件夹)：所有待优化的 harness 代码。
   - [评测脚本](SPEC.md#评测脚本)：在指定题目上评测 harness，保存完整轨迹并计算得分和成本。
   - [evolve.json](SPEC.md#evolvejson)：配置。
2. 构建 proposer 运行的镜像：`docker build -t pi-sandbox -f <harness-evolve 目录>/Dockerfile.pi .`
3. 在项目根目录运行 `python <harness-evolve 目录>/evolve.py`。

运行中断后，再次运行会从中断处继续。想在当前提交完成后停下，创建文件 `runs/stop`。

## 流程

`evolve.py` 依次执行：

1. **筛选题目。** 全量评测很耗时，同一版本每次的结果也有波动。因此先让 v0.0 在训练集和验证集上各评测 S 次，只保留答错过的题目，之后都只在这些题目上评测。v0.0 再在这些题目上评测 R 次，作为第一轮的比较对象（筛选那几次的结果偏低，不能直接用）。
2. **迭代优化。** 每个新版本都在保留的题目上评测 R 次，按平均分和当前版本比较（见[检查](#检查)）：

   ```
   当前版本 ← v0.0
   for 每一轮（最多 K 轮）:
       for 每次提交（最多 J 次）:
           proposer 修改 harness，生成新版本
           if 新版本在训练集上没有显著优于当前版本:
               继续下一次提交
           if 新版本在验证集上没有显著优于当前版本:
               继续下一次提交
           当前版本 ← 新版本
           进入下一轮
       if 连续 J 次提交都没有改进:
           终止
   ```

3. **最终比较。** v0.0 和最终版本在全部题目上各重新评测 R 次并比较，同时检查筛掉的题目有没有被改坏；筛选时的结果在筛掉的题目上偏高，所以 v0.0 也要重新评测。最终效果以验证集上的比较为准。

## 检查

训练集检查和验证集检查都在保留的题目上逐题比较当前版本 C 和新版本 N，每道题取 R 次评测的平均分。记 $c$ 为 N 平均分更高的题数，$b$ 为 N 平均分更低的题数，$n = b + c$：

$$
p = \sum_{i=c}^{n} \binom{n}{i} \left(\frac{1}{2}\right)^{n}
$$

$p < \alpha$ 时通过。

R 和 α 决定了检查的取舍：R 越大，真实的改进越容易通过，但评测越慢；α 越大，真实的改进越容易通过，但没有改进的版本也越容易通过。没有改进的版本要碰巧通过两项检查，概率为 $\alpha^2$，和数据无关；真实改进被保留的概率则取决于数据。下表是在一个示例数据集上的估计（共 535 题，v0.0 正确率约 80%，约 30% 的题目被保留），提升按全部题目计算：

| 被保留的概率 | α = 0.05 | α = 0.1 | α = 0.2 |
|---|---|---|---|
| 提升 1 个点，R = 1 | 7% | 15% | 31% |
| 提升 1 个点，R = 2 | 17% | 30% | 51% |
| 提升 1 个点，R = 3 | 28% | 45% | 66% |
| 提升 2 个点，R = 1 | 40% | 57% | 76% |
| 提升 2 个点，R = 2 | 77% | 88% | 95% |
| 提升 2 个点，R = 3 | 93% | 97% | 99% |
| 没有改进 | 0.25% | 1% | 4% |

评测 v0.0 之后，`runs/detection_rates.md` 会给出按你自己的数据估计的同一张表，可以据此调整 R 和 α。

## 记录

v0.0 是初始版本，vK.J 是第 K 轮的第 J 次提交。每次评测的结果（`1/`、`2/`……）包含 `scores.jsonl` 和 `trajectory/`。

```
runs/
├── history.jsonl              每次提交一行：版本、问题、修改、结果
├── eval_hash.txt              评测方式的哈希
├── detection_rates.md         按当前数据估计的被保留概率
├── sessions/                  proposer 会话（可选）
├── candidates/<版本>/
│   ├── harness/               这个版本的 harness 代码
│   ├── proposal.json          proposer 的提议
│   └── proposer.jsonl         proposer 的轨迹
├── train/
│   ├── selected_questions.txt 保留的题目
│   ├── v0.0/screen/1..S/      v0.0 在全部题目上的评测，用于筛选
│   └── <版本>/                在保留的题目上的评测 1..R/，以及和当前版本的比较 check.json
├── val/                       结构同 train/
└── final/                     v0.0 和最终版本在全部题目上的评测与比较
```
