"""PythonDancer 3.0 Intelligent Choreography localization additions."""
from __future__ import annotations

from . import i18n
from .i18n_v28 import install_v28_translations

_INSTALLED = False


def install_v30_translations():
    global _INSTALLED
    if _INSTALLED:
        return
    install_v28_translations()
    i18n._ZH.update({
        "PythonDancer 3.0 · Intelligent Choreography Workstation": "PythonDancer 3.0 · 智能六轴编舞工作站",
        "Intelligence": "智能编舞",
        "Choreography Copilot": "编舞 Copilot",
        "Instruction": "指令",
        "Apply Copilot": "应用 Copilot",
        "Preference Learning": "偏好学习",
        "Prefer A": "偏好 A",
        "Prefer B": "偏好 B",
        "Load preference…": "加载偏好…",
        "Save preference…": "保存偏好…",
        "Motion Grammar": "动作语法",
        "Primitive": "动作原语",
        "Add primitive": "添加动作原语",
        "Apply motion program": "应用动作程序",
        "Clear program": "清空动作程序",
        "Reference Retrieval": "参考动作检索",
        "Load index…": "加载索引…",
        "Retrieve section": "检索当前段落",
        "Apply best reference": "应用最佳参考",
        "Project Versions": "工程版本",
        "Commit version": "提交版本",
        "Create branch": "创建分支",
        "Plugin SDK": "插件 SDK",
        "Discover plugins": "发现插件",
        "Device Twin 2.0": "设备数字孪生 2.0",
        "Load telemetry…": "加载遥测…",
        "Motion Packs": "动作包",
        "Load pack…": "加载动作包…",
        "Save pack…": "保存动作包…",
        "Control Surfaces": "控制器",
        "Start controls": "启动控制器",
        "Stop controls": "停止控制器",
        "Batch Queue": "批处理队列",
        "Run manifest…": "运行任务清单…",
    })
    i18n._REPLACEMENTS = (
        ("Copilot applied", "Copilot 已应用"),
        ("Preference updated", "偏好已更新"),
        ("Motion program applied", "动作程序已应用"),
        ("Reference applied", "参考动作已应用"),
        ("Version committed", "版本已提交"),
        ("Telemetry calibrated", "遥测校准已完成"),
    ) + tuple(i18n._REPLACEMENTS)
    _INSTALLED = True
