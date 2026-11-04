# harness-evolve

harness-evolve 是一个极简的 harness 改进循环：模型固定，反复修改 prompt、工具等，只保留经统计检验有效的修改。

## 组成

- **`evolve.py`**：控制流程的 Python 脚本，负责运行评测、调用 proposer、检查、提交或撤销。
- **`proposer.md`**：交给 proposer 的 prompt。proposer 由 [pi](https://github.com/earendil-works/pi) 以非交互模式运行，只给它读、搜索和编辑文件的工具，没有 bash。

## 流程

1. 由人把评测数据集分为三份：
   - **train set**（训练集）：用于分析错误案例，以便改进 harness。
   - **validation set**（验证集）：用来判断修改是否有效。
   - **test set**（测试集）：优化过程中不使用，全部结束后由人确认最终效果。
2. `evolve.py` 运行初始版本 v0.0，得到训练集和验证集上的结果，然后循环：

   ```
   for 每一轮:
       for 本轮的每次尝试:
           1. proposer 阅读以前各次尝试的记录和当前版本在训练集上的轨迹，修改 harness
           2. 训练集检查：重新运行 proposer 列出的错题，一道都没变对，撤销，再试一次
           3. 验证集检查：验证集上的正确率没有显著高于当前版本，撤销，再试一次
           4. 两项都通过：保留修改，作为新的当前版本；在整个训练集上运行它，供下一轮分析；进入下一轮
       如果本轮所有尝试都没有通过，停止
   ```

3. 由人在测试集上比较最终的当前版本和 v0.0。

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
2. 把数据集分成训练集、验证集和测试集。来源相同的题（例如同一个视频的多道题）放在同一份里。
3. 把 `evolve.py` 和 `proposer.md` 放到项目根目录，填写 `evolve.py` 开头的配置。评测命令要按配置中说明的格式输出结果。
4. 在专用分支上提交当前代码，把 `runs/` 加入 `.gitignore`。
5. 运行 `python evolve.py`。中途停止后再次运行，会从上次的进度继续。
