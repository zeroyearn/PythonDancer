# PythonDancer 2.6 中文 GUI 与 Generation Quality

PythonDancer 2.6 的六轴工作站支持简体中文与 English 运行时切换。语言只影响显示层，不会改变 `balanced`、`choreography`、`L0/R0` 等内部控制 token，因此切换语言不会改变生成结果。

## 中文界面

启动六轴 GUI：

```bash
python -m dancer scene.mp4 --multiaxis
```

顶部菜单提供：

```text
语言
├─ 简体中文
└─ English
```

默认规则：

- 中文系统默认简体中文；
- 英文系统默认 English；
- 其他系统语言在本 fork 默认简体中文；
- 可设置环境变量 `PYTHONDANCER_LANG=en` 或 `PYTHONDANCER_LANG=zh_CN` 覆盖默认语言；
- `.pdance` 会保存当前工作站语言。

翻译范围包括主工作站卡片、菜单、页签、Timeline Canvas 文本、状态栏、MessageBox、设备/校准信息、Generation Quality、Motion Intent 和 SR6 机械诊断。生成引擎、文件格式和设备协议始终使用稳定的内部英文 token。

## 2.6 生成主链

```text
音频 / 视频
    ↓
Beat / Bar / Phrase + Stems
    ↓
Motion Intent
    ↓
Reference Style / Profile
    ↓
L0 主规划器 + 五个副轴独立音乐时间线
    ↓
Gesture Timeline
    ↓
6D Pose / Velocity / Acceleration / Jerk Optimizer
    ↓
Workspace 编辑 / Smart Limit
    ↓
SR6 firmware-model 机械可达性诊断
    ↓
Funscript / TCode / Intiface
```

## Motion Intent

连续 0..1 空间：

- intensity：整体动作强度；
- aggression：冲击性；
- flow：流动性；
- complexity：复杂度；
- symmetry：对称性；
- rotation bias：旋转轴偏好；
- translation bias：平移轴偏好；
- accent density：重音动作密度。

GUI 可将音频推断值与手动值按 `Override amount` 0..1 混合。

## 独立六轴时间线

2.6 不再强制五个副轴复用 L0 的关键帧时间：

```text
L1 surge   ← bass
L2 sway    ← hi-hat / high band
R0 twist   ← vocal pitch motion
R1 roll    ← snare / drum onset
R2 pitch   ← vocal / harmonic
```

`Axis density` 控制关键帧密度，`Accent threshold` 决定额外细分触发阈值。

## Calibration → Optimizer

加载设备 calibration JSON 后，生成阶段会直接使用该设备每轴的：

- `max_speed`
- `max_acceleration`
- `max_jerk`

作为 6D optimizer 的动态限制。设备的 min/max/neutral/invert 仍只在 live output 映射阶段应用，因此 canonical `.funscript` 保持标准 0..100。

安全单轴测试使用保守的逐轴 ±5% 验证序列；它不是自动端点探测，也不会尝试撞机械限位。

## SR6 firmware-model 机械诊断

3D Pose 页面会同时运行 SR6 linkage solver，显示：

- 当前姿态 reachable / unreachable；
- 四个主 linkage + 两个 pitch linkage 的角度；
- R0 twist；
- 最大舵机角；
- 整条轨迹不可达比例与首个不可达时间。

可加载独立 SR6 geometry JSON。机械求解仅用于模拟、诊断和导出 metadata；真实设备仍接收 TCode，最终 servo PWM/校准由设备 firmware 负责。

## Latency Compensation

支持：

- 固定设备/链路 latency；
- manual offset；
- 串口 D1 RTT 测量；
- half-RTT one-way estimate；
- jitter 统计。

这些补偿只作用于 live playback，不改变 canonical funscript/tcode 时间线。

## 参考风格

既支持单个 reference bundle，也支持多个 reference bundle 的加权融合和 deterministic clustering。风格学习提取统计动作特征，不复制原脚本的时间戳或位置轨迹。
