你在改进一个 agent 的 harness。模型不变，只改 harness，目标是提高 agent 在没见过的题上的正确率。

当前版本是 {current}，本次尝试的版本是 {new}。

## 可以读的

- harness 文件：{harness}
- `runs/history.jsonl`：以前每次尝试一行，包括基于哪个版本、找出的问题、修改说明、是否保留及原因
- `runs/<版本>/change.diff`：每次尝试的代码改动，包括没有保留的
- `runs/<版本>/eval_train/`：被保留的版本在训练集上的结果。`results.jsonl` 每行一道题（`qid`、`correct`、`tokens`、`steps`），`traces/` 中是每道题的轨迹

怎么分析由你决定。

## 不要做的

- 不要读 `eval_val/`、`check_val.json` 和测试集。
- 只修改 harness 文件，不新建或删除文件。
- 不要写只对个别题目或特定数据成立的规则。
- 不要重复以前没有通过的问题和改法。

## 产出

1. 在当前版本的 harness 上做一处修改，解决一个在很多题上出现、由 harness 不完善导致的问题。
2. 写出 `runs/{new}/proposal.json`：

   ```json
   {"problem": "找出的问题", "change": "做了什么修改", "targets": ["预期这处修改能修好的训练集错题题号"]}
   ```

## 之后怎么检验

你结束后，修改要通过两项检查才会保留：

1. 重新运行 `targets` 中的题，至少一道变对。
2. 在你看不到的验证集上，正确率显著高于当前版本。

所以修改要解决问题本身，而不只是修好你读过的那几道题。
