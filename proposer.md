你在改进一个 agent 的 harness。模型不变，只改 harness，目标是提高 agent 在没见过的题上的正确率。

当前版本是 {current}，本次尝试的版本是 {new}。

## 可以看的

- harness 文件夹：`{harness}`
- git 历史：每次尝试都是一个提交，标签为版本号 vK.J。当前分支只包含被保留的版本，没有保留的尝试只能通过标签访问。可以用 `git tag`、`git log`、`git diff <版本> <版本>`、`git show <版本>:<文件>` 查看。
- `runs/history.jsonl`：每次尝试一行，包括基于哪个版本、找出的问题、修改说明、是否保留及原因
- `runs/<版本>/proposal.json`：每次尝试找出的问题、修改说明和 targets
- `runs/<版本>/proposer.jsonl`：以前 proposer 的轨迹
- `runs/<版本>/scores/targets.jsonl`、`train.jsonl`：训练集上每道题的得分，每行包括 `qid`、`correct`、`tokens`、`steps`
- `runs/<版本>/trajectory/targets/`、`train/`：训练集上每道题的 agent 轨迹

`targets` 是那次尝试重新运行它列出的错题的结果；`train` 是整个训练集的结果，只有被保留的版本才有。怎么分析由你决定，可以写脚本统计。

## 不要做的

- 不要看验证集和测试集：`runs/*/check.json`、`runs/*/scores/val.jsonl`、`runs/*/trajectory/val/`，以及数据集中的 val、test 部分。
- 只修改 harness 文件夹内的文件，可以新建或删除，文件夹以外的改动会被丢弃；不要改变 harness 被评测脚本调用的接口。
- 不要运行评测，也不要提交或打标签，这些由流程完成。
- 不要切换分支或 checkout 其他版本，查看旧版本用 `git show`、`git diff`。
- 不要写只对个别题目或特定数据成立的规则。

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
