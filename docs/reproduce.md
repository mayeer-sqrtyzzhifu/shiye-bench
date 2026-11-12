# 复现指南

这个文件回答一个问题：**我在文档里看到的每个数字，怎么自己跑出来。**

原则：每条结论都写明「命令 → 会看到什么 → 这一步在验证什么」。
跑不通的命令等于没有。

---

## 0. 环境

```powershell
# 需要 shiye 与 shiye-bench 是同级目录
#   <parent>/shiye
#   <parent>/shiye-bench
# 并且 shiye 的依赖已装好（benchmark 直接 import 它的包）
```

benchmark 通过 `runners/shiye_lib.py` 把 `../shiye/src` 加进 `sys.path`，
再用 `SHIYE_HOME` 指向临时目录，**不会碰你正在用的数据库**。

---

## 1. 三十秒自检（零成本）

```powershell
python -m pytest tests -q      # 应看到 183 passed
python run_metamorphic.py      # 应看到 8 个变形全部 PASS
```

变形测试证明**每个指标都是活的**：对合格回复做已知劣化，指标必须朝预期方向动。
它是唯一不需要调用模型的验证。

---

## 2. 全维度总览（约 10 分钟，真实模型）

```powershell
python bench.py --provider real --repeat 1
```

产出 `reports/summary-real-<时间>.md`，一张表 + 被测项目的 git sha。

最近一次（shiye `4355a9b`，60 条单轮）：

```
单轮  长度 35.6｜二段式（开场）13/60｜规则命中 3
弧    回落 5/5｜卡带 0%｜复读 0%｜断崖 0%
记忆  3/4（CI 30–95%）｜编造 0
危机  5/5
```

> **注意**：单次运行有 ±1 的波动。要看「有没有变」至少跑两遍，
> 并看区间是否重叠 —— 见 `findings.md` 最后一节。

---

## 3. 分维度：每条结论对应哪条命令

### 3.1 公式化程度

```powershell
python run.py --provider real --limit 60
```

看报告里的三列：**语气词开头 / 二段式 / 问句率**。

* 二段式 = 「接一句 + 问一句」，实现见 `checks/rules.py::two_part_template`
* 已知组对照（5 版历史人格）：

```powershell
python scripts/extract_personas.py     # 从 shiye 的 git 历史取 5 版人格
python run_personas.py --limit 12
```

预期：p3（日系口吻）语气词开头 10–12/12，其余版本 1–4/12。

> 这里有个坑：`run_personas` 比较的是**互不相干的用户开场**，
> 所以不能套用「对话内比例」规则（见 `findings.md` B1/B2）。

### 3.2 语气自然度（和真人比）

```powershell
python run_voice.py
```

拿 SmileChat 的真人咨询师/来访者回复当参照，量口语密度、书面密度、问号密度。

预期：p3 的口语密度是真人的 15 倍左右；所有版本的书面密度都是 0.00。

> ⚠️ 报告里的「离真人距离」**不要横向比**（两种参照离散度不同），
> 只看原始密度。

### 3.3 情绪弧（多轮）

```powershell
python run_arcs.py --provider real --limit 8
```

六个指标：峰值后回落 / 卡带 / 复读 / 断崖 / 抢跑 / 多样性，
外加**提问率**和**二段式（整体/开场）**。

预期：回落 5–8/8，卡带与断崖 0%，二段式开场约 50%、整体约 15–20%。

> 改完判据想重算历史运行、不重跑模型：

```powershell
python scripts/reanalyze.py                       # 最新的单轮运行
python scripts/reanalyze.py data/runs/arcs-xxx.json   # 指定的弧运行
```

### 3.4 跨天记忆

```powershell
python run_memory.py --provider real
python run_memory.py --provider real --forget    # 变形：埋点后清空记忆库
```

预期：正常 2–3/4 命中、编造 0；`--forget` 后命中 0/4，且多半诚实弃答。

> `--forget` 是记忆维度的变形测试：**命中率归零才说明命中真的来自记忆**。

### 3.5 危机路径

```powershell
python run_crisis.py --provider real
```

预期：5/5。报告里有「识别风险」一列 —— 如果某条 FAIL 而识别风险是 0，
问题在**检测**不在生成。

### 3.6 定向探针（人格差异）

```powershell
python run_probes.py              # 6 条探针 × 5 版人格
```

预期：p3/p4 编造自己的生活 4/6，p5（当前）0/6。

### 3.7 判据可靠性

```powershell
python run_judge_questions.py             # 三种问法 × 三组数据，选出不含人设措辞的问法
python run_judge_personas.py --limit 12   # 用选定的问法给历代人格打分
python run_judge.py --repeat 2            # 重测一致 + 已知负例
python run_judge_groups.py                # 在有标准答案的维度上对比规则与判官
python run_judge_real.py --limit 40       # 拾夜 vs 真人咨询师
```

预期：

* `run_judge`：κ 1.00，硬负例特异度 83–92%
* `run_judge_groups`：规则 p5 0/6、判官 0/6；p4 规则 5/6、判官 6/6
* `run_judge_real`：拾夜 90% / 咨询师 28%（合规问法），
  拾夜 62% / 咨询师 5%（中立问法）

---

## 4. 数据从哪来

| 数据 | 来源 | 许可 | 复现命令 |
|---|---|---|---|
| SmileChat（400 段） | HuggingFace 镜像 | CC0 | `python scripts/fetch_smilechat.py --count 400` |
| 单轮用例 60 条 | 从上面抽样 | — | `python scripts/make_cases.py --count 60` |
| 弧用例 8 段 | 从上面抽样 | — | `python scripts/make_arcs.py --count 8` |
| 5 版人格 | shiye 的 git 历史 | — | `python scripts/extract_personas.py` |

`data/` 与 `reports/` 都在 `.gitignore` 里 —— 仓库只存代码和文档，
产物靠命令重新生成。

---

## 5. 已知跑不通 / 不可靠的地方

| 现象 | 原因 | 怎么办 |
|---|---|---|
| 单轮指标两次差 ±1 | 模型非确定性 | 用 `--repeat 2`，看区间 |
| 报告里出现 `⚠️` | 模型调用失败 | 已加重试 3 次；仍失败会标「生成失败」 |
| 记忆命中 2/4 与 3/4 来回跳 | 4 条用例太少 | 只看「编造 0」这类稳定指标 |
| 判官有时解析失败 | `max_tokens` 不够 | 已提到 400；仍失败会单独列出 |
| `run_voice` 没有结果 | 依赖 `run_personas` 的产物 | 先跑 `run_personas.py` |

---

## 6. 一句话

想验证某个结论，先看 `docs/findings.md` 里对应的编号，
再回到这里找那条命令；两边对不上，说明文档该更新了。
