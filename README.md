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
   输入：初始 harness、训练集、验证集、proposer、
         轮数上限 K、每轮提交上限 J
   初始化：current ← 初始 harness             ▷ current：当前保留的 harness
           在训练集和验证集上评测 current

   for k = 1 … K:                             ▷ 新的一轮，新的会话
       candidate ← current 的副本             ▷ candidate：本轮要修改的候选 harness
       for j = 1 … J:                         ▷ 版本 vk.j
           proposer 修改 candidate            ▷ 接续会话，知道上次为何没通过
           if 训练集上没有显著优于 current:   ▷ 训练集检查
               continue                       ▷ 下次接着改 candidate
           if 验证集上没有显著优于 current:   ▷ 验证集检查
               continue
           current ← candidate                ▷ 保留
           break
       if 本轮没有保留:
           break
   return current
   ```
4. 运行 `python <harness-evolve 目录>/evolve.py final`，在 test set 上比较最终的 harness 和初始 harness。之后不能再继续优化。

## 检查

训练集检查和验证集检查都用单侧精确 McNemar 检验，逐题比较当前版本 C 和候选 N。记 $c$ 为变对（C 错 N 对）的题数，$b$ 为变错（C 对 N 错）的题数，$n = b + c$：

$$
p = \sum_{i=c}^{n} \binom{n}{i} \left(\frac{1}{2}\right)^{n}
$$

$p < \alpha$ 时通过，$\alpha$ 在 `evolve.json` 中设置。

## 记录

v0.0 是初始版本，vK.J 是第 K 轮的第 J 次提交。

```
runs/
├── history.jsonl          每次提交一行：版本、问题、修改、结果
├── eval_hash.txt          评测方式的哈希
├── sessions/              proposer 会话（可选）
├── candidates/<版本>/
│   ├── harness/           这个版本的 harness 代码
│   ├── proposal.json      proposer 的提议
│   └── proposer.jsonl     proposer 的轨迹
├── train/<版本>/          训练集结果：check.json、scores.jsonl、trajectory/
├── val/<版本>/            验证集结果：check.json、scores.jsonl、trajectory/
└── test/<版本>/           测试集结果（final）
```
