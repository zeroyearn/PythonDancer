"""Runtime GUI localization for PythonDancer.

The workstation has several inherited UI layers.  Rather than duplicating every
widget builder, this controller translates the assembled Tk widget tree,
notebook tabs, menus, canvas text, message boxes and dynamic StringVars.  English
remains the internal/control vocabulary, so changing UI language never changes
preset/axis values consumed by the motion engine.
"""
from __future__ import annotations

import locale
import os
import re
from typing import Iterable

LANG_EN = "en"
LANG_ZH = "zh_CN"
SUPPORTED_LANGUAGES = (LANG_ZH, LANG_EN)

_ZH = {
    "PythonDancer 2.6 · Generation Quality Workstation": "PythonDancer 2.6 · 生成质量工作站",
    "PythonDancer · Choreography Workstation": "PythonDancer · 编舞工作站",
    "PythonDancer · Six-axis Choreography": "PythonDancer · 六轴编舞",
    "PythonDancer - Six-axis choreography": "PythonDancer - 六轴编舞",
    "PythonDancer": "PythonDancer",
    "Six-axis music choreography": "六轴音乐编舞",
    "1 · Motion setup": "1 · 动作设置",
    "Start here. These controls define the overall movement character.": "从这里开始。这些参数定义整体动作风格。",
    "Preset": "预设",
    "Mode": "模式",
    "Axis strength": "轴强度",
    "Gesture strength": "手势强度",
    "Subdivision": "细分",
    "Auto-tune L0 pitch and energy": "自动调整 L0 中心与能量",
    "2 · Musical intelligence": "2 · 音乐智能",
    "Optional structure, learned style, and stem-aware controls.": "可选的结构分析、风格学习与分轨感知控制。",
    "Structure": "结构",
    "Style & stems": "风格与分轨",
    "Beats / bar": "每小节拍数",
    "Bars / phrase": "每乐句小节数",
    "Section bars": "段落小节数",
    "Choreography profile": "编舞配置",
    "Reference bundle": "参考脚本包",
    "Reference library…": "参考库…",
    "Reference library": "参考库",
    "Choose…": "选择…",
    "Browse…": "浏览…",
    "Browse": "浏览",
    "Stems": "分轨",
    "Stem folder…": "分轨目录…",
    "Motion preview": "动作预览",
    "No choreography generated": "尚未生成编舞",
    "Axis controls": "轴控制",
    "Solo is preview-only. Mute affects export/device. Lock protects local regeneration.": "Solo 仅影响预览；Mute 会影响导出/设备；Lock 可保护局部重新生成。",
    "All axes": "全部轴",
    "Axis": "轴",
    "Mute": "静音",
    "Lock": "锁定",
    "Generation Quality": "生成质量",
    "Independent stem-driven clocks feed a continuous Motion Intent layer before the 6D pose / velocity / jerk optimizer.": "独立的分轨驱动时间轴先进入连续 Motion Intent，再进入六维姿态/速度/jerk 优化器。",
    "Independent secondary-axis timelines": "副轴使用独立时间轴",
    "Axis density": "轴关键帧密度",
    "Accent threshold": "重音阈值",
    "6D pose / velocity / jerk optimizer": "六维姿态 / 速度 / Jerk 优化器",
    "Pose budget": "姿态预算",
    "Velocity budget": "速度预算",
    "Optimizer passes": "优化迭代次数",
    "Intent / Gesture": "意图 / 手势",
    "Motion Intent": "Motion Intent",
    "Selected / next gesture block": "当前 / 下一个手势块",
    "Cycles": "循环数",
    "Phase": "相位",
    "Direction": "方向",
    "Blend in": "淡入",
    "Blend out": "淡出",
    "Apply selected": "应用到当前手势",
    "Manual Motion Intent blend": "手动 Motion Intent 混合",
    "Override amount": "覆盖比例",
    "Copy inferred → manual": "复制推断值 → 手动值",
    "Cluster": "聚类",
    "Motion": "动作",
    "Timeline editor": "时间轴编辑器",
    "3D Pose": "3D 姿态",
    "Curve editor": "曲线编辑器",
    "Diagnostics": "诊断",
    "Drag empty waveform space to select · drag blue section dividers · drag/resize gesture blocks": "拖动波形空白区域进行选择 · 拖动蓝色段落边界 · 拖动/缩放手势块",
    "Gesture": "手势",
    "Strength": "强度",
    "Add to selection": "添加到所选范围",
    "Delete gesture": "删除手势",
    "Section": "段落",
    "Apply label": "应用标签",
    "Edit selection": "编辑所选范围",
    "Select a range in Timeline editor, adjust local character, then replace only that range. Locked axes are preserved.": "在时间轴中选择范围，调整局部风格后只替换该范围；锁定轴保持不变。",
    "Local preset": "局部预设",
    "Regenerate selection": "重新生成所选范围",
    "Safety & motion shaping": "安全与动作整形",
    "Smart limits constrain coupled poses. Gap fill and axis links are applied before the final physical constraint pass.": "智能限制约束耦合姿态；补空与轴联动会在最终物理约束前应用。",
    "Smart cross-axis limits": "智能跨轴限制",
    "Envelope": "安全包络",
    "Gap filling": "空段填充",
    "Gap threshold": "空段阈值",
    "Apply shaping": "应用整形",
    "Axis link": "轴联动",
    "Add": "添加",
    "Remove last link": "删除最后一个联动",
    "Only generate when target is empty": "仅在目标轴为空时生成",
    "Link delay": "联动延迟",
    "Link smoothing": "联动平滑",
    "Link mode": "联动模式",
    "Project": "项目",
    "Save .pdance": "保存 .pdance",
    "Open .pdance…": "打开 .pdance…",
    "Undo": "撤销",
    "Redo": "重做",
    "Autosave now": "立即自动保存",
    "File": "文件",
    "Edit": "编辑",
    "Open project…": "打开项目…",
    "Save project": "保存项目",
    "Save project as…": "项目另存为…",
    "Intiface / Buttplug": "Intiface / Buttplug",
    "Connect to Intiface Central over WebSocket. Position uses L0; vibration follows six-axis motion intensity; rotation follows R0.": "通过 WebSocket 连接 Intiface Central。位置使用 L0；振动跟随六轴动作强度；旋转跟随 R0。",
    "Server": "服务器",
    "Device": "设备",
    "Scan": "扫描",
    "Play": "播放",
    "Pause": "暂停",
    "Resume": "继续",
    "STOP": "停止",
    "Stop Intiface": "停止 Intiface",
    "Playback safety": "播放安全",
    "Soft Start enters the selected start pose before playback. Auto Home returns naturally completed motion to neutral.": "Soft Start 会在播放前平滑进入起始姿态；Auto Home 会在自然播放结束后返回中位。",
    "Soft start": "软启动",
    "Auto Home after natural finish": "自然播放结束后自动回中",
    "Home ramp": "回中时间",
    "Apply safety timing": "应用安全时序",
    "8 · Timing & calibration": "8 · 时序与校准",
    "Live output can compensate transport/device latency and map normalized choreography into a saved device-safe envelope.": "实时输出可补偿传输/设备延迟，并将标准化编舞映射到已保存的设备安全范围。",
    "Latency": "延迟",
    "Manual offset": "手动偏移",
    "Measure serial RTT before play": "播放前测量串口 RTT",
    "Load…": "加载…",
    "Safe axis test": "安全单轴测试",
    "SR6 mechanical diagnostics": "SR6 机械诊断",
    "SR6 geometry": "SR6 几何参数",
    "Load geometry…": "加载几何参数…",
    "Reachable": "可达",
    "Unreachable": "不可达",
    "Language": "语言",
    "Chinese (Simplified)": "简体中文",
    "English": "English",
    "Wave": "波形",
    "Selection": "选择范围",
    "Generate motion to edit the timeline": "生成动作后即可编辑时间轴",
    "Interpolation": "插值",
    "Snap to beat": "吸附到节拍",
    "Quantize": "量化",
    "Smooth": "平滑",
    "Flatten": "拉平",
    "Scale": "缩放",
    "Offset": "偏移",
    "Apply": "应用",
    "Delete selected keyframe": "删除所选关键帧",
    "Double-click to add · drag a point to move · edits affect final funscript/TCode output": "双击添加 · 拖动关键帧移动 · 编辑会影响最终 funscript/TCode 输出",
    "Ready": "就绪",
    "Not connected": "未连接",
    "No axis links": "暂无轴联动",
    "No reference library": "暂无参考库",
    "Timing: no compensation": "时序：未启用补偿",
    "Calibration: normalized 0–100": "校准：标准化 0–100",
    "Motion Intent: generate a track to analyze": "Motion Intent：生成曲目后进行分析",
    "Reference clusters: not analyzed": "参考风格聚类：尚未分析",
    "Effective Intent: audio-driven": "有效 Intent：音频驱动",
    "forward": "正向",
    "reverse": "反向",
}

