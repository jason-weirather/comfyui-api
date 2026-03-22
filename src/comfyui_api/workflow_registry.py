import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class WorkflowDefinition:
    id: str
    name: str
    template_path: Path
    input_map: dict[str, list[str]]


class WorkflowRegistry:
    def __init__(self, registry_dir: Path, template_dir: Path) -> None:
        self.registry_dir = registry_dir
        self.template_dir = template_dir
        self._definitions: dict[str, WorkflowDefinition] = {}
        self._load()

    def _load(self) -> None:
        if not self.registry_dir.exists():
            raise FileNotFoundError(f"Workflow registry directory not found: {self.registry_dir}")

        for path in sorted(self.registry_dir.glob("*.yaml")):
            raw = yaml.safe_load(path.read_text())
            template_path = self.template_dir / raw["template"]
            if not template_path.exists():
                raise FileNotFoundError(
                    f"Workflow template for '{raw['id']}' not found: {template_path}"
                )
            definition = WorkflowDefinition(
                id=raw["id"],
                name=raw["name"],
                template_path=template_path,
                input_map=raw["input_map"],
            )
            self._definitions[definition.id] = definition

        if not self._definitions:
            raise RuntimeError(f"No workflow definitions found in {self.registry_dir}")

    def summary(self) -> list[dict[str, str]]:
        return [
            {"id": d.id, "name": d.name, "template": d.template_path.name}
            for d in self._definitions.values()
        ]

    def build(self, workflow_id: str, values: dict[str, Any]) -> tuple[WorkflowDefinition, dict[str, Any]]:
        if workflow_id not in self._definitions:
            raise KeyError(f"Unknown workflow_id: {workflow_id}")

        definition = self._definitions[workflow_id]
        workflow = json.loads(definition.template_path.read_text())

        for key, path in definition.input_map.items():
            if key in values and values[key] is not None:
                self._deep_set(workflow, path, values[key])

        return definition, workflow

    @staticmethod
    def _deep_set(obj: dict[str, Any], path: list[str], value: Any) -> None:
        cursor = obj
        for step in path[:-1]:
            cursor = cursor[step]
        cursor[path[-1]] = value
