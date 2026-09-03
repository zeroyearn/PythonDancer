"""Plugin SDK and entry-point discovery for PythonDancer 3.0."""
from __future__ import annotations

from dataclasses import dataclass, field
from importlib import metadata
from typing import Any, Callable, Mapping


PLUGIN_KINDS = (
    "gesture",
    "quality_metric",
    "device",
    "exporter",
    "analyzer",
    "planner",
    "copilot_backend",
    "control_surface",
)


@dataclass(frozen=True)
class PluginDescriptor:
    name: str
    kind: str
    version: str = "0"
    description: str = ""
    provider: str = ""

    def __post_init__(self):
        if self.kind not in PLUGIN_KINDS:
            raise ValueError(f"unsupported plugin kind: {self.kind}")

    def to_dict(self):
        return {
            "name": self.name,
            "kind": self.kind,
            "version": self.version,
            "description": self.description,
            "provider": self.provider,
        }


@dataclass
class RegisteredPlugin:
    descriptor: PluginDescriptor
    plugin: Any


@dataclass
class PluginRegistry:
    plugins: dict[str, dict[str, RegisteredPlugin]] = field(default_factory=lambda: {kind: {} for kind in PLUGIN_KINDS})
    errors: list[str] = field(default_factory=list)

    def register(self, descriptor: PluginDescriptor, plugin: Any):
        self.plugins.setdefault(descriptor.kind, {})[descriptor.name] = RegisteredPlugin(descriptor, plugin)
        return plugin

    def unregister(self, kind: str, name: str):
        self.plugins.get(kind, {}).pop(name, None)

    def get(self, kind: str, name: str, default=None):
        item = self.plugins.get(kind, {}).get(name)
        return item.plugin if item else default

    def descriptors(self, kind: str | None = None):
        groups = (kind,) if kind else PLUGIN_KINDS
        return tuple(
            item.descriptor
            for group in groups
            for item in self.plugins.get(group, {}).values()
        )

    def invoke(self, kind: str, name: str, *args, **kwargs):
        plugin = self.get(kind, name)
        if plugin is None:
            raise KeyError(f"plugin not found: {kind}/{name}")
        target = plugin
        if hasattr(plugin, "run"):
            target = plugin.run
        if not callable(target):
            raise TypeError(f"plugin is not callable: {kind}/{name}")
        return target(*args, **kwargs)

    def discover(self, group: str = "pythondancer.plugins"):
        """Discover third-party plugins through Python entry points.

        Entry points may expose either:
        - a callable ``register(registry)`` function;
        - an object with ``descriptor`` and optional ``run``;
        - a mapping with ``descriptor`` and ``plugin``.
        Discovery failures are isolated and recorded instead of blocking launch.
        """
        try:
            entries = metadata.entry_points()
            entries = entries.select(group=group) if hasattr(entries, "select") else entries.get(group, ())
        except Exception as exc:
            self.errors.append(f"entry-point discovery failed: {exc}")
            return self
        for entry in entries:
            try:
                loaded = entry.load()
                if callable(loaded) and getattr(loaded, "__name__", "") == "register":
                    loaded(self)
                    continue
                if isinstance(loaded, Mapping):
                    descriptor = loaded.get("descriptor")
                    plugin = loaded.get("plugin")
                else:
                    descriptor = getattr(loaded, "descriptor", None)
                    plugin = loaded
                if isinstance(descriptor, Mapping):
                    descriptor = PluginDescriptor(**descriptor)
                if not isinstance(descriptor, PluginDescriptor):
                    kind = getattr(loaded, "kind", "")
                    if kind not in PLUGIN_KINDS:
                        raise ValueError("plugin must declare descriptor or valid kind")
                    descriptor = PluginDescriptor(
                        name=str(getattr(loaded, "name", entry.name)),
                        kind=kind,
                        version=str(getattr(loaded, "version", "0")),
                        description=str(getattr(loaded, "description", "")),
                        provider=str(entry.value),
                    )
                self.register(descriptor, plugin)
            except Exception as exc:
                self.errors.append(f"{entry.name}: {exc}")
        return self

    def to_dict(self):
        return {
            "plugins": [descriptor.to_dict() for descriptor in self.descriptors()],
            "errors": list(self.errors),
        }


GLOBAL_PLUGINS = PluginRegistry()


def plugin(kind: str, name: str, *, version="0", description="", provider="core"):
    """Decorator for lightweight built-in or user plugins."""
    descriptor = PluginDescriptor(name, kind, version, description, provider)

    def decorate(target: Callable):
        GLOBAL_PLUGINS.register(descriptor, target)
        return target

    return decorate
