import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from jsonschema import ValidationError, validate


@dataclass(frozen=True)
class WorkflowDefinition:
    id: str
    name: str
    kind: str
    cassette_path: Path
    workflow_path: Path
    input_map: dict[str, list[Any]]
    request_schema: dict[str, Any] | bool | None = None
    docs: dict[str, Any] = field(default_factory=dict)
    runtime: dict[str, Any] = field(default_factory=dict)
    aliases: list[str] = field(default_factory=list)
    models_required: dict[str, list[str]] = field(default_factory=dict)

class WorkflowRegistry:
    def __init__(self, cassette_dir: Path, cassette_schema_path: Path | None = None) -> None:
        self.cassette_dir = cassette_dir
        self.cassette_schema_path = cassette_schema_path
        self._definitions: dict[str, WorkflowDefinition] = {}
        self._load()

    def _load_schema(self) -> dict[str, Any] | None:
        if self.cassette_schema_path is None:
            return None
        if not self.cassette_schema_path.exists():
            raise FileNotFoundError(f"Cassette schema not found: {self.cassette_schema_path}")
        return json.loads(self.cassette_schema_path.read_text())

    def _load(self) -> None:
        if not self.cassette_dir.exists():
            raise FileNotFoundError(f"Cassette directory not found: {self.cassette_dir}")

        schema = self._load_schema()

        for cassette_path in sorted(self.cassette_dir.glob("*/cassette.yaml")):
            raw = yaml.safe_load(cassette_path.read_text()) or {}

            if schema is not None:
                try:
                    validate(raw, schema)
                except ValidationError as exc:
                    raise ValueError(
                        f"Invalid cassette '{cassette_path}': {exc.message}"
                    ) from exc

            workflow_path = cassette_path.parent / raw.get("workflow_file", "workflow.json")
            if not workflow_path.exists():
                raise FileNotFoundError(
                    f"Workflow JSON for cassette '{raw.get('id', cassette_path.parent.name)}' not found: {workflow_path}"
                )

            definition = WorkflowDefinition(
                id=raw["id"],
                name=raw["name"],
                kind=raw["kind"],
                cassette_path=cassette_path,
                workflow_path=workflow_path,
                input_map=raw["inputs"],
                request_schema=raw.get("request_schema"),
                docs=raw.get("docs", {}),
                runtime=raw.get("runtime", {}),
                aliases=raw.get("aliases", []),
                models_required=raw.get("models_required", {}),
            )
            self._definitions[definition.id] = definition

        if not self._definitions:
            raise RuntimeError(f"No cassettes found in {self.cassette_dir}")

    def summary(self) -> list[dict[str, str]]:
        return [
            {
                "id": d.id,
                "name": d.name,
                "kind": d.kind,
                "workflow": d.workflow_path.name,
                "aliases": d.aliases,
            }
            for d in self._definitions.values()
        ]

    def get(self, workflow_id: str) -> WorkflowDefinition:
        if workflow_id not in self._definitions:
            raise KeyError(f"Unknown workflow_id: {workflow_id}")
        return self._definitions[workflow_id]

    def build(self, workflow_id: str, values: dict[str, Any]) -> tuple[WorkflowDefinition, dict[str, Any]]:
        definition = self.get(workflow_id)
        workflow = json.loads(definition.workflow_path.read_text())

        for key, binding in definition.input_map.items():
            if key in values and values[key] is not None:
                if (
                    isinstance(binding, list)
                    and binding
                    and all(isinstance(x, list) for x in binding)
                ):
                    for path in binding:
                        self._deep_set(workflow, path, values[key])
                else:
                    self._deep_set(workflow, binding, values[key])

        return definition, workflow

    @staticmethod
    def _deep_set(obj: dict[str, Any], path: list[str], value: Any) -> None:
        cursor = obj
        for step in path[:-1]:
            cursor = cursor[step]
        cursor[path[-1]] = value