# Useful substitutions for dynamic status strings. Longer phrases run first.
_REPLACEMENTS = (
    ("Reference clustering failed", "参考风格聚类失败"),
    ("Reference clusters", "参考风格聚类"),
    ("Generation Quality parameters are invalid", "生成质量参数无效"),
    ("No actions could be generated from this input", "无法从该输入生成动作"),
    ("Choose a media file first", "请先选择媒体文件"),
    ("File does not exist", "文件不存在"),
    ("Choose one style source", "请选择一种风格来源"),
    ("Reference bundle", "参考脚本包"),
    ("Reference library", "参考库"),
    ("Generation failed", "生成失败"),
    ("Playback failed", "播放失败"),
    ("Device playback failed", "设备播放失败"),
    ("Device playback complete or stopped", "设备播放已完成或停止"),
    ("Safe calibration verification complete", "安全校准验证完成"),
    ("Calibration load failed", "校准文件加载失败"),
    ("Calibration", "校准"),
    ("Timing", "时序"),
    ("Structure", "结构"),
    ("Style", "风格"),
    ("Selection", "选择范围"),
    ("Intent", "意图"),
    ("independent axes", "独立轴时间线"),
    ("shared timeline", "共享时间线"),
    ("optimizer on", "优化器开启"),
    ("optimizer off", "优化器关闭"),
    ("keyframes", "关键帧"),
    ("actions", "动作"),
    ("Opening", "正在打开"),
    ("Playing", "正在播放"),
    ("Paused at", "已暂停于"),
    ("Resuming from", "从以下位置继续"),
    ("Seeking device to", "设备定位到"),
    ("Stopping", "正在停止"),
    ("Exported", "已导出"),
    ("Saved project", "项目已保存"),
    ("Opened project", "项目已打开"),
    ("Autosaved", "已自动保存"),
    ("Nothing to undo", "没有可撤销的操作"),
    ("Nothing to redo", "没有可重做的操作"),
    ("Ready", "就绪"),
    ("built-in", "内置"),
    ("stems off", "分轨关闭"),
    ("stems ready", "分轨就绪"),
    ("not analyzed", "尚未分析"),
    ("no sections detected", "未检测到段落"),
    ("No devices found", "未发现设备"),
    ("Found", "发现"),
    ("device(s)", "个设备"),
    ("Motion preview", "动作预览"),
    ("stroke", "升降"),
    ("surge", "前后"),
    ("sway", "左右"),
    ("twist", "扭转"),
    ("roll", "横滚"),
    ("pitch", "俯仰"),
)


