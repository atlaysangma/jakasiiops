from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol


class ReasoningProvider(Protocol):
    name: str

    def choose_mapping(
        self, canonical_field: str, candidates: list[str], context: dict
    ) -> tuple[str | None, float, str]: ...

    def summarize(self, title: str, facts: dict) -> str: ...


@dataclass(slots=True)
class DeterministicReasoner:
    """Offline fallback. It never converts a guess into a verified fact."""

    name: str = "deterministic"

    def choose_mapping(
        self, canonical_field: str, candidates: list[str], context: dict
    ) -> tuple[str | None, float, str]:
        if not candidates:
            return None, 0.0, "No candidate matched the configured vocabulary."
        return candidates[0], 0.65, "Highest lexical and sample-type match; human verification required."

    def summarize(self, title: str, facts: dict) -> str:
        compact = ", ".join(f"{key}={value}" for key, value in sorted(facts.items()))
        return f"{title}: {compact}"


@dataclass(slots=True)
class OllamaReasoner:
    """Optional local model adapter; no cloud credential is required."""

    model: str = "qwen2.5:7b"
    base_url: str = "http://127.0.0.1:11434"
    timeout_seconds: int = 45
    name: str = "ollama"

    def _generate(self, prompt: str) -> str:
        body = json.dumps(
            {"model": self.model, "prompt": prompt, "stream": False, "format": "json"}
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url.rstrip('/')}/api/generate",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
                return payload.get("response", "{}")
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Local Ollama reasoning failed: {exc}") from exc

    def choose_mapping(
        self, canonical_field: str, candidates: list[str], context: dict
    ) -> tuple[str | None, float, str]:
        prompt = (
            "You map an unfamiliar store schema into a canonical operations model. "
            "Never claim certainty. Return JSON with source_path, confidence from 0 to 1, and reasoning.\n"
            f"Canonical field: {canonical_field}\nCandidates: {candidates}\nContext: {context}"
        )
        result = json.loads(self._generate(prompt))
        source = result.get("source_path")
        if source not in candidates:
            return None, 0.0, "Local model did not return a valid candidate."
        return source, min(float(result.get("confidence", 0.5)), 0.89), str(result.get("reasoning", ""))

    def summarize(self, title: str, facts: dict) -> str:
        prompt = (
            "Return JSON with a concise 'summary'. State uncertainty explicitly.\n"
            f"Title: {title}\nFacts: {facts}"
        )
        return str(json.loads(self._generate(prompt)).get("summary", title))

