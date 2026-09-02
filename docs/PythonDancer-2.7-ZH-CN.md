# PythonDancer 2.7 — 质量智能工作站

PythonDancer 2.7 在 2.6 的分轨感知、Motion Intent、独立六轴时间线、SR6 机械诊断和中英双语 GUI 基础上增加 **Quality Intelligence（质量智能）**。

目标不再只是“生成一条六轴轨迹”，而是：

```text
生成
 ↓
评分
 ↓
比较多个候选方案
 ↓
识别低分区间
 ↓
局部重新生成 / 分段合并
 ↓
机械风险投影
 ↓
再次评分
 ↓
Funscript / TCode / Intiface
```

## 1. Motion Quality Scorer

每条有效六轴轨迹都会得到 0–100 分评分：

- Rhythm alignment：动作重音与节拍对齐度
- Phrase alignment：段落/乐句边界的动作对比
- Smoothness：加速度平滑度
- Axis diversity：六轴使用多样性
- Cross-axis coherence：L0/R0、L1/R2、L2/R1 等轴间协调
- Repetition：重复模式惩罚
- Mechanical safety：SR6 机构风险
- Jerk comfort：加速度变化率舒适度
- Stem responsiveness：副轴与 bass / hi-hat / vocals / snare 等分轨特征的响应度

GUI 的 **Quality Intelligence → Motion Quality** 页面会显示总分、9 项分数和最低分时间窗。

CLI：

```bash
python -m dancer song.mp3 --cli --yes --multiaxis --quality-score
```

写出 JSON 报告：

```bash
--quality-report song-quality.json
```

## 2. Multi-Candidate Generation

一次可生成 2–8 个候选方案。内置候选包括：

- Balanced
- Expressive
- Rhythm Heavy
- Smooth Flow
- Rotation Heavy
- Deep Translation
- Accent Dense
- Experimental

候选不仅改变名称，而会改变：

- preset
- strength / gesture strength
- 独立轴关键帧密度
- accent threshold
- pose / velocity budget
- Motion Intent bias

生成完成后自动按总分排序。

CLI：

```bash
--quality-candidates 6
```

默认会选择最高分候选；若只想比较而保留基础方案：

```bash
--keep-base-candidate
```

## 3. A/B Preview

GUI 可以分别选择 Candidate A 和 Candidate B：

- Preview A / Preview B：仅切换六轴曲线和 3D Pose 预览，不修改实际输出
- Use A / Use B：确认后才写入当前 base plan
- A/B 摘要会显示总分差和差异最大的质量指标

因此预览不会意外覆盖 Funscript / TCode 输出。

## 4. Best-section Merge

PythonDancer 会在每个已检测/手工调整的 Section 内分别评分候选：

```text
Intro   → Smooth Flow
Verse   → Balanced
Build   → Rhythm Heavy
Drop    → Expressive
Outro   → Smooth Flow
```

然后用 crossfade 将各段最高分方案合并为一个 base plan。

GUI：**Best-section merge**

CLI：

```bash
--quality-candidates 6 --merge-best-sections
```

## 5. Auto Improvement

自动优化循环：

```text
Score current plan
 ↓
Find lowest-scoring time window
 ↓
Try candidate motion only in that range
 ↓
Re-score whole track
 ↓
Accept only if score improves
 ↓
Repeat
```

默认最多 4 轮；若没有低分区间、达到目标分数、提升小于阈值或达到迭代上限则停止。

重要约束：

- 不接受降分方案
- Lock 轴在局部替换时保持原轨迹
- 使用 crossfade 处理替换边界

CLI：

```bash
--auto-improve \
--improve-iterations 4 \
--improve-target 90 \
--improve-min-gain 0.35
```

## 6. Section-level Motion Intent

每个 Section 可以单独设置：

- intensity
- aggression
- flow
- complexity
- symmetry
- rotation_bias
- translation_bias
- accent_density
- override amount

例如：

```text
Intro   flow 0.90 / aggression 0.20
Verse   balanced
Build   accent density 0.80
Drop    intensity 0.95 / aggression 0.90
Outro   flow 0.85
```

Section 边界发生变化时，Intent override 会同步新的起止时间。

GUI 支持：

- Apply section intent
- Regenerate section
- Clear section intent

CLI 可从 JSON 加载：

```bash
--section-intents section-intents.json
```

示例：

```json
{
  "section_intents": [
    {
      "start": 30.0,
      "end": 45.0,
      "label": "drop",
      "amount": 1.0,
      "blend_seconds": 0.35,
      "intent": {
        "intensity": 0.95,
        "aggression": 0.90,
        "flow": 0.35,
        "complexity": 0.78,
        "symmetry": 0.30,
        "rotation_bias": 0.72,
        "translation_bias": 0.80,
        "accent_density": 0.92
      }
    }
  ]
}
```

## 7. Mechanical Risk / Singularity Scoring

2.6 的 SR6 solver 主要判断 reachable / unreachable。

2.7 增加：

- max servo angle
- servo margin
- linkage finite-difference sensitivity
- singularity risk
- mean / peak mechanical risk
- unsafe ratio
- singularity ratio
- first unsafe timestamp

这些指标进入 Motion Quality 的 Mechanical Safety 分数。

SR6 模型仍为**诊断与规划安全层**，不会绕过 TCode 固件直接输出舵机 PWM。

## 8. Nearest-safe-pose Projection

如果目标姿态风险超过阈值：

1. 先从目标姿态向 neutral 做二分搜索；
2. 找到安全边界；
3. 再逐轴 coordinate descent 尽可能靠回目标姿态；
4. 重新执行 speed / acceleration / jerk optimizer；
5. 再做最终机械安全投影。

因此它不是简单 clamp 某一个轴。

GUI 可调：

- Nearest-safe-pose projection
- Maximum risk
- Servo limit
- Singularity sensitivity

CLI：

```bash
--mechanical-projection \
--mechanical-max-risk 0.82 \
--servo-limit-deg 88 \
--singularity-sensitivity 2.5
```

禁用用于 A/B：

```bash
--no-mechanical-projection
```

## 9. `.pdance` schema 3

2.7 项目文件会保存：

- 上一份 QualityReport
- Section-level Intent overrides
- 机械投影参数
- 候选方案与候选轨迹
- Candidate A / B 选择
- Auto Improvement 参数和历史
- 2.6 的语言、SR6 geometry、Calibration、Gesture、Curve、Safety、Device 等状态

Schema 1 和 Schema 2 继续可读。

## 10. 中文 GUI

2.7 继续支持：

```text
Language
├─ 简体中文
└─ English
```

Quality Intelligence 页的评分、候选、A/B、自动优化、Section Intent、机械投影以及动态状态信息都有简体中文映射。

内部 token 不翻译，例如：

```text
balanced
forward
L0 / L1 / L2 / R0 / R1 / R2
TCode protocol data
```

因此切换界面语言不会改变生成结果。

## 11. 输出

标准输出仍是：

```text
scene.funscript        L0
scene.surge.funscript  L1
scene.sway.funscript   L2
scene.twist.funscript  R0
scene.roll.funscript   R1
scene.pitch.funscript  R2
scene.motion.json      manifest 1.5
```

质量报告、Section Intent、机械诊断和候选摘要会作为 metadata / project state 保存；标准 Funscript position 仍保持规范化 0–100。

## 12. 安全说明

机械风险模型和 nearest-safe projection 是软件安全辅助，不替代：

- 设备固件限制
- 真实 SR6 geometry/calibration
- Emergency STOP
- 电源断开能力
- 首次连接时的低速单轴测试

使用新设备配置时仍建议先使用保守范围和低速测试。
