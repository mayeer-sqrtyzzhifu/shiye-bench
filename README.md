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

## 先读什么

- `docs/findings.md` —— **发现登记表**：benchmark 提过哪些问题、改没改、验证没验证
- `docs/reproduce.md` —— **复现指南**：文档里每个数字对应哪条命令
- `docs/measurement.md` —— **测量模型**：误差多大、什么结论允许下
- `docs/review-prompt.md` —— 第一轮外部 review 提示词
- `docs/review-prompt-2.md` —— **第二轮 review 提示词**：验证修复是否成立
- `HANDOFF.md` —— **交接主文档**：两个项目的现状、改进记录、欠账、怎么跑

## 六个维度

| 维度 | 看什么 |
|---|---|
| 单轮 | 长度、问句率、二段式、语气词开头、规则命中 |
| 弧 | 峰值后回落、卡带、复读、断崖 |
| 记忆 | 命中、编造、指代理解、诚实弃答 |
| 危机 | 是否识别 + 是否给资源 |
| 变形 | 判据自检：换个说法还认不认得 |
| 语气 | 口语/书面密度、标点画像（与真人语料的 z 距离；需先跑 run_personas） |

「语气」不是语音、不涉音频，量的是**读起来像不像人写的**。
- `HANDOFF.md` —— 设计初衷、与现实的偏差、能测什么/不能测什么
- `docs/worklog.md` —— 逐轮的完整过程（包括走过的弯路）

## 一条命令跑完

```powershell
python bench.py --provider real --repeat 2   # 全维度，跑两遍取中位
python bench.py --provider fake             # 零成本冒烟
```

输出 `reports/summary-*.md`：一张总览表 + 每维测试的产品版本（shiye git sha）。

> 单次运行有 ±1 的波动（实测记忆维度在 3/4 与 2/4 之间来回），
> 要看"是否真的变了"至少跑两遍。

## 分维度跑

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

# 4) 已知组校准：同一批用例跑历代人格，验证判据能不能复现已知好坏
python scripts/extract_personas.py     # 从 shiye git 历史取 5 版人格
python run_personas.py                 # 通用用例对照
python run_probes.py                   # 定向探针（问 agent 自己的生活）

# 5) 自检：指标是不是活的、危机路径对不对
python run_metamorphic.py              # 7 组变形，指标不动就报错
python run_crisis.py --provider real   # 危机用例

# 6) 改完判据后重算，不必重跑模型
python scripts/reanalyze.py
```

> HuggingFace 直连不通时用镜像：`$env:HF_ENDPOINT = "https://hf-mirror.com"`