def normalize_language(value: str | None) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    if text.startswith("en"):
        return LANG_EN
    if text.startswith("zh"):
        return LANG_ZH
    return LANG_ZH


def detect_language() -> str:
    override = os.environ.get("PYTHONDANCER_LANG")
    if override:
        return normalize_language(override)
    try:
        current = locale.getlocale()[0] or ""
    except Exception:
        current = ""
    if str(current).lower().startswith("en"):
        return LANG_EN
    # For non-English desktop locales default to Chinese for this fork.  Users
    # can switch at runtime or set PYTHONDANCER_LANG=en.
    return LANG_ZH


def translate_text(text: object, language: str) -> str:
    value = str(text if text is not None else "")
    if normalize_language(language) == LANG_EN or not value:
        return value
    exact = _ZH.get(value)
    if exact is not None:
        return exact
    result = value
    for source, target in _REPLACEMENTS:
        result = result.replace(source, target)
    return result


def configure_matplotlib_cjk() -> None:
    """Prefer common system CJK fonts without bundling or redistributing fonts."""
    try:
        from matplotlib import rcParams
        rcParams["font.sans-serif"] = [
            "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", "SimHei",
            "Arial Unicode MS", "DejaVu Sans",
        ]
        rcParams["axes.unicode_minus"] = False
    except Exception:
        pass


