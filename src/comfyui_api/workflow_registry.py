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
    input_map: dict[str, Any]
    optional_input_map: dict[str, Any] = field(default_factory=dict)
    presence_input_map: dict[str, str] = field(default_factory=dict)
    fallback_input_map: dict[str, str] = field(default_factory=dict)
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
                optional_input_map=raw.get("optional_inputs", {}),
                presence_input_map=raw.get("presence_inputs", {}),
                fallback_input_map=raw.get("fallback_inputs", {}),
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
        resolved_values = self._schema_defaults(definition.request_schema)
        resolved_values.update({k: v for k, v in values.items() if v is not None})

        presence_source_values = dict(resolved_values)
        for target, source in definition.presence_input_map.items():
            if target not in resolved_values:
                resolved_values[target] = (
                    source in presence_source_values
                    and presence_source_values[source] is not None
                )

        for target, source in definition.fallback_input_map.items():
            if target not in resolved_values or resolved_values[target] is None:
                if source in resolved_values and resolved_values[source] is not None:
                    resolved_values[target] = resolved_values[source]

        for key, binding in definition.optional_input_map.items():
            if key not in resolved_values or resolved_values[key] is None:
                self._apply_delete(workflow, binding)


        for key, binding in definition.input_map.items():
            if key in resolved_values and resolved_values[key] is not None:
                self._apply_set(workflow, binding, resolved_values[key])

        return definition, workflow


    @staticmethod
    def _schema_defaults(schema: dict[str, Any] | bool | None) -> dict[str, Any]:
        if not isinstance(schema, dict):
            return {}
        defaults: dict[str, Any] = {}
        for key, spec in (schema.get("properties") or {}).items():
            if isinstance(spec, dict) and "default" in spec:
                defaults[key] = spec["default"]
        return defaults

    @staticmethod
    def _apply_set(obj: dict[str, Any], binding: Any, value: Any) -> None:
        if (
            isinstance(binding, list)
            and binding
            and all(isinstance(x, list) for x in binding)
        ):
            for path in binding:
                WorkflowRegistry._deep_set(obj, path, value)
        else:
            WorkflowRegistry._deep_set(obj, binding, value)

    @staticmethod
    def _apply_delete(obj: dict[str, Any], binding: Any) -> None:
        if (
            isinstance(binding, list)
            and binding
            and all(isinstance(x, list) for x in binding)
        ):
            for path in binding:
                WorkflowRegistry._deep_delete(obj, path)
        else:
            WorkflowRegistry._deep_delete(obj, binding)

    @staticmethod
    def _deep_set(obj: dict[str, Any], path: list[str], value: Any) -> None:
        cursor = obj
        for step in path[:-1]:
            cursor = cursor[step]
        cursor[path[-1]] = value

    @staticmethod
    def _deep_delete(obj: dict[str, Any], path: list[str]) -> None:
        cursor = obj
        for step in path[:-1]:
            if isinstance(cursor, dict):
                if step not in cursor:
                    return
                cursor = cursor[step]
            elif isinstance(cursor, list):
                if not isinstance(step, int) or step >= len(cursor):
                    return
                cursor = cursor[step]
            else:
                return

        last = path[-1]
        if isinstance(cursor, dict):
            cursor.pop(last, None)
        elif isinstance(cursor, list) and isinstance(last, int) and last < len(cursor):
            cursor.pop(last)
