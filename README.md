# harness-evolve

harness-evolve 是一个极简的 harness 改进循环。

## 组成

- **Proposer**：改进 harness 的 meta agent，由 pi coding agent 和系统指令 `proposer.md` 构成。
- **Process control**：驱动 Proposer 提出修改，再评估并决定是否保留的优化流程（`evolve.py`）。
- **Sandbox**：限制 Proposer 能读写的内容、防止 reward hacking 的隔离环境（`Dockerfile.pi`）。

## 流程

1. 把评测数据集分为三份：
   1. train set（训练集）：用于分析错误案例以便改进 harness。
   2. validation set（验证集）：用于判断改进是否真实有效。
   3. test set（测试集）：用于确认最终效果。
2. 配置：
   1. 按[规范](SPEC.md)提供初始 harness 文件夹：包含所有待优化的 harness 代码。
   2. 按[规范](SPEC.md)提供评测脚本 `eval.py`：在评测数据集上评测 harness，保存完整轨迹并计算得分和成本。
   3. 用 `Dockerfile.pi` 构建 proposer 运行的镜像。
   4. 按[规范](SPEC.md)在项目根目录写好配置 `evolve.json`。
3. 在项目根目录运行 `python <harness-evolve 目录>/evolve.py`：

   ```
   Input:  initial harness, train set, validation set, proposer,
           max rounds K, max tries per round J
   Init:   current ← initial harness
           evaluate current on train set and validation set

   for k = 1 … K:
       for j = 1 … J:                                ▷ version vk.j
           proposer reads history and current's train trajectories,
               edits a copy of current into candidate, and lists targets
           if candidate fails user check:            ▷ optional, e.g. edit scope
               continue
           if no target is fixed:                    ▷ train check
               continue
           if candidate is not significantly better
                   than current on validation set:   ▷ validation check
               continue
           current ← candidate                       ▷ keep
           evaluate current on train set             ▷ for next round
           break
       if no candidate is kept in round k:
           break
   return current
   ```

4. 运行 `python <harness-evolve 目录>/evolve.py final`，在 test set 上比较最终的 harness 和初始 harness。之后不能再继续优化。

## 验证集检查

验证集上的正确率提升，可能源于 proposer 的修改，也可能是偶然波动。为了检验提升是否显著，我们采用单侧精确 McNemar 检验，在验证集上逐题比较当前版本 C 和修改后的版本 N。

记 $c$ 为变对（C 答错、N 答对）的题数，$b$ 为变错（C 答对、N 答错）的题数，$n = b + c$，那么假如修改无效，仍然出现至少 $c$ 道题变对的概率为：

$$
p = \sum_{i=c}^{n} \binom{n}{i} \left(\frac{1}{2}\right)^{n}
$$

$p < 0.05$ 表示这个结果很难用偶然解释，因此认为修改有效，予以保留；否则撤销。

这是针对单次比较的检验。同一个验证集会被反复用来挑选候选，同一来源的题目之间也相互关联，所以整个优化过程的误报率会高于 5%，最终效果以 test set 为准。

token 消耗和步数只做记录，不参与判断。

## 记录

每次尝试都有一个版本号 vK.J，表示第 K 轮的第 J 次尝试，v0.0 是初始版本。只有修改被保留，才进入下一轮。

所有记录都在 `runs/` 中。项目中的 harness 文件夹不会被修改，最终版本的 harness 在 `runs/candidates/<版本>/` 中。

```
runs/
├── history.jsonl          进度：每次尝试一行（版本、基于哪个版本、问题、修改、是否保留及原因）
├── eval_hash.txt          评测设置的哈希：评测命令或评测文件改过时，停止运行
├── candidates/<版本>/
│   ├── harness/           这个版本的 harness 代码
│   ├── proposal.json      proposer 的产出：问题、修改说明、targets
│   └── proposer.jsonl     proposer 的轨迹
├── train/<版本>/
│   ├── check.json         训练集检查的结论
│   ├── targets/           重新运行 targets 的结果
│   ├── scores.jsonl       通过后，整个训练集的结果
│   └── trajectory/
├── val/<版本>/
│   ├── check.json         验证集检查的结论
│   ├── scores.jsonl
│   └── trajectory/
└── test/<版本>/           final 的结果
```

每个评测结果都是一个 `scores.jsonl`（每行一道题的 correct、tokens、steps）和一个 `trajectory/`（每道题一个 agent 轨迹文件）。某一步没有通过，之后的结果就不会生成。

Proposer 在沙箱中只能看到 `history.jsonl`、`candidates/` 和 `train/`，只能修改本次版本的 `candidates/<版本>/`。
