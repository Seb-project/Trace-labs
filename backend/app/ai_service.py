from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .models import CircuitBlock, DatasheetCandidate, DatasheetSearchResponse, DatasheetSource
from .part_intent import analyse_part_intent, normalise_part_number
from .storage import JsonStore


@dataclass
class AISuggestion:
    recipe_id: str
    label: str
    reason: str
    status: str = "supported"


@dataclass
class AIChatDecision:
    action: str
    assistant_message: str
    recipe_id: str = ""
    target_part_number: str = ""
    context_part_numbers: list[str] = field(default_factory=list)
    suggestions: list[AISuggestion] = field(default_factory=list)
    confidence: float = 0.0
    used_ai: bool = False
    token_count: int = 0
    error: str | None = None


class TraceLabsAIService:
    def __init__(self, data_dir: Path | None = None) -> None:
        self.api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        self.model = os.environ.get("OPENAI_MODEL", "gpt-5.5").strip() or "gpt-5.5"
        self.timeout_seconds = float(os.environ.get("OPENAI_TIMEOUT_SECONDS", "20"))
        self.datasheet_timeout_seconds = float(
            os.environ.get("OPENAI_DATASHEET_TIMEOUT_SECONDS", str(max(self.timeout_seconds, 60)))
        )
        self.broad_datasheet_timeout_seconds = float(
            os.environ.get(
                "OPENAI_BROAD_DATASHEET_TIMEOUT_SECONDS",
                str(min(self.timeout_seconds, self.datasheet_timeout_seconds)),
            )
        )
        self.datasheet_max_output_tokens = int(os.environ.get("OPENAI_DATASHEET_MAX_OUTPUT_TOKENS", "8000"))
        self.live_datasheet_search_enabled = (
            os.environ.get("DATASHEET_LIVE_SEARCH_ENABLED", "true").strip().lower()
            not in {"0", "false", "no", "off"}
        )
        self.search_cache = JsonStore(data_dir / "datasheet_search_cache.json") if data_dir else None

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "model": self.model,
            "provider": "openai" if self.enabled else "local_fallback",
            "live_datasheet_search_enabled": self.live_datasheet_search_enabled and self.enabled,
            "timeout_seconds": self.timeout_seconds,
            "datasheet_timeout_seconds": self.datasheet_timeout_seconds,
            "broad_datasheet_timeout_seconds": self.broad_datasheet_timeout_seconds,
            "datasheet_max_output_tokens": self.datasheet_max_output_tokens,
        }

    def decide(
        self,
        message: str,
        available_recipes: list[dict[str, Any]],
        current_block: CircuitBlock | None = None,
        draft_block: CircuitBlock | None = None,
        answers: dict[str, str] | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> AIChatDecision:
        fallback = self._fallback_decision(
            message,
            available_recipes=available_recipes,
            current_block=current_block,
            draft_block=draft_block,
        )
        if current_block is None and draft_block is None and fallback.action in {"generate_recipe", "suggest_parts"}:
            return fallback
        if not self.enabled:
            return fallback

        try:
            raw = self._call_openai(
                message=message,
                available_recipes=available_recipes,
                current_block=current_block,
                draft_block=draft_block,
                answers=answers or {},
                history=(history or [])[-8:],
            )
            decision = self._decision_from_payload(raw)
            decision.used_ai = True
            return decision
        except (ValueError, TimeoutError, HTTPError, URLError, OSError) as exc:
            fallback.error = str(exc)
            fallback.assistant_message = (
                f"I could not reach OpenAI cleanly, so I used the local Trace Labs fallback. "
                f"{fallback.assistant_message}"
            )
            return fallback

    def search_datasheets(
        self,
        query: str,
        available_recipes: list[dict[str, Any]],
        include_unsupported: bool = True,
    ) -> DatasheetSearchResponse:
        intent = analyse_part_intent(query)
        cache_key = self._datasheet_cache_key(query, include_unsupported)
        cached = self._read_cached_datasheet_search(cache_key, query)
        if cached is not None:
            return cached

        fallback = self._fallback_datasheet_search(query, available_recipes)
        if not self.enabled or not self.live_datasheet_search_enabled:
            return fallback

        try:
            target_keys = {normalise_part_number(part) for part in intent.target_part_numbers if part}
            timeout_seconds = (
                self.datasheet_timeout_seconds
                if target_keys
                else self.broad_datasheet_timeout_seconds
            )
            payload = self._call_openai_datasheet_search(
                query,
                available_recipes,
                include_unsupported,
                timeout_seconds=timeout_seconds,
            )
            response = self._datasheet_response_from_payload(query, payload)
            if self._needs_deeper_datasheet_search(response, intent):
                try:
                    deeper_payload = self._call_openai_datasheet_search(
                        query,
                        available_recipes,
                        include_unsupported,
                        deepening=True,
                        timeout_seconds=self.datasheet_timeout_seconds,
                    )
                    response = self._merge_datasheet_responses(
                        response,
                        self._datasheet_response_from_payload(query, deeper_payload),
                    )
                except (ValueError, TimeoutError, HTTPError, URLError, OSError) as exc:
                    response.warnings.append(f"Reference-design follow-up search failed: {exc}")
            self._mark_incomplete_source_coverage(response)
            self._write_cached_datasheet_search(cache_key, response)
            return response
        except (ValueError, TimeoutError, HTTPError, URLError, OSError) as exc:
            fallback.warnings.append(f"Live datasheet search failed, using local fallback: {exc}")
            return fallback

    def _datasheet_cache_key(self, query: str, include_unsupported: bool) -> str:
        intent = analyse_part_intent(query)
        if intent.target_part_numbers:
            part_key = normalise_part_number(intent.target_part_numbers[0])
            return f"v1:part:{part_key}:unsupported:{int(include_unsupported)}"
        query_key = re.sub(r"\s+", " ", query.strip().lower())
        return f"v1:query:{query_key}:unsupported:{int(include_unsupported)}"

    def _read_cached_datasheet_search(
        self,
        cache_key: str,
        query: str,
    ) -> DatasheetSearchResponse | None:
        if self.search_cache is None:
            return None
        try:
            entries = self.search_cache.read_dict()
            entry = entries.get(cache_key)
            if not isinstance(entry, dict):
                return None
            response = DatasheetSearchResponse.model_validate(entry.get("response"))
        except (json.JSONDecodeError, OSError, ValueError, TypeError):
            return None

        response = response.model_copy(deep=True)
        original_provider = response.provider
        response.query = query
        response.provider = "local_cache"
        response.live_search_used = False
        response.token_count = 0
        cache_note = (
            f"Loaded cached datasheet search result for "
            f"{response.target_part_number or query}; original provider: {original_provider}."
        )
        response.search_audit = [cache_note, *[item for item in response.search_audit if item != cache_note]]
        return response

    def _write_cached_datasheet_search(
        self,
        cache_key: str,
        response: DatasheetSearchResponse,
    ) -> None:
        if self.search_cache is None or not response.live_search_used or not response.candidates:
            return
        try:
            entries = self.search_cache.read_dict()
            entries[cache_key] = {
                "saved_at": datetime.now(timezone.utc).isoformat(),
                "response": response.model_dump(),
            }
            if len(entries) > 50:
                entries = dict(
                    sorted(
                        entries.items(),
                        key=lambda item: str(item[1].get("saved_at", "")) if isinstance(item[1], dict) else "",
                    )[-50:]
                )
            self.search_cache.write_dict(entries)
        except (OSError, TypeError, ValueError):
            return

    def _call_openai(
        self,
        message: str,
        available_recipes: list[dict[str, Any]],
        current_block: CircuitBlock | None,
        draft_block: CircuitBlock | None,
        answers: dict[str, str],
        history: list[dict[str, str]],
    ) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "input": [
                {"role": "system", "content": self._system_prompt(available_recipes)},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "user_message": message,
                            "part_intent": self._part_intent_summary(message),
                            "available_recipes": available_recipes,
                            "current_block": self._block_summary(current_block),
                            "draft_block": self._block_summary(draft_block),
                            "answers": answers,
                            "recent_history": history,
                        },
                    ),
                },
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "tracelabs_chat_decision",
                    "strict": True,
                    "schema": self._decision_schema(),
                }
            },
            "max_output_tokens": 900,
        }
        request = Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            body = json.loads(response.read().decode("utf-8"))
        text = self._extract_output_text(body)
        parsed = json.loads(text)
        parsed["_token_count"] = int(body.get("usage", {}).get("total_tokens") or 0)
        return parsed

    def _call_openai_datasheet_search(
        self,
        query: str,
        available_recipes: list[dict[str, Any]],
        include_unsupported: bool,
        deepening: bool = False,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        part_intent = self._part_intent_summary(query)
        payload = {
            "model": self.model,
            "input": [
                {
                    "role": "system",
                    "content": (
                        "You are Trace Labs' datasheet search and extraction service. Search the live web for "
                        "manufacturer datasheets, application notes, product pages, and reference circuits. "
                        "Prefer official manufacturer domains and distributor pages only as secondary evidence. "
                        "First identify the target component the user wants to add, and separately identify context "
                        "parts such as MCUs, host boards, processors, dev boards, or existing project parts. Do not "
                        "return a context part as a candidate unless the user explicitly asked to add that part itself. "
                        "Extract only review data: candidate parts, source URLs, confidence, warnings, and whether "
                        "Trace Labs has a supported local recipe. Do not invent schematic circuits. Do not output KiCad data. "
                        "If a part is not supported by a local recipe, mark supported_recipe_id as an empty string. "
                        "For each exact target part, look beyond the first PDF: find the official datasheet, then search "
                        "for linked or separately published reference designs, evaluation boards, application notes, "
                        "typical application circuits, layout guidelines, and design files. If an official datasheet or "
                        "product page links to a reference-design page or design-file package, include that linked source. "
                        "If you cannot verify that you checked linked reference-design material, say so in search_audit "
                        "and warnings instead of implying the search is complete. "
                        "Keep output bounded: return at most 4 candidates, at most 4 sources per candidate, and concise "
                        "single-sentence notes. For broad category searches, prefer common, manufacturer-backed parts "
                        "with clear I2C/SPI integration evidence. "
                        "When recommended values depend on load current, output voltage, bus capacitance, speed, "
                        "gain, timing, mode straps, or other application context, call that out in extraction_notes "
                        "and warnings. Trace Labs must ask the user for those conditions, and should provide cited "
                        "or reviewable starter values when possible. Leave values unspecified only when the user "
                        "says they are not sure. If you find an LCSC/JLCPCB/EasyEDA supplier CAD "
                        "identifier such as C2040, include supplier='LCSC', supplier_part_number with the C-number, "
                        "and supplier_url. Do not invent supplier IDs."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "query": query,
                            "part_intent": part_intent,
                            "available_recipes": available_recipes,
                            "include_unsupported": include_unsupported,
                            "search_focus": "deepen_reference_design_sources" if deepening else "initial_component_search",
                            "minimum_source_goal": (
                                "For exact target parts, return the official datasheet plus at least one official "
                                "application-note, reference-design, evaluation-board, design-file, or layout-guidance "
                                "source when such a source can be found."
                            ),
                            "output_limits": {
                                "max_candidates": 4,
                                "max_sources_per_candidate": 4,
                                "style": "concise JSON fields; no long prose",
                            },
                            "supported_recipe_policy": (
                                "available_recipes are only the currently verified insertable blocks. For anything not "
                                "listed there, search datasheets and return reviewable candidates. Unsupported "
                                "candidates can become AI-proposed draft recipes only after the user selects one "
                                "specific component and confirms the extra review step."
                            ),
                        },
                    ),
                },
            ],
            "tools": [{"type": "web_search_preview"}],
            "tool_choice": "required",
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "tracelabs_datasheet_search",
                    "strict": True,
                    "schema": self._datasheet_search_schema(),
                }
            },
            "stream": True,
            "max_output_tokens": self.datasheet_max_output_tokens,
        }
        request = Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        per_chunk_timeout = timeout_seconds or self.datasheet_timeout_seconds
        text_parts: list[str] = []
        total_tokens = 0
        with urlopen(request, timeout=per_chunk_timeout) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").rstrip("\n\r")
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str == "[DONE]":
                    break
                try:
                    event = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                event_type = event.get("type", "")
                if event_type == "response.output_text.delta":
                    text_parts.append(str(event.get("delta") or ""))
                elif event_type == "response.output_text.done":
                    text = str(event.get("text") or "")
                    if text:
                        text_parts = [text]
                elif event_type == "response.done":
                    resp = event.get("response") or {}
                    total_tokens = int((resp.get("usage") or {}).get("total_tokens") or 0)
                    if not text_parts:
                        text = self._extract_output_text(resp)
                        if text:
                            text_parts = [text]
        full_text = "".join(text_parts)
        if not full_text:
            raise ValueError("OpenAI streaming response contained no output text.")
        parsed = json.loads(full_text)
        parsed["_token_count"] = total_tokens
        return parsed

    def _system_prompt(self, available_recipes: list[dict[str, Any]]) -> str:
        recipe_lines = [
            f"- {recipe.get('id', '')}: {recipe.get('display_name', '')} ({recipe.get('interface', 'unknown interface')})"
            for recipe in available_recipes
            if recipe.get("id")
        ]
        supported_recipes = "\n".join(recipe_lines) if recipe_lines else "- none"
        return (
            "You are Trace Labs, an AI-assisted KiCad helper. Decide how the backend should respond. "
            "You do not generate KiCad files, CircuitBlock JSON, schematic text, symbols, or footprints. "
            "Deterministic backend code handles all schematic generation. "
            f"Verified insertable recipes currently known to Trace Labs are:\n{supported_recipes}\n"
            "Treat available_recipes as the set of already-verified insertable blocks only; do not treat it as an exhaustive "
            "catalog of everything Trace Labs can help with. "
            "Use action generate_recipe only when the user explicitly asks for or selects one of those verified recipes. "
            "Use action suggest_parts for broad requests like sensor, regulator, ADC, GPS, IMU, or interface IC when the exact "
            "part is unclear. For those requests, stay conversational, compare candidates, and ask clarifying questions as needed. "
            "Do not default to any verified local recipe just because one exists. "
            "Before choosing an action, identify the target component the user wants Trace Labs to add and list separate "
            "context parts. Treat board/platform names such as an MCU, processor, dev board, or host controller as context "
            "unless the user explicitly asks to add that component itself. If the target component is ambiguous, ask the user "
            "to choose; do not silently convert context into the target. "
            "For unsupported or ambiguous requests, use datasheet search to gather options and only create an AI-proposed draft "
            "recipe after the user names or selects one specific component. "
            "If the target looks like a complex subsystem such as a PMIC, switching regulator, charger, RF part, high-speed "
            "interface, MCU, processor, or module, be explicit that Trace Labs can only create a review skeleton until the "
            "reference design, layout guidance, pins, passives, and operating conditions are reviewed. "
            "Use action answer_question for follow-up questions, comparisons, or requests for rationale. "
            "Use action unsupported when Trace Labs cannot help with the request. "
            "When Trace Labs is about to present structured follow-up questions or option cards, keep the assistant message "
            "short and direct the user to the buttons; do not restate the full questionnaire in prose. "
            "When values depend on current, load, output voltage, I2C bus capacitance, speed, gain, timing, or other "
            "application context, say that Trace Labs needs the relevant information and will use cited values, "
            "calculated values, or reviewable starter values where possible. Leave values unspecified only if the user "
            "says they are not sure. Never silently guess critical electrical values. "
            "Keep responses concise, practical, and honest about review requirements."
        )

    def _decision_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["generate_recipe", "suggest_parts", "answer_question", "unsupported"],
                },
                "assistant_message": {"type": "string"},
                "recipe_id": {"type": "string"},
                "target_part_number": {"type": "string"},
                "context_part_numbers": {"type": "array", "items": {"type": "string"}},
                "suggestions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "recipe_id": {"type": "string"},
                            "label": {"type": "string"},
                            "reason": {"type": "string"},
                            "status": {"type": "string", "enum": ["supported", "planned", "unsupported"]},
                        },
                        "required": ["recipe_id", "label", "reason", "status"],
                    },
                },
                "confidence": {"type": "number"},
            },
            "required": [
                "action",
                "assistant_message",
                "recipe_id",
                "target_part_number",
                "context_part_numbers",
                "suggestions",
                "confidence",
            ],
        }

    def _datasheet_search_schema(self) -> dict[str, Any]:
        source_schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "title": {"type": "string"},
                "source_type": {
                    "type": "string",
                    "enum": [
                        "manufacturer_datasheet",
                        "manufacturer_product_page",
                        "application_note",
                        "reference_design",
                        "evaluation_board",
                        "design_file",
                        "distributor",
                        "other",
                    ],
                },
                "url": {"type": "string"},
                "confidence": {
                    "type": "string",
                    "enum": ["official", "likely_official", "secondary", "uncertain"],
                },
                "notes": {"type": "string"},
            },
            "required": ["title", "source_type", "url", "confidence", "notes"],
        }
        candidate_schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "part_number": {"type": "string"},
                "manufacturer": {"type": "string"},
                "description": {"type": "string"},
                "supplier": {"type": "string"},
                "supplier_part_number": {"type": "string"},
                "supplier_url": {"type": "string"},
                "supported_recipe_id": {"type": "string"},
                "confidence": {
                    "type": "string",
                    "enum": ["high", "medium", "low"],
                },
                "complexity": {
                    "type": "string",
                    "enum": ["simple", "moderate", "complex", "unknown"],
                },
                "source_coverage": {"type": "array", "items": {"type": "string"}},
                "capability_notes": {"type": "array", "items": {"type": "string"}},
                "datasheet_sources": {"type": "array", "items": source_schema},
                "extraction_notes": {"type": "array", "items": {"type": "string"}},
                "warnings": {"type": "array", "items": {"type": "string"}},
            },
            "required": [
                "part_number",
                "manufacturer",
                "description",
                "supplier",
                "supplier_part_number",
                "supplier_url",
                "supported_recipe_id",
                "confidence",
                "complexity",
                "source_coverage",
                "capability_notes",
                "datasheet_sources",
                "extraction_notes",
                "warnings",
            ],
        }
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "summary": {"type": "string"},
                "target_part_number": {"type": "string"},
                "context_part_numbers": {"type": "array", "items": {"type": "string"}},
                "search_audit": {"type": "array", "items": {"type": "string"}},
                "candidates": {"type": "array", "items": candidate_schema},
                "warnings": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["summary", "target_part_number", "context_part_numbers", "search_audit", "candidates", "warnings"],
        }

    def _extract_output_text(self, body: dict[str, Any]) -> str:
        if body.get("status") == "incomplete":
            details = body.get("incomplete_details") or {}
            reason = details.get("reason") if isinstance(details, dict) else details
            raise ValueError(f"OpenAI response was incomplete: {reason or 'unknown reason'}")
        if isinstance(body.get("output_text"), str):
            return body["output_text"]
        for item in body.get("output", []):
            for content in item.get("content", []):
                if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                    return content["text"]
        raise ValueError("OpenAI response did not include output text.")

    def _decision_from_payload(self, payload: dict[str, Any]) -> AIChatDecision:
        action = str(payload.get("action", "unsupported"))
        if action not in {"generate_recipe", "suggest_parts", "answer_question", "unsupported"}:
            action = "unsupported"
        return AIChatDecision(
            action=action,
            assistant_message=str(payload.get("assistant_message") or "I need a bit more detail."),
            recipe_id=str(payload.get("recipe_id") or ""),
            target_part_number=str(payload.get("target_part_number") or ""),
            context_part_numbers=[str(item) for item in payload.get("context_part_numbers", [])],
            suggestions=[
                AISuggestion(
                    recipe_id=str(item.get("recipe_id") or ""),
                    label=str(item.get("label") or ""),
                    reason=str(item.get("reason") or ""),
                    status=str(item.get("status") or "unsupported"),
                )
                for item in payload.get("suggestions", [])
                if isinstance(item, dict)
            ],
            confidence=float(payload.get("confidence") or 0),
            token_count=int(payload.get("_token_count") or 0),
        )

    def _datasheet_response_from_payload(self, query: str, payload: dict[str, Any]) -> DatasheetSearchResponse:
        candidates = []
        for item in payload.get("candidates", []):
            if not isinstance(item, dict):
                continue
            sources = []
            for source in item.get("datasheet_sources", []):
                if isinstance(source, dict):
                    sources.append(
                        DatasheetSource(
                            title=str(source.get("title") or ""),
                            source_type=str(source.get("source_type") or "other"),
                            url=str(source.get("url") or ""),
                            confidence=str(source.get("confidence") or "uncertain"),
                            notes=str(source.get("notes") or ""),
                        )
                    )
            candidates.append(
                DatasheetCandidate(
                    part_number=str(item.get("part_number") or ""),
                    manufacturer=str(item.get("manufacturer") or ""),
                    description=str(item.get("description") or ""),
                    supplier=str(item.get("supplier") or ""),
                    supplier_part_number=str(item.get("supplier_part_number") or ""),
                    supplier_url=str(item.get("supplier_url") or ""),
                    supported_recipe_id=str(item.get("supported_recipe_id") or ""),
                    confidence=str(item.get("confidence") or "low"),
                    complexity=str(item.get("complexity") or "unknown"),
                    source_coverage=[str(note) for note in item.get("source_coverage", [])],
                    capability_notes=[str(note) for note in item.get("capability_notes", [])],
                    datasheet_sources=sources,
                    extraction_notes=[str(note) for note in item.get("extraction_notes", [])],
                    warnings=[str(warning) for warning in item.get("warnings", [])],
                )
            )
        return DatasheetSearchResponse(
            query=query,
            live_search_used=True,
            provider="openai_web_search",
            summary=str(payload.get("summary") or "Live datasheet search completed."),
            target_part_number=str(payload.get("target_part_number") or ""),
            context_part_numbers=[str(item) for item in payload.get("context_part_numbers", [])],
            search_audit=[str(item) for item in payload.get("search_audit", [])],
            candidates=candidates,
            warnings=[str(warning) for warning in payload.get("warnings", [])],
            token_count=int(payload.get("_token_count") or 0),
        )

    def _needs_deeper_datasheet_search(self, response: DatasheetSearchResponse, intent=None) -> bool:
        if not response.live_search_used or not response.candidates:
            return False

        target_keys = {
            normalise_part_number(part)
            for part in (intent.target_part_numbers if intent else [])
            if part
        }
        response_target = normalise_part_number(response.target_part_number)
        if response_target:
            target_keys.add(response_target)
        if not target_keys:
            return False

        for candidate in response.candidates[:3]:
            candidate_key = normalise_part_number(candidate.part_number)
            if candidate_key and candidate_key not in target_keys:
                continue
            if candidate.supported_recipe_id:
                continue
            if len(candidate.datasheet_sources) < 2:
                return True
            if not self._has_reference_design_source(candidate):
                return True
        return False

    def _merge_datasheet_responses(
        self,
        primary: DatasheetSearchResponse,
        deeper: DatasheetSearchResponse,
    ) -> DatasheetSearchResponse:
        primary.token_count += deeper.token_count
        primary.search_audit = self._dedupe_strings([*primary.search_audit, *deeper.search_audit])
        primary.warnings = self._dedupe_strings([*primary.warnings, *deeper.warnings])
        if deeper.summary and deeper.summary not in primary.summary:
            primary.summary = f"{primary.summary} Follow-up search: {deeper.summary}"

        by_part = {normalise_part_number(candidate.part_number): candidate for candidate in primary.candidates}
        for deeper_candidate in deeper.candidates:
            key = normalise_part_number(deeper_candidate.part_number)
            existing = by_part.get(key)
            if existing is None:
                primary.candidates.append(deeper_candidate)
                by_part[key] = deeper_candidate
                continue
            existing.datasheet_sources = self._merge_sources(
                existing.datasheet_sources,
                deeper_candidate.datasheet_sources,
            )
            existing.extraction_notes = self._dedupe_strings(
                [*existing.extraction_notes, *deeper_candidate.extraction_notes]
            )
            existing.warnings = self._dedupe_strings([*existing.warnings, *deeper_candidate.warnings])
            existing.source_coverage = self._dedupe_strings(
                [*existing.source_coverage, *deeper_candidate.source_coverage]
            )
            existing.capability_notes = self._dedupe_strings(
                [*existing.capability_notes, *deeper_candidate.capability_notes]
            )
            if existing.complexity in {"unknown", "simple"} and deeper_candidate.complexity != "unknown":
                existing.complexity = deeper_candidate.complexity
        return primary

    def _mark_incomplete_source_coverage(self, response: DatasheetSearchResponse) -> None:
        for candidate in response.candidates:
            if candidate.supported_recipe_id:
                continue
            if self._has_reference_design_source(candidate):
                continue
            warning = (
                f"No linked reference design, evaluation board, application note, or design-file source was verified "
                f"for {candidate.manufacturer} {candidate.part_number}; treat the draft recipe as incomplete."
            )
            if warning not in candidate.warnings:
                candidate.warnings.append(warning)
            if warning not in response.warnings:
                response.warnings.append(warning)

    def _has_reference_design_source(self, candidate: DatasheetCandidate) -> bool:
        useful_source_types = {"application_note", "reference_design", "evaluation_board", "design_file"}
        return any(source.source_type in useful_source_types for source in candidate.datasheet_sources)

    def _merge_sources(
        self,
        primary: list[DatasheetSource],
        secondary: list[DatasheetSource],
    ) -> list[DatasheetSource]:
        merged = list(primary)
        seen = {self._source_key(source) for source in merged}
        for source in secondary:
            key = self._source_key(source)
            if key not in seen:
                merged.append(source)
                seen.add(key)
        return merged

    def _source_key(self, source: DatasheetSource) -> str:
        return source.url.strip().lower() or f"{source.title.strip().lower()}::{source.source_type}"

    def _dedupe_strings(self, values: list[str]) -> list[str]:
        result = []
        for value in values:
            if value and value not in result:
                result.append(value)
        return result

    def _part_intent_summary(self, message: str) -> dict[str, Any]:
        intent = analyse_part_intent(message)
        return {
            "target_part_numbers": intent.target_part_numbers,
            "context_part_numbers": intent.context_part_numbers,
            "all_part_numbers": intent.all_part_numbers,
            "has_generation_intent": intent.has_generation_intent,
            "has_exploratory_intent": intent.has_exploratory_intent,
            "has_category_request": intent.has_category_request,
            "complexity": intent.complexity,
            "complexity_reasons": intent.complexity_reasons,
            "mentions": [mention.__dict__ for mention in intent.mentions],
        }

    def _complexity_limit_sentence(self, intent) -> str:
        if intent.complexity == "complex":
            return (
                " For this class of part, Trace Labs can only create a review skeleton until the reference design, "
                "layout guidance, pins, passives, and operating conditions are checked."
            )
        if intent.complexity == "moderate":
            return " I will keep context-dependent values as questions or reviewable starter values rather than silently guessing."
        return ""

    def _fallback_capability_notes(self, intent) -> list[str]:
        notes = [
            "No verified local recipe exists yet; Trace Labs can only create a reviewable draft shell for this part.",
            "Datasheet, pin map, support passives, symbol, and footprint must be reviewed before fabrication.",
        ]
        if intent.complexity == "complex":
            notes.append(
                "This looks like a complex subsystem; the draft cannot safely replace a manufacturer reference design."
            )
        return notes

    def _fallback_decision(
        self,
        message: str,
        available_recipes: list[dict[str, Any]],
        current_block: CircuitBlock | None = None,
        draft_block: CircuitBlock | None = None,
    ) -> AIChatDecision:
        text = message.lower()
        intent = analyse_part_intent(message)
        has_context = current_block is not None or draft_block is not None
        if has_context and any(term in text for term in ["why", "compare", "better", "this one", "that one"]):
            recipe_name = current_block.block_name if current_block else draft_block.block_name if draft_block else "this part"
            return AIChatDecision(
                action="answer_question",
                confidence=0.8,
                target_part_number=intent.target_part_numbers[0] if intent.target_part_numbers else "",
                context_part_numbers=intent.context_part_numbers,
                assistant_message=(
                    f"{recipe_name} was selected because Trace Labs has enough recipe context to prepare a "
                    "reviewable KiCad block for it. Review the assumptions, support components, symbol, and "
                    "footprint before fabrication."
                ),
            )

        matched_recipe = None
        if intent.target_part_numbers or (intent.has_generation_intent and not intent.context_part_numbers):
            matched_recipe = self._matching_supported_recipe(text, available_recipes, intent.target_part_numbers)
        if matched_recipe:
            target_part_number = str(matched_recipe.get("mpn") or "")
            if not target_part_number and intent.target_part_numbers:
                target_part_number = intent.target_part_numbers[0]
            return AIChatDecision(
                action="generate_recipe",
                recipe_id=str(matched_recipe.get("id") or ""),
                target_part_number=target_part_number,
                context_part_numbers=intent.context_part_numbers,
                confidence=0.95,
                assistant_message=(
                    f"I found {matched_recipe.get('display_name')}. I can generate that supported recipe, "
                    "then ask you to confirm voltage, address, interface, and pull-ups."
                ),
            )
        part_number = intent.target_part_numbers[0] if intent.target_part_numbers else ""
        if part_number:
            limit_note = self._complexity_limit_sentence(intent)
            return AIChatDecision(
                action="suggest_parts",
                confidence=0.7,
                target_part_number=part_number,
                context_part_numbers=intent.context_part_numbers,
                assistant_message=(
                    f"Trace Labs does not have a verified local recipe for {part_number} yet. "
                    "I will search datasheet sources and prepare an AI-proposed draft recipe that requires review "
                    f"before schematic insertion.{limit_note}"
                ),
                suggestions=[
                    AISuggestion(
                        recipe_id="",
                        label=f"{part_number} draft recipe",
                        reason="Exact unsupported part request; create a reviewable AI-proposed draft recipe.",
                        status="planned",
                    )
                ],
            )
        if intent.has_category_request:
            limit_note = self._complexity_limit_sentence(intent)
            return AIChatDecision(
                action="suggest_parts",
                confidence=0.7,
                context_part_numbers=intent.context_part_numbers,
                assistant_message=(
                    "I can search for candidate parts and discuss tradeoffs. Trace Labs will only create a draft "
                    f"schematic recipe after you choose a specific component.{limit_note}"
                ),
            )
        if has_context:
            return AIChatDecision(
                action="answer_question",
                confidence=0.6,
                context_part_numbers=intent.context_part_numbers,
                assistant_message=(
                    "I can answer questions about the current generated block, its assumptions, warnings, pull-ups, "
                    "address straps, symbol/footprint confidence, or KiCad insertion options."
                ),
            )
        return AIChatDecision(
            action="unsupported",
            confidence=0.5,
            context_part_numbers=intent.context_part_numbers,
            assistant_message=(
                "I can generate supported local recipes or prepare AI-proposed draft recipes from exact part requests."
            ),
        )

    def _matching_supported_recipe(
        self,
        text: str,
        available_recipes: list[dict[str, Any]],
        target_parts: list[str] | None = None,
    ) -> dict[str, Any] | None:
        normalised_targets = {normalise_part_number(part) for part in target_parts or []}
        for recipe in available_recipes:
            tokens = [
                str(recipe.get("id") or ""),
                str(recipe.get("mpn") or ""),
                str(recipe.get("display_name") or ""),
            ]
            if normalised_targets and not any(normalise_part_number(token) in normalised_targets for token in tokens):
                continue
            if any(token and token.lower() in text for token in tokens):
                return recipe
        return None

    def _fallback_datasheet_search(
        self,
        query: str,
        available_recipes: list[dict[str, Any]],
    ) -> DatasheetSearchResponse:
        text = query.lower()
        intent = analyse_part_intent(query)
        candidates: list[DatasheetCandidate] = []
        lcsc_id = self._extract_lcsc_id(query)
        target_part = intent.target_part_numbers[0] if intent.target_part_numbers else ""
        supported_recipe = None
        if target_part or (intent.has_generation_intent and not intent.context_part_numbers):
            supported_recipe = self._matching_supported_recipe(text, available_recipes, intent.target_part_numbers)
        if target_part:
            supported_recipe = self._matching_supported_recipe(target_part.lower(), available_recipes, [target_part])
        if supported_recipe is None and self._matches_environmental_sensor_category(text) and not target_part:
            supported_recipe = available_recipes[0] if available_recipes else None
        if supported_recipe is None and self._matches_power_converter_category(text) and not target_part:
            candidates.extend(self._power_converter_fallback_candidates(lcsc_id))
        if supported_recipe:
            part_number = str(supported_recipe.get("mpn") or supported_recipe.get("id") or "SupportedPart")
            manufacturer = str(supported_recipe.get("manufacturer") or "Verified local recipe")
            display_name = str(supported_recipe.get("display_name") or part_number)
            candidates.append(
                DatasheetCandidate(
                    part_number=part_number,
                    manufacturer=manufacturer,
                    description=f"{display_name} is available as a verified local Trace Labs recipe.",
                    supplier="LCSC" if lcsc_id else "",
                    supplier_part_number=lcsc_id,
                    supplier_url=self._lcsc_url(lcsc_id),
                    supported_recipe_id=str(supported_recipe.get("id") or ""),
                    confidence="medium",
                    complexity="simple",
                    source_coverage=["local verified recipe"],
                    capability_notes=["Trace Labs can generate this recipe deterministically and then ask setup questions."],
                    datasheet_sources=[
                        DatasheetSource(
                            title=f"{display_name} local recipe reference",
                            source_type="local_recipe",
                            url="",
                            confidence="local_recipe_verified",
                            notes="Local fallback source; enable OpenAI web search for live URLs.",
                        )
                    ],
                    extraction_notes=[
                        "Trace Labs has a deterministic local recipe for this candidate.",
                        "Live datasheet URLs were not fetched in fallback mode.",
                    ],
                    warnings=["Verify the live manufacturer datasheet before production."],
                )
            )
        if target_part and not candidates:
            candidates.append(
                DatasheetCandidate(
                    part_number=target_part,
                    manufacturer="Unknown manufacturer",
                    description=(
                        f"{target_part} was named by the user. Live datasheet search is unavailable, so Trace Labs "
                        "can only create a generic draft recipe shell that needs datasheet review."
                    ),
                    supplier="LCSC" if lcsc_id else "",
                    supplier_part_number=lcsc_id,
                    supplier_url=self._lcsc_url(lcsc_id),
                    supported_recipe_id="",
                    confidence="medium",
                    complexity=intent.complexity,
                    source_coverage=["target part number only"],
                    capability_notes=self._fallback_capability_notes(intent),
                    datasheet_sources=[
                        DatasheetSource(
                            title=f"{target_part} datasheet source needed",
                            source_type="other",
                            url="",
                            confidence="uncertain",
                            notes="Enable live datasheet search to attach official source URLs.",
                        )
                    ],
                    extraction_notes=[
                        "No verified Trace Labs recipe exists yet.",
                        "This draft was created from the requested part number, not from a verified local recipe.",
                    ],
                    warnings=[
                        "Official datasheet, pin map, recommended circuit, symbol, and footprint must be verified.",
                        (
                            "Any context-dependent values need cited evidence, calculated inputs, or reviewable starter "
                            "defaults; use TBD only if the user explicitly says they are not sure."
                        ),
                    ],
                )
            )
        return DatasheetSearchResponse(
            query=query,
            live_search_used=False,
            provider="local_fallback",
            summary=(
                "Live datasheet search is unavailable, so Trace Labs used local recipe knowledge."
                if candidates
                else "No local datasheet candidate matched this request."
            ),
            target_part_number=target_part,
            context_part_numbers=intent.context_part_numbers,
            search_audit=[
                (
                    "Local fallback does not fetch live datasheets during the comparison step; "
                    "selected unsupported parts must run datasheet/reference extraction before schematic generation."
                )
            ],
            candidates=candidates,
            warnings=["Set OPENAI_API_KEY and DATASHEET_LIVE_SEARCH_ENABLED=true to use live datasheet search."],
        )

    def _extract_lcsc_id(self, message: str) -> str:
        match = re.search(r"\bC\d{3,}\b", message.upper())
        return match.group(0) if match else ""

    def _matches_environmental_sensor_category(self, text: str) -> bool:
        excluded_sensor_categories = [
            "distance",
            "lidar",
            "proximity",
            "range",
            "ranging",
            "time of flight",
            "tof",
        ]
        if any(term in text for term in excluded_sensor_categories):
            return False
        return any(term in text for term in ["temperature", "temp", "environmental", "humidity", "pressure"])

    def _matches_power_converter_category(self, text: str) -> bool:
        return any(term in text for term in [
            "buck", "boost", "step-down", "step down", "dc-dc", "dcdc",
            "switching regulator", "switch mode", "smps",
        ])

    def _matches_gps_gnss_category(self, text: str) -> bool:
        return any(term in text for term in ["gps", "gnss", "navigation", "positioning", "geolocation"])

    def _matches_imu_category(self, text: str) -> bool:
        excluded = ["temperature", "humidity", "pressure", "gas", "air quality"]
        if any(term in text for term in excluded):
            return False
        return any(term in text for term in [
            "imu", "accelerometer", "gyroscope", "gyro", "inertial", "motion sensor",
            "6-axis", "6 axis", "9-axis", "9 axis",
        ])

    def _make_fallback_candidates(
        self,
        parts: list[tuple[str, str, str, str]],
        capability_notes: list[str],
        warnings: list[str],
        complexity: str = "moderate",
    ) -> list[DatasheetCandidate]:
        return [
            DatasheetCandidate(
                part_number=mpn,
                manufacturer=mfr,
                description=desc,
                supplier="LCSC" if supplier_pn else "",
                supplier_part_number=supplier_pn,
                supplier_url=self._lcsc_url(supplier_pn),
                supported_recipe_id="",
                confidence="medium",
                complexity=complexity,
                source_coverage=["local fallback candidate list"],
                capability_notes=[
                    "No verified Trace Labs recipe yet; extraction will build a reviewable draft.",
                    *capability_notes,
                ],
                datasheet_sources=[
                    DatasheetSource(
                        title=f"{mpn} datasheet",
                        source_type="other",
                        url="",
                        confidence="uncertain",
                        notes="Enable live datasheet search to attach official source URLs.",
                    )
                ],
                extraction_notes=[
                    "Live datasheet search unavailable; values shown are from local fallback candidate list.",
                    "Run datasheet extraction after selecting this part to fill in pin map and support values.",
                ],
                warnings=warnings,
            )
            for mpn, mfr, supplier_pn, desc in parts
        ]

    def _power_converter_fallback_candidates(self, _lcsc_id: str) -> list[DatasheetCandidate]:
        parts = [
            ("AP63205WU-7", "Diodes Incorporated", "C2071056",
             "2A synchronous buck converter, 3.8–32V input, adjustable output down to 0.8V, SOT-23-6."),
            ("TPS54302DDCR", "Texas Instruments", "",
             "3A synchronous buck converter, 4.5–28V input, adjustable output, SOT-23-6."),
            ("TPS5401DGQR", "Texas Instruments", "C58517",
             "1A non-synchronous buck converter, 5.5–36V input, adjustable output, HSOP-8."),
            ("TPS5430DDAR", "Texas Instruments", "C9864",
             "3A non-synchronous buck converter, 5.5–36V input, adjustable output, SO-8."),
        ]
        return self._make_fallback_candidates(
            parts,
            capability_notes=["Verify switching frequency, inductor, and output capacitor values against the datasheet."],
            warnings=[
                "Verify Vin, Vout, Iout, switching frequency, inductor, and output capacitor against the datasheet.",
                "Buck converter PCB layout is performance-critical; follow manufacturer EVM/layout guidance.",
            ],
        )

    def _gps_gnss_fallback_candidates(self, _lcsc_id: str) -> list[DatasheetCandidate]:
        parts = [
            ("NEO-M9N-00B", "u-blox", "",
             "Multi-band GNSS module (GPS/GLONASS/Galileo/BeiDou), UART/I2C/SPI, 3.3V, −167 dBm sensitivity."),
            ("NEO-M8N-0", "u-blox", "C6330769",
             "Multi-GNSS module (GPS/GLONASS/Galileo/BeiDou), UART/I2C/SPI/USB, 3.3V, compact LCC package."),
            ("SAM-M10Q-00B", "u-blox", "C5443880",
             "Ultra-compact GNSS module, UART/I2C/SPI, 1.71–1.89V core / 3.3V I/O, very low power."),
            ("MAX-M10S-00B", "u-blox", "",
             "Smallest u-blox GNSS module, UART/I2C/SPI, 1.71–1.89V core / 3.3V I/O, automotive-grade option."),
        ]
        return self._make_fallback_candidates(
            parts,
            capability_notes=[
                "GNSS modules require an external passive antenna or integrated patch antenna board.",
                "Confirm UART/I2C/SPI interface selection matches your host MCU pinout and firmware library.",
            ],
            warnings=[
                "Verify antenna matching network, supply filtering, and RF keep-out area against the datasheet.",
                "GPS/GNSS modules require clear sky view; evaluate antenna placement on the PCB early.",
            ],
            complexity="complex",
        )

    def _imu_fallback_candidates(self, _lcsc_id: str) -> list[DatasheetCandidate]:
        parts = [
            ("BMI270", "Bosch Sensortec", "",
             "6-axis IMU (accel + gyro), I2C/SPI, 1.8V (5V-tolerant I/O on breakout), low power, wearable-grade."),
            ("LSM6DSO", "STMicroelectronics", "",
             "6-axis IMU (accel + gyro), I2C/SPI, 1.71–3.6V, embedded FIFO, machine-learning core option."),
            ("ICM-42688-P", "TDK InvenSense", "",
             "6-axis IMU (accel + gyro), I2C/SPI, 1.8V (level-shifted), high-bandwidth, small LGA package."),
            ("MPU-6050", "TDK InvenSense", "",
             "6-axis IMU (accel + gyro), I2C only, 3.3V, integrated DMP, widely supported in firmware."),
        ]
        return self._make_fallback_candidates(
            parts,
            capability_notes=[
                "Confirm I2C/SPI interface selection; some variants support both, others are I2C-only.",
                "Supply voltage varies by variant; check whether 1.8V or 3.3V logic is needed.",
            ],
            warnings=[
                "Verify supply voltage, I/O level, and decoupling capacitor values against the datasheet.",
                "IMU placement and orientation relative to the board axis must match firmware conventions.",
            ],
        )

    def _lcsc_url(self, lcsc_id: str) -> str:
        return f"https://www.lcsc.com/datasheet/{lcsc_id}.pdf" if lcsc_id else ""

    def _block_summary(self, block: CircuitBlock | None) -> dict[str, Any] | None:
        if block is None:
            return None
        return {
            "block_name": block.block_name,
            "block_slug": block.block_slug,
            "status": block.status,
            "main_component": {
                "value": block.main_component.value,
                "mpn": block.main_component.mpn,
                "manufacturer": block.main_component.manufacturer,
                "supplier": block.main_component.supplier,
                "supplier_part_number": block.main_component.supplier_part_number,
                "purpose": block.main_component.purpose,
                "symbol": block.main_component.symbol,
                "footprint": block.main_component.footprint,
                "footprint_confidence": block.main_component.footprint_confidence,
            },
            "selected_options": block.selected_options,
            "assumptions": block.assumptions,
            "warnings": [warning.message for warning in block.validation_warnings],
        }
