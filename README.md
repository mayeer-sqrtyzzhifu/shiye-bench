# 拾夜 · 情感陪伴质量 Benchmark

给「拾夜」这类情感陪伴 agent 做**验收**的测量工具。不是排行榜，不是人格调音器。

## 文档

| 文档 | 内容 |
|---|---|
| [HANDOFF.md](HANDOFF.md) | 交接文档：初衷、设计思路、参考工作、规划 |
| [docs/data-inventory.md](docs/data-inventory.md) | 中文情感对话数据集调研 |
| [docs/worklog.md](docs/worklog.md) | **实施记录**（每轮做了什么、结论、遗留问题） |

## 目录约定

```
cases/      会话脚本（未来）
checks/     L1 规则与标注器（未来）
judge/      L2 判据（未来）
runners/    假 provider / shiye lib（未来）
calibrate/  已知组 / 变形测试（未来）
scripts/    数据获取与分析脚本
data/       下载的语料（gitignored）
docs/       文档
```

## 快速开始

```powershell
# 1) 语料：采样 + 结构分析
python scripts/fetch_smilechat.py --count 120
python scripts/analyze_smilechat.py

# 2) 用例
python scripts/make_cases.py --count 30     # 单轮
python scripts/make_arcs.py --count 6       # 多轮情绪弧

# 3) 评测
python run.py --provider fake                 # 单轮（零成本，确定性）
python run_arcs.py --provider real            # 情绪弧
python run_memory.py --provider real          # 跨天记忆

# 4) 改完判据后重算，不必重跑模型
python scripts/reanalyze.py
```

> HuggingFace 直连不通时用镜像：`$env:HF_ENDPOINT = "https://hf-mirror.com"`
