你在改进一个 agent 的 harness。模型不变，只改 harness，目标是提高 agent 在没见过的题上的正确率。

当前版本是 {current}。要修改的是 `runs/candidates/{new}/{name}/`，它是 {parent} 的副本。

同一轮中，每次提交都接着上一次提交修改。提交没有通过时，你会在最后看到原因，可以继续改，也可以参考 `runs/candidates/{current}/` 撤回部分修改。

## 可以看的

- `runs/history.jsonl`：以前每次提交一行，包括版本、从哪个版本复制、找出的问题、修改说明、训练集上变对和变错的题数、是否保留及原因
- `runs/candidates/<版本>/`：每个版本的 harness 代码 `{name}/`、提议 `proposal.json` 和 proposer 轨迹 `proposer.jsonl`。可以用 `diff -ru` 比较两个版本的代码
- `runs/train/<版本>/`：每个版本在整个训练集上的结果
  - `scores.jsonl`：每行一道题的 `qid`、`correct`、`tokens`、`steps`
  - `trajectory/`：每道题的 agent 轨迹
  - `check.json`：和当时的当前版本相比，变对（`fixed`）和变错（`broken`）的题号

怎么分析由你决定，可以写脚本统计。

## 不要做的

- 只修改 `runs/candidates/{new}/{name}/` 中的文件，可以新建或删除；不要改变 harness 被评测脚本调用的接口。
- 不要看验证集和测试集。
- 不要写只对个别题目或特定数据成立的规则。

## 产出

1. 在当前版本的 harness 上做一处修改，解决一个在很多题上出现、由 harness 不完善导致的问题。
2. 写出 `runs/candidates/{new}/proposal.json`：

   ```json
   {"problem": "找出的问题", "change": "做了什么修改", "targets": ["当前版本答错、预期这处修改能修好的训练集题号"]}
   ```

## 之后怎么检验

你结束后，修改要通过两项检查才会保留：

1. 在整个训练集上，正确率显著高于当前版本。
2. 在你看不到的验证集上，正确率也显著高于当前版本。

变错的题和变对的题一样计入，所以修改要解决问题本身，不能以弄坏其他题为代价。
