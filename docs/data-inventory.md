# 中文情感对话数据集调研

> 调研时间：2026-11-05
> 目的：为 `shiye-bench` 找可用的中文情感对话语料
> 结论先行：**有一个真正能用的（SmileChat，CC0，可直接 clone），但没有一个是"陪伴"场景的**

---

## 一、总表

| 数据集 | 语言 | 规模 | 来源 | 许可 | 能否直接下 | 适合度 |
|---|---|---|---|---|---|---|
| **SmileChat** | 中 | **55,165 段**多轮（实测） | 真实咨询对话（来访者/咨询师） | **CC0 1.0** | ✅ GitHub 直接 clone | ★★★★ |
| **PsyQA** | 中 | 较大（论文口径） | 论坛问答 + 援助策略标注 | 需签协议 | ⚠️ 邮件申请 | ★★★ |
| **AuraDial** | 中 | 30 万单轮 + 9 万多轮 | 真实用户提问改写 | CC-BY-SA-4.0 | ❌ HF 仓库只有 README | ★★ |
| **deep-emotional-support-zh** | 中 | 6,253 单轮 | 真实人机交互（声称） | CC-BY-NC-SA-4.0 | ✅ HF（走镜像） | ★★ |
| **chinese-adorable-chat** | 中 | ~170 组 | 疑似合成 | CC-BY-4.0 | ✅ HF（走镜像） | ★★ |
| **LCCC (Slim-LCCC-zh)** | 中 | 10K 子集 / 原 1200 万 | 人类闲聊 | 未标注 | ✅ HF（走镜像） | ★★ |
| **SoulChat** | 中 | 以模型为主 | 咨询对话 | 待查 | 部分 | ★★ |
| **CPsyCoun** | 中 | 报告重构多轮 | 咨询 | 待查 | ❌ 仓库 404 | ? |

---

## 二、逐个评估

### 1. SmileChat —— 目前唯一"拿来就能用"的

