"""Load an explicitly declared trusted Rule Plugin from a content pack."""

from __future__ import annotations

import hashlib
import importlib.util
import re
import sys
from pathlib import Path
from typing import Any

from engine.core.errors import ContentPackError
from engine.rules.plugin import RULE_PLUGIN_API_VERSION, RulePlugin

_SAFE_KEY = re.compile(r"[^a-zA-Z0-9_]")


def load_rule_plugin(root: Path, meta: dict[str, Any]) -> RulePlugin | None:
    declaration = meta.get("rule_plugin")
    if declaration is None:
        return None
    if not isinstance(declaration, dict):
        raise ContentPackError("pack rule_plugin must be a mapping")

    relative = declaration.get("path")
    class_name = declaration.get("class")
    declared_api = str(declaration.get("api_version", ""))
    if not isinstance(relative, str) or not relative.endswith(".py"):
        raise ContentPackError("rule_plugin.path must name a Python file")
    if not isinstance(class_name, str) or not class_name:
        raise ContentPackError("rule_plugin.class is required")
    if declared_api != RULE_PLUGIN_API_VERSION:
        raise ContentPackError(
            f"unsupported rule plugin API {declared_api!r}; expected {RULE_PLUGIN_API_VERSION!r}"
        )

    path = (root / relative).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise ContentPackError("rule_plugin.path escapes the content pack") from exc
    if not path.is_file():
        raise ContentPackError(f"rule plugin file not found: {relative}")

    digest = hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()[:12]
    module_name = f"content_rule_plugin_{_SAFE_KEY.sub('_', root.name)}_{digest}"
    spec = importlib.util.spec_from_file_location(
        module_name,
        path,
        submodule_search_locations=[str(root)],
    )
    if spec is None or spec.loader is None:
        raise ContentPackError(f"cannot load rule plugin: {relative}")
    module = importlib.util.module_from_spec(spec)
    try:
        # Register the synthetic package while executing so a portable plugin
        # can use relative imports such as ``from .domain_rules import ...``.
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        plugin_class = getattr(module, class_name)
        plugin = plugin_class()
    except Exception as exc:
        sys.modules.pop(module_name, None)
        raise ContentPackError(f"failed to initialise rule plugin {class_name!r}") from exc

    if not isinstance(plugin, RulePlugin):
        raise ContentPackError(f"{class_name!r} does not implement RulePlugin")
    if plugin.api_version != RULE_PLUGIN_API_VERSION:
        raise ContentPackError(
            f"plugin runtime API {plugin.api_version!r} does not match declaration"
        )
    if not plugin.handled_actions:
        raise ContentPackError("rule plugin must handle at least one action")
    return plugin