class I18nController:
    def __init__(self, root, language: str | None = None):
        self.root = root
        self.language = normalize_language(language or detect_language())
        self._widget_raw: dict[str, str] = {}
        self._widget_rendered: dict[str, str] = {}
        self._tab_raw: dict[tuple[str, str], str] = {}
        self._tab_rendered: dict[tuple[str, str], str] = {}
        self._canvas_raw: dict[tuple[str, int], str] = {}
        self._canvas_rendered: dict[tuple[str, int], str] = {}
        self._menu_raw: dict[tuple[str, int], str] = {}
        self._menu_rendered: dict[tuple[str, int], str] = {}
        self._vars: dict[int, object] = {}
        self._var_raw: dict[int, str] = {}
        self._var_rendered: dict[int, str] = {}
        self._title_raw = str(root.title())
        self._title_rendered = self._title_raw
        self._messagebox_originals = {}
        self._install_messagebox_translation()
        configure_matplotlib_cjk()

    def set_language(self, language: str) -> None:
        self.language = normalize_language(language)
        self.refresh(force=True)

    def tr(self, text: object) -> str:
        return translate_text(text, self.language)

    def bind_object(self, obj) -> None:
        """Discover StringVars in an object's state, including nested dict/list containers."""
        import tkinter as tk
        seen: set[int] = set()

        def visit(value):
            identity = id(value)
            if identity in seen:
                return
            seen.add(identity)
            if isinstance(value, tk.StringVar):
                self._vars[identity] = value
                try:
                    current = str(value.get())
                except Exception:
                    return
                self._var_raw.setdefault(identity, current)
                self._var_rendered.setdefault(identity, current)
                return
            if isinstance(value, dict):
                for item in value.values():
                    visit(item)
            elif isinstance(value, (list, tuple, set)):
                for item in value:
                    visit(item)

        for value in getattr(obj, "__dict__", {}).values():
            visit(value)

    def install_language_menu(self, variable, callback) -> None:
        import tkinter as tk
        try:
            menu_name = self.root.cget("menu")
            menu = self.root.nametowidget(menu_name) if menu_name else None
        except Exception:
            menu = None
        if menu is None:
            menu = tk.Menu(self.root)
            self.root.configure(menu=menu)
        language_menu = tk.Menu(menu, tearoff=False)
        language_menu.add_radiobutton(label="简体中文", value=LANG_ZH, variable=variable, command=callback)
        language_menu.add_radiobutton(label="English", value=LANG_EN, variable=variable, command=callback)
        menu.add_cascade(label="语言" if self.language == LANG_ZH else "Language", menu=language_menu)

    def _install_messagebox_translation(self) -> None:
        try:
            from tkinter import messagebox
        except Exception:
            return
        for name in ("showinfo", "showwarning", "showerror", "askokcancel", "askyesno", "askretrycancel", "askquestion"):
            original = getattr(messagebox, name, None)
            if original is None or getattr(original, "_pythondancer_i18n", False):
                continue
            self._messagebox_originals[name] = original

            def wrapped(title, message, *args, __original=original, **kwargs):
                return __original(self.tr(title), self.tr(message), *args, **kwargs)

            wrapped._pythondancer_i18n = True
            setattr(messagebox, name, wrapped)

    def _iter_widgets(self, widget) -> Iterable:
        yield widget
        try:
            children = widget.winfo_children()
        except Exception:
            children = ()
        for child in children:
            yield from self._iter_widgets(child)

    def _refresh_widget(self, widget, force: bool) -> None:
        key = str(widget)
        try:
            current = str(widget.cget("text"))
        except Exception:
            current = ""
        if current:
            rendered = self._widget_rendered.get(key)
            if key not in self._widget_raw or (current != rendered and not force):
                self._widget_raw[key] = current
            raw = self._widget_raw.get(key, current)
            translated = self.tr(raw)
            if current != translated:
                try:
                    widget.configure(text=translated)
                except Exception:
                    pass
            self._widget_rendered[key] = translated

        # ttk.Notebook tab labels are not normal child widget text options.
        try:
            tabs = widget.tabs()
        except Exception:
            tabs = ()
        for tab in tabs:
            tab_key = (key, str(tab))
            try:
                current_tab = str(widget.tab(tab, "text"))
            except Exception:
                continue
            rendered_tab = self._tab_rendered.get(tab_key)
            if tab_key not in self._tab_raw or (current_tab != rendered_tab and not force):
                self._tab_raw[tab_key] = current_tab
            translated_tab = self.tr(self._tab_raw[tab_key])
            if translated_tab != current_tab:
                try:
                    widget.tab(tab, text=translated_tab)
                except Exception:
                    pass
            self._tab_rendered[tab_key] = translated_tab

        # Tk Canvas is heavily used by the workstation timeline.
        try:
            items = widget.find_all()
        except Exception:
            items = ()
        for item in items:
            try:
                if widget.type(item) != "text":
                    continue
                current_canvas = str(widget.itemcget(item, "text"))
            except Exception:
                continue
            canvas_key = (key, int(item))
            rendered_canvas = self._canvas_rendered.get(canvas_key)
            if canvas_key not in self._canvas_raw or (current_canvas != rendered_canvas and not force):
                self._canvas_raw[canvas_key] = current_canvas
            translated_canvas = self.tr(self._canvas_raw[canvas_key])
            if translated_canvas != current_canvas:
                try:
                    widget.itemconfigure(item, text=translated_canvas)
                except Exception:
                    pass
            self._canvas_rendered[canvas_key] = translated_canvas

    def _refresh_menu(self, menu, force: bool) -> None:
        key = str(menu)
        try:
            end = menu.index("end")
        except Exception:
            return
        if end is None:
            return
        for index in range(int(end) + 1):
            try:
                entry_type = menu.type(index)
            except Exception:
                continue
            if entry_type in ("separator", "tearoff"):
                continue
            try:
                current = str(menu.entrycget(index, "label"))
            except Exception:
                continue
            item_key = (key, index)
            rendered = self._menu_rendered.get(item_key)
            if item_key not in self._menu_raw or (current != rendered and not force):
                self._menu_raw[item_key] = current
            translated = self.tr(self._menu_raw[item_key])
            if current != translated:
                try:
                    menu.entryconfigure(index, label=translated)
                except Exception:
                    pass
            self._menu_rendered[item_key] = translated
            if entry_type == "cascade":
                try:
                    child_name = menu.entrycget(index, "menu")
                    child = self.root.nametowidget(child_name)
                    self._refresh_menu(child, force)
                except Exception:
                    pass

    def _refresh_variables(self, force: bool) -> None:
        for identity, variable in list(self._vars.items()):
            try:
                current = str(variable.get())
            except Exception:
                continue
            rendered = self._var_rendered.get(identity)
            if identity not in self._var_raw or (current != rendered and not force):
                self._var_raw[identity] = current
            translated = self.tr(self._var_raw.get(identity, current))
            if current != translated:
                try:
                    variable.set(translated)
                except Exception:
                    continue
            self._var_rendered[identity] = translated

    def refresh(self, force: bool = False) -> None:
        try:
            current_title = str(self.root.title())
            if current_title != self._title_rendered and not force:
                self._title_raw = current_title
            translated_title = self.tr(self._title_raw)
            if current_title != translated_title:
                self.root.title(translated_title)
            self._title_rendered = translated_title
        except Exception:
            pass

        self.bind_object(self.root)
        for widget in self._iter_widgets(self.root):
            self._refresh_widget(widget, force)
        try:
            menu_name = self.root.cget("menu")
            if menu_name:
                self._refresh_menu(self.root.nametowidget(menu_name), force)
        except Exception:
            pass
        self._refresh_variables(force)
