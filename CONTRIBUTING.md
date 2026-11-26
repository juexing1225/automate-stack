# 贡献指南

本仓库的协作流程只有一份权威说明：

- 进仓先读 [`AGENTS.md`](AGENTS.md)（命令与铁律）；
- 完整细则见 [`docs/COLLAB.md`](docs/COLLAB.md)（领取、门禁、返工、独立验收）；
- 整体设计见 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)，该文件受保护，修改需人放行。

基本流程：

```bash
python3 scripts/collab.py claim <Issue号> --member <你的ID>
python3 scripts/collab.py gate --profile fast
python3 scripts/collab.py submit --member <你的ID>
```

验收由未参与创作的成员执行；作者不得自审。详细格式与失败处理见 `docs/COLLAB.md`，不要在本文件另立一套规则。
