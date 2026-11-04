# harness-evolve

harness-evolve 是一个极简的 harness 改进循环：模型固定，反复修改 prompt、工具等，只保留经统计检验有效的修改。

## 组成

- **`evolve.py`**：控制流程的 Python 脚本
- **`proposer.md`**：优化 harness 的 meta agent 的 prompt

## 流程

1. 由人把评测数据集分为三份：
   - **train set**（训练集）：用于分析错误案例，以便改进 harness。
   - **validation set**（验证集）：用来判断修改是否有效。
   - **test set**（测试集）：优化过程中不使用，全部结束后由人确认最终效果。

   来源相同的题（例如同一个视频的多道题）放在同一份里。
2. 由人定义评测脚本和 harness 文件，填进 `evolve.py` 开头的配置：
   - **评测脚本**：接受 `--split train/val`、`--out <目录>`，以及可选的 `--qids <逗号分隔的题号>`（只运行这些题）。输出 `<目录>/results.jsonl`，每行一道题：`{"qid": ..., "correct": 0 或 1, "tokens": token 消耗, "steps": agent 步数}`；以及 `<目录>/traces/`，每道题一个轨迹文件，文件名包含题号。
   - **harness 文件**：允许 proposer 修改的文件，用 glob 列出，例如 `agent/prompts/*.md`。评测脚本、数据集不能放在里面。
3. `evolve.py` 运行初始版本 v0.0，得到训练集和验证集上的结果，然后循环：

   ```
   for 每一轮:
       for 本轮的每次尝试:
           1. proposer 阅读以前各次尝试的记录和当前版本在训练集上的轨迹，修改 harness
           2. 训练集检查：重新运行 proposer 列出的错题，一道都没变对，撤销，再试一次
           3. 验证集检查：验证集上的正确率没有显著高于当前版本，撤销，再试一次
           4. 两项都通过：保留修改，作为新的当前版本；在整个训练集上运行它，供下一轮分析；进入下一轮
       如果本轮所有尝试都没有通过，停止
   ```

4. 由人在测试集上比较最终的当前版本和 v0.0。

## 验证集检查

验证集上的正确率提升，可能源于 proposer 的修改，也可能是偶然波动。为了检验提升是否显著，我们采用单侧精确 McNemar 检验，在验证集上逐题比较当前版本 C 和修改后的版本 N。

记 $c$ 为变对（C 答错、N 答对）的题数，$b$ 为变错（C 答对、N 答错）的题数，$n = b + c$，那么假如修改无效，仍然出现至少 $c$ 道题变对的概率为：

$$
p = \sum_{i=c}^{n} \binom{n}{i} \left(\frac{1}{2}\right)^{n}
$$

$p < 0.05$ 表示这个结果很难用偶然解释，因此认为修改有效，予以保留；否则撤销。

token 消耗和步数只做记录，不参与判断。

## 记录

每次尝试都有一个版本号 vK.J，表示第 K 轮的第 J 次尝试（J 从 0 开始），v0.0 是初始版本。只有修改被保留，才进入下一轮。

- **git** 只保存通过检查的版本，以版本号为标签，例如用 `git diff v0.0 v2.0` 查看两个版本之间的改动。
- **runs/** 保存每次尝试的记录，包括没有通过的。这些文件由程序生成，不提交到 git。

```
runs/
├── history.jsonl             每次尝试一行：基于哪个版本、问题、修改、是否保留及原因
├── v0.0/
│   ├── eval_train/           初始版本在训练集上的结果
│   └── eval_val/             初始版本在验证集上的结果
└── v1.0/
    ├── proposer_trace.jsonl  proposer 的运行轨迹
    ├── change.diff           这次尝试的代码改动
    ├── proposal.json         proposer 找出的问题、修改说明和列出的错题
    ├── eval_train_targets/   重新运行这些错题的结果
    ├── eval_val/             验证集上的结果
    ├── check_val.json        验证集检查的结果，以及平均 token 消耗和步数
    └── eval_train/           通过后，整个训练集上的结果
```

## 使用

1. 安装 pi：`npm install -g @earendil-works/pi-coding-agent`，并配置好模型的 API key。
2. 把 `evolve.py` 和 `proposer.md` 放到项目根目录，完成流程中的第 1、2 步。
3. 在专用分支上提交当前代码，把 `runs/` 加入 `.gitignore`。
4. 运行 `python evolve.py`。中途停止后再次运行，会从上次的进度继续。
