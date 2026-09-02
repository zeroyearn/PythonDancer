"""PythonDancer 2.8 DAW localization additions."""
from __future__ import annotations

from . import i18n

_INSTALLED = False


def install_v28_translations():
    global _INSTALLED
    if _INSTALLED:
        return
    i18n._ZH.update({
        "PythonDancer 2.8 · AI Choreography DAW": "PythonDancer 2.8 · AI 六轴编舞 DAW",
        "DAW Automation": "DAW 自动化",
        "Automation lanes": "自动化轨道",
        "Lane": "轨道",
        "Point time": "关键点时间",
        "Point value": "关键点数值",
        "Easing": "缓动",
        "Add / update point": "添加 / 更新关键点",
        "Remove nearest": "删除最近关键点",
        "Quantize to beats": "量化到节拍",
        "Style Morphing": "风格渐变",
        "Style": "风格",
        "Style time": "风格时间",
        "Style strength": "风格强度",
        "Add style keyframe": "添加风格关键帧",
        "Remove style keyframe": "删除风格关键帧",
        "Candidate Composer": "候选方案编排器",
        "Assign section": "分配段落",
        "Compose sections": "合成段落",
        "Auto assign": "自动分配",
        "Live Choreography": "实时编舞",
        "Audio input": "音频输入",
        "Refresh devices": "刷新设备",
        "Live BPM": "实时 BPM",
        "Prediction horizon": "预测窗口",
        "Preview only": "仅预览",
        "Send TCode": "发送 TCode",
        "Start live": "开始实时编舞",
        "Stop live": "停止实时编舞",
        "Device Twin": "设备数字孪生",
        "Safe mode": "安全模式",
        "Load twin…": "加载设备模型…",
        "Save twin…": "保存设备模型…",
        "Apply twin": "应用设备模型",
        "Motion Inspector": "动作检查器",
        "Mechanical margin": "机械余量",
        "Live idle": "实时模式：空闲",
    })
    extra = (
        ("Live running", "实时编舞运行中"),
        ("Live stopped", "实时编舞已停止"),
        ("Candidate composition", "候选方案编排"),
        ("Automation updated", "自动化已更新"),
        ("Style morph updated", "风格渐变已更新"),
        ("Device twin loaded", "设备数字孪生已加载"),
        ("Device twin saved", "设备数字孪生已保存"),
    )
    i18n._REPLACEMENTS = extra + tuple(i18n._REPLACEMENTS)
    _INSTALLED = True
