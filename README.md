# harness-evolve

harness-evolve 是一个极简的 harness 改进循环。

## 组成

- **`evolve.py`**：控制流程的 Python 脚本
- **`proposer.md`**：优化 harness 的 meta agent 的 prompt

## 流程

1. 把评测数据集分为三份：
   1. train set（训练集）：用于分析错误案例以便改进 harness。
   2. validation set（验证集）：用于判断改进是否真实有效。
   3. test set（测试集）：用于确认最终效果。
2. 按[规范](SPEC.md)提供初始 harness 文件夹和 `eval.py`：
   1. 初始 harness 文件夹：包含所有待优化的 harness 代码。
   2. 评测脚本：在评测数据集上评测 harness，保存完整轨迹并计算得分和成本。
3. 运行 `evolve.py`（K、J 在配置中设定）：

   ```
   Input:  initial harness, train set, validation set, proposer,
           max rounds K, max tries per round J
   Init:   current ← initial harness
           evaluate current on train set and validation set

   for k = 1 … K:
       for j = 1 … J:                                ▷ version vk.j
           proposer reads history and current's train trajectories,
               edits current into candidate, and lists targets
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

4. 在 test set 上比较最终的 harness 和初始 harness。

## 验证集检查

验证集上的正确率提升，可能源于 proposer 的修改，也可能是偶然波动。为了检验提升是否显著，我们采用单侧精确 McNemar 检验，在验证集上逐题比较当前版本 C 和修改后的版本 N。

记 $c$ 为变对（C 答错、N 答对）的题数，$b$ 为变错（C 答对、N 答错）的题数，$n = b + c$，那么假如修改无效，仍然出现至少 $c$ 道题变对的概率为：

$$
p = \sum_{i=c}^{n} \binom{n}{i} \left(\frac{1}{2}\right)^{n}
$$

$p < 0.05$ 表示这个结果很难用偶然解释，因此认为修改有效，予以保留；否则撤销。

token 消耗和步数只做记录，不参与判断。

## 记录

每次尝试都有一个版本号 vK.J，表示第 K 轮的第 J 次尝试，v0.0 是初始版本。只有修改被保留，才进入下一轮。

- **git** 保存每次尝试的代码，以版本号为标签。当前分支只包含被保留的版本，没有保留的尝试通过标签访问，例如 `git diff v1.1 v2.1`。
- **runs/** 保存进度、得分和轨迹。这些文件由程序生成，不提交到 git。

```
runs/
├── history.jsonl          进度：每次尝试一行（版本、基于哪个版本、问题、修改、是否保留及原因）
├── v0.0/
│   ├── scores/
│   │   ├── val.jsonl
│   │   └── train.jsonl
│   └── trajectory/
│       ├── val/
│       └── train/
└── v1.1/
    ├── proposal.json      proposer 的产出：问题、修改说明、targets
    ├── proposer.jsonl     proposer 的轨迹
    ├── check.json         两项检查的结论
    ├── scores/            得分：每行一道题的 correct、tokens、steps
    │   ├── targets.jsonl
    │   ├── val.jsonl
    │   └── train.jsonl
    └── trajectory/        agent 轨迹：每道题一个文件
        ├── targets/
        ├── val/
        └── train/
```

`scores/` 和 `trajectory/` 一一对应，按流程顺序有三部分：`targets` 是训练集检查时重新运行的错题，`val` 是验证集检查，`train` 是通过后的整个训练集。某一步没有通过，之后的部分就不会生成。

## 使用

1. 安装 pi：`npm install -g @earendil-works/pi-coding-agent`，并配置好模型的 API key。
2. 按 [SPEC.md](SPEC.md) 准备项目：数据集、harness 文件夹和 `eval.py`。把 `runs/` 加入 `.gitignore`，在专用分支上提交。
3. 在 `evolve.py` 开头填写配置。
4. 在项目根目录运行 `python <harness-evolve 目录>/evolve.py`。中途停止后再次运行，会丢弃没有完成的那次尝试，从它重新开始。