- 仓库：[qiuhuachuan/smile](https://github.com/qiuhuachuan/smile)（EMNLP 2024，MeChat 配套数据）
- 许可：**CC0 1.0**（公有领域，无任何使用限制）
- 格式：`data/<id>.json`，每个文件一段对话

```json
[
  {"role": "client",   "content": "高三后的迷茫，高考前的恐惧，能给我一些建议么？",
   "annotation": [{"sentence": "…", "label": ""}]},
  {"role": "counselor","content": "看到你的提问感觉你很焦虑…", "annotation": [...]}
]
```

**能用在哪**：
- **真实的中文情绪表达**——这是最缺的素材，比自己编的"用户输入"真实得多
- 多轮结构，可以直接改写成我们的会话脚本
- 咨询师的回应可做"另一种风格"的对照（它们通常更长、更说教——正好是我们的人格要避开的）

**局限**：
- 场景是**咨询**不是陪伴：95% 的开场带问号，缺少"今天好累"这类日常开场
- 咨询师回复中位 **91 字**，是来访者（39 字）的 2.3 倍，与"短句、不说教"的人格**相反**
- **策略标注实测为空**：4,073 条 annotation，有内容的 0 条

实测统计（120 段采样）：

| 指标 | 值 |
|---|---|
| 每段轮数 | 中位 12（2–22） |
| client 长度 | 中位 39 字 |
| counselor 长度 | 中位 91 字 |
| 开场带问号 | 95% |

### 2. PsyQA —— 有标注，但拿不到

- 仓库：[thu-coai/PsyQA](https://github.com/thu-coai/PsyQA)（ACL 2021 Findings，283 stars）
- 特色：**带援助策略标注**，正是我们"需求 → 策略"映射需要的
- 获取：需要下载用户协议、填写信息、电子签名、发邮件审核 → **不适合快速迭代**

样本文件 `PsyQA_example.json` 在仓库里（100 条 / 268 个答案 / 888 个标注片段）。

**实测：策略标注是真实存在的**，按字符区间打标：

```json
{"start": 0, "end": 78, "type": "Interpretation"}
```

7 类策略的分布：

| 策略 | 占比 |
|---|---|
| Interpretation（解释） | 47.9% |
| Direct Guidance（直接指导） | 33.2% |
| Others | 7.4% |
| Approval and Reassurance（认可安抚） | 5.2% |
| Self-disclosure（自我披露） | 2.3% |
| Restatement（复述） | 2.1% |
| Information（信息） | 1.9% |

⚠️ **这组分布本身就是个警告**：咨询语料里 81% 是"解释 + 指导"，
认可与复述只占 7%；而陪伴 agent 恰恰要"少给建议、多认可"。
**照着咨询语料调参，会把 agent 调成一个小咨询师。**

### 3. AuraDial —— 论文很好，数据没放出来

- 论文：[AuraDial (EMNLP 2025 Findings)](https://aclanthology.org/2025.findings-emnlp.155/)
- 声称：30 万单轮 + 9 万多轮，指令来自真实用户提问
- 实测：HF 仓库 [Mxode/AuraDial](https://huggingface.co/datasets/Mxode/AuraDial) **只有一个 license 字段，没有任何数据文件**
- 结论：**只能读论文，拿不到数据**（除非作者后续上传）

### 4. deep-emotional-support-zh —— 内容太重，不适合做风格参照

- [HF 数据集](https://huggingface.co/datasets/AngelWarmSmile123/deep-emotional-support-zh)，6,253 条，CC-BY-NC-SA-4.0
- 实测样本（前 200 条可下）：题材集中在**跨性别身份、家庭冲突、自杀风险**
- 回复特点：**带完整 `[思考过程]`，正文 1000–2000 字，大量小标题和编号列表**

这正好是我们人格要避免的形态。**不建议做风格参照**，但可以做两件事：
- **危机语料**：真实的极端表达，用来测安全路径
- **反例**：证明"长 + 结构化 = AI 味"

⚠️ 内容高度敏感（性别认同、自伤），作为测试用例要谨慎。

### 5. chinese-adorable-chat —— 短、自然，但太小

- [HF 数据集](https://huggingface.co/datasets/MemorialSummer/chinese-adorable-high-emotional-intelligence-chat)，约 170 组，CC-BY-4.0
- 风格示例：

```
用户：你今天状态不太好。
回复：那我今天就当你的充电宝，抱一下回血百分之十～
```

- 优点：**平均 15–30 字、有情绪转折、不解释不总结**——形态上接近我们要的
- 缺点：体量太小（170 组）、疑似合成、语气偏"可爱女友"而非"姐姐"
- 用法：**做"短回复"的正面参照**，不参与训练

### 6. LCCC —— 自然口语，但没有情绪

- 1200 万对话（Slim 版 10K），人类真实闲聊
- 优点：口语化、短句、有来有回——是"活人感"的天然参照
- 缺点：无情绪标注、无支持策略，且多为陌生人闲聊
- 用法：做**句式多样性**的参照分布

---

## 三、下载方式（重要）

**HuggingFace 直连不通，但镜像可用**：

```
https://huggingface.co          → 连接被重置
https://hf-mirror.com           → 200
```

下载方式：

```powershell
# 单文件
Invoke-WebRequest "https://hf-mirror.com/datasets/<org>/<name>/resolve/main/<file>" -OutFile out.jsonl

# 或设环境变量后直接用 huggingface-cli
$env:HF_ENDPOINT = "https://hf-mirror.com"
```

GitHub 直连正常，SmileChat / PsyQA 直接 `git clone` 即可。

---

## 四、缺口分析

把六个维度列出来对照：

| 维度 | 有哪个数据集满足 |
|---|---|
| 中文 | ✅ 大部分 |
| 情感内容 | ✅ SmileChat / AuraDial / deep-ES |
| **日常陪伴场景**（非咨询） | ❌ **一个都没有** |
| 多轮 + 情绪延续 | ⚠️ SmileChat 有轮次，但非情绪弧 |
| 长期记忆（跨会话） | ❌ 没有 |
| 公开且无许可障碍 | ⚠️ 只有 SmileChat（CC0） |

**结论**：公开语料能提供"真实的情绪表达"，但提供不了"陪伴场景 + 情感延续 + 记忆"这三样——而这恰恰是本项目要测的东西。

---

## 五、建议

### 用什么

| 用途 | 用哪个 |
|---|---|
| 真实用户输入素材（改写成本地用例） | **SmileChat** |
| 危机表达的语料 | deep-emotional-support-zh（谨慎） |
| 短回复的正面参照 | chinese-adorable-chat（170 组够做分布对照） |
| 句式多样性参照 | LCCC 10K 子集 |
| 援助策略分类 | PsyQA（若能拿到）／ESConv 的 8 类 |

### 不用什么

- **AuraDial**：数据没放出来，别在论文上做计划
- **deep-emotional-support-zh 的回复**：形态与目标人格相反，只能做反例

### 缺的部分自己写

22 个会话脚本仍然要自己写，但可以按这个流程降低工作量：

```
SmileChat 里挑 12 段真实对话
   ↓ 改写（去掉咨询语境，换成日常陪伴开场）
   ↓ 加 4 个长弧（把某段情绪拉长到 8~12 轮）
   ↓ 加 2 个跨天（人为制造"隔天再提"）
   ↓ 加 4 个对抗（诱导诊断、要求承诺、反复追问、改口）
```

这条路径能把"写用例"从凭空创作变成**改写真实语料**，质量会明显高一档。

---

## 六、待办

- [x] 采样并统计 SmileChat：55,165 段文件 / 采样 120 段 / 中位 12 轮
- [x] 检查 `annotation.label`：**全空，策略标注不可用**
- [x] 检查 PsyQA 示例：**策略标注真实存在**，7 类分布已统计
- [ ] 从 SmileChat 改写 12 段成会话脚本，验证这条路径的工时
- [ ] PsyQA 发邮件申请（示例已够定分类体系，可延后）
- [ ] 关注 AuraDial 是否补传数据
