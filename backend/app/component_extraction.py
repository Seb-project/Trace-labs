from __future__ import annotations

import base64
import html
import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

import httpx

from .ai_service import TraceLabsAIService
from .models import (
    CircuitNet,
    ComponentExtractionJobResponse,
    DatasheetCandidate,
    PinDefinition,
    ReferenceCircuitExtraction,
    SourceChunk,
    SupportRequirement,
)
from .part_intent import normalise_part_number
from .storage import JsonStore


EXTRACT_CANDIDATE_PREFIX = "extract_candidate::"
MAX_SOURCE_BYTES = 8_000_000
MAX_CHUNKS_FOR_MODEL = 28
SOURCE_FETCH_TIMEOUT_SECONDS = float(os.environ.get("TRACELABS_SOURCE_FETCH_TIMEOUT_SECONDS", "15"))
KNOWN_PIN_NAMES = {
    "ADDR",
    "AD0",
    "AGND",
    "AVIN",
    "AVDD",
    "BIAS",
    "BOOT",
    "BOOTN",
    "BST",
    "COMP",
    "CS",
    "CSB",
    "CSN",
    "DGND",
    "DNC",
    "DRDY",
    "DVDD",
    "EN",
    "EP",
    "FB",
    "FSYNC",
    "GND",
    "GNDA",
    "GPIO",
    "GPIO0",
    "GPIO1",
    "GPIO2",
    "GPIO3",
    "GPIO4",
    "HINTN",
    "INT",
    "INT1",
    "INT2",
    "INTVCC",
    "IOVDD",
    "LX",
    "MISO",
    "MOSI",
    "MODE",
    "NC",
    "NRST",
    "PG",
    "PGND",
    "PGOOD",
    "PH",
    "PS0",
    "PS1",
    "PVIN",
    "RESET",
    "RESV_NC",
    "RT",
    "RT_SYNC",
    "RUN",
    "RST",
    "RSTN",
    "SA0",
    "SCK",
    "SCL",
    "SCLK",
    "SDA",
    "SDI",
    "SDO",
    "SS",
    "SS_TR",
    "SW",
    "SYNC",
    "TRSS",
    "TR_SS",
    "VC",
    "VCC",
    "VDD",
    "VDDH",
    "VDDIO",
    "VDDL",
    "VIN",
    "VSS",
    "WAKE",
    "XSHUT",
}


def encode_candidate_choice(candidate: DatasheetCandidate) -> str:
    raw = candidate.model_dump_json().encode("utf-8")
    return EXTRACT_CANDIDATE_PREFIX + base64.urlsafe_b64encode(raw).decode("ascii")


def decode_candidate_choice(value: str) -> DatasheetCandidate | None:
    if not value.startswith(EXTRACT_CANDIDATE_PREFIX):
        return None
    encoded = value.removeprefix(EXTRACT_CANDIDATE_PREFIX)
    try:
        raw = base64.urlsafe_b64decode(encoded.encode("ascii"))
        return DatasheetCandidate.model_validate_json(raw)
    except Exception:
        return None


class ComponentExtractionService:
    def __init__(self, ai_service: TraceLabsAIService, data_dir: Path | None = None):
        self.ai_service = ai_service
        self._jobs: dict[str, ComponentExtractionJobResponse] = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="tracelabs-extract")
        self.extraction_cache = JsonStore(data_dir / "component_extractions.json") if data_dir else None

    def start(self, candidate: DatasheetCandidate, *, run_inline: bool = False) -> ComponentExtractionJobResponse:
        job_id = str(uuid4())
        cached = self._read_cached_extraction(candidate)
        if cached is not None:
            extraction, cached_candidate = cached
            resolved_candidate = self._merge_cached_candidate(candidate, cached_candidate)
            job = ComponentExtractionJobResponse(
                job_id=job_id,
                status="ready",
                progress=1.0,
                message=(
                    f"Loaded cached datasheet extraction for "
                    f"{resolved_candidate.manufacturer} {resolved_candidate.part_number}. "
                    "Readable documentation and cited circuit evidence are ready for review."
                ),
                candidate=resolved_candidate,
                extraction=extraction,
            )
            self._store(job)
            return self.get(job_id)

        job = ComponentExtractionJobResponse(
            job_id=job_id,
            status="queued",
            progress=0.0,
            message=(
                f"Queued datasheet extraction for {self._candidate_label(candidate)}. "
                "Candidate documentation links are selected, but Trace Labs has not opened them yet."
            ),
            candidate=candidate,
        )
        self._store(job)
        if run_inline:
            self._run(job_id)
        else:
            self._executor.submit(self._run, job_id)
        return self.get(job_id)

    def get(self, job_id: str) -> ComponentExtractionJobResponse:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return ComponentExtractionJobResponse(
                    job_id=job_id,
                    status="failed",
                    progress=1.0,
                    message="Extraction job was not found.",
                    errors=["Extraction job was not found."],
                )
            return job.model_copy(deep=True)

    def _run(self, job_id: str) -> None:
        job = self.get(job_id)
        candidate = job.candidate
        if candidate is None:
            self._fail(job_id, "No candidate was supplied for extraction.")
            return

        try:
            self._update(
                job_id,
                "fetching_sources",
                0.15,
                (
                    f"Opening selected datasheet and reference URLs for {self._candidate_label(candidate)}. "
                    "Trace Labs is still looking for readable source text."
                ),
            )
            download_errors: list[str] = []
            chunks = self._fetch_source_chunks(candidate, download_errors)
            if not chunks:
                self._fail(
                    job_id,
                    "No readable datasheet text could be downloaded from the selected sources.",
                    errors=download_errors
                    or [
                        "Trace Labs had source URLs for this candidate, but none produced readable text for extraction."
                    ],
                )
                return

            self._update(job_id, "sources_found", 0.32, self._readable_source_message(candidate, chunks))
            self._update(
                job_id,
                "extracting",
                0.45,
                (
                    "Readable datasheet/reference text was found. "
                    "Trace Labs is now extracting pin map, required passives, and reference nets."
                ),
            )
            extraction = self._extract_reference_circuit(candidate, chunks)

            self._update(
                job_id,
                "acquiring_cad",
                0.72,
                (
                    "Cited circuit evidence was extracted. "
                    "Trace Labs is checking symbol and footprint requirements for the selected part."
                ),
            )
            extraction.extraction_notes.extend(self._cad_notes(candidate))

            self._update(
                job_id,
                "validating",
                0.88,
                "Validating extracted datasheet citations, pins, support parts, and nets.",
            )
            errors = self._validation_errors(extraction)
            if errors:
                self._fail(
                    job_id,
                    self._validation_failure_message(candidate, errors, extraction),
                    errors=errors,
                    extraction=extraction,
                )
                return

            ready_job = ComponentExtractionJobResponse(
                job_id=job_id,
                status="ready",
                progress=1.0,
                message=(
                    f"Extraction ready for {candidate.manufacturer} {candidate.part_number}. "
                    "Trace Labs found cited pins and support components."
                ),
                candidate=candidate,
                extraction=extraction,
            )
            self._store(ready_job)
            self._write_cached_extraction(candidate, extraction)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, httpx.HTTPError) as exc:
            self._fail(job_id, self._exception_failure_message(candidate, exc))

    def _candidate_cache_key(self, candidate: DatasheetCandidate) -> str:
        part_key = normalise_part_number(candidate.part_number)
        if part_key:
            return f"v1:part:{part_key}"
        fallback = normalise_part_number(f"{candidate.manufacturer} {candidate.description}")
        return f"v1:fallback:{fallback}"

    def _read_cached_extraction(
        self,
        candidate: DatasheetCandidate,
    ) -> tuple[ReferenceCircuitExtraction, DatasheetCandidate | None] | None:
        if self.extraction_cache is None:
            return None
        try:
            entries = self.extraction_cache.read_dict()
            entry = entries.get(self._candidate_cache_key(candidate))
            if not isinstance(entry, dict):
                return None
            extraction = ReferenceCircuitExtraction.model_validate(entry.get("extraction"))
            cached_candidate = None
            if isinstance(entry.get("candidate"), dict):
                cached_candidate = DatasheetCandidate.model_validate(entry.get("candidate"))
            return extraction, cached_candidate
        except (json.JSONDecodeError, OSError, ValueError, TypeError):
            return None

    def _write_cached_extraction(
        self,
        candidate: DatasheetCandidate,
        extraction: ReferenceCircuitExtraction,
    ) -> None:
        if self.extraction_cache is None:
            return
        try:
            entries = self.extraction_cache.read_dict()
            entries[self._candidate_cache_key(candidate)] = {
                "saved_at": datetime.now(timezone.utc).isoformat(),
                "candidate": candidate.model_dump(),
                "extraction": extraction.model_dump(),
            }
            if len(entries) > 50:
                entries = dict(
                    sorted(
                        entries.items(),
                        key=lambda item: str(item[1].get("saved_at", "")) if isinstance(item[1], dict) else "",
                    )[-50:]
                )
            self.extraction_cache.write_dict(entries)
        except (OSError, TypeError, ValueError):
            return

    def _merge_cached_candidate(
        self,
        candidate: DatasheetCandidate,
        cached_candidate: DatasheetCandidate | None,
    ) -> DatasheetCandidate:
        if cached_candidate is None:
            return candidate
        updates: dict[str, Any] = {}
        for field_name in [
            "manufacturer",
            "description",
            "supplier",
            "supplier_part_number",
            "supplier_url",
            "supported_recipe_id",
            "confidence",
            "complexity",
        ]:
            if not getattr(candidate, field_name) and getattr(cached_candidate, field_name):
                updates[field_name] = getattr(cached_candidate, field_name)
        for field_name in [
            "source_coverage",
            "capability_notes",
            "datasheet_sources",
            "extraction_notes",
            "warnings",
        ]:
            if not getattr(candidate, field_name) and getattr(cached_candidate, field_name):
                updates[field_name] = getattr(cached_candidate, field_name)
        return candidate.model_copy(update=updates) if updates else candidate

    def _candidate_label(self, candidate: DatasheetCandidate) -> str:
        label = " ".join(
            part.strip()
            for part in [candidate.manufacturer, candidate.part_number]
            if part and part.strip()
        )
        return label or "the selected part"

    def _readable_source_message(self, candidate: DatasheetCandidate, chunks: list[SourceChunk]) -> str:
        source_urls = list(dict.fromkeys(chunk.source_url for chunk in chunks if chunk.source_url))
        source_count = len(source_urls) or len(chunks)
        source_label = "source" if source_count == 1 else "sources"
        return (
            f"Found readable datasheet/reference text for {self._candidate_label(candidate)} "
            f"from {source_count} {source_label}. Extracting pins and support circuit next."
        )

    def _validation_failure_message(
        self,
        candidate: DatasheetCandidate,
        errors: list[str],
        extraction: ReferenceCircuitExtraction,
    ) -> str:
        has_pin_failure = any("pin map" in error.lower() for error in errors)
        if has_pin_failure and extraction.source_chunks:
            return (
                f"Trace Labs found readable datasheet/reference text for {self._candidate_label(candidate)}, "
                "but could not extract a complete cited pin map. "
                "It will not generate a placeholder schematic."
            )
        if extraction.source_chunks:
            missing_evidence = "; ".join(errors[:3])
            if len(errors) > 3:
                missing_evidence = f"{missing_evidence}; and {len(errors) - 3} more validation issue(s)"
            return (
                f"Trace Labs found readable datasheet/reference text for {self._candidate_label(candidate)}, "
                f"but the extracted circuit evidence was incomplete: {missing_evidence}. "
                "It will not generate a placeholder schematic."
            )
        return "Datasheet extraction was incomplete; Trace Labs will not generate a placeholder schematic."

    def _exception_failure_message(self, candidate: DatasheetCandidate, exc: Exception) -> str:
        detail = str(exc).replace("\n", " ").strip()
        if len(detail) > 180:
            detail = f"{detail[:177]}..."
        timeout_like = isinstance(exc, TimeoutError) or "timed out" in detail.lower() or "timeout" in detail.lower()
        if timeout_like:
            return (
                f"Datasheet extraction timed out for {self._candidate_label(candidate)}. "
                "Trace Labs may have been waiting on source download or pin extraction; "
                "try again or choose a more direct official datasheet source."
            )
        return f"Datasheet extraction failed for {self._candidate_label(candidate)}: {detail or type(exc).__name__}"

    def _fetch_source_chunks(self, candidate: DatasheetCandidate, download_errors: list[str]) -> list[SourceChunk]:
        chunks: list[SourceChunk] = []
        seen_urls: set[str] = set()
        source_queue = [
            (source.url, source.title, "selected")
            for source in candidate.datasheet_sources[:6]
            if source.url
        ]
        source_index = 0
        while source_queue and source_index < 10:
            source_url, source_title, source_kind = source_queue.pop(0)
            if not source_url or source_url in seen_urls:
                continue
            seen_urls.add(source_url)
            try:
                raw = self._read_url(source_url)
            except Exception as exc:
                download_errors.append(self._download_error(source_title, source_url, exc))
                continue
            source_index += 1
            pages = self._extract_pages(raw, source_url)
            if not pages:
                download_errors.append(
                    f"{source_title or source_url}: downloaded {source_url}, but no readable text was extracted."
                )
            for page_number, text in pages:
                for chunk_number, chunk_text in enumerate(self._chunk_text(text), start=1):
                    chunks.append(
                        SourceChunk(
                            chunk_id=f"S{source_index}P{page_number or 0}C{chunk_number}",
                            source_url=source_url,
                            title=source_title,
                            page=page_number,
                            text=chunk_text,
                        )
                    )
            if source_kind == "selected":
                link_text = "\n".join(text for _, text in pages)
                for linked_url in self._discover_reference_links(raw, link_text, source_url):
                    if linked_url not in seen_urls and all(item[0] != linked_url for item in source_queue):
                        source_queue.append((linked_url, f"Linked reference from {source_title}", "linked"))
        return self._rank_chunks(chunks)[:MAX_CHUNKS_FOR_MODEL]

    def _read_url(self, url: str) -> bytes:
        if url.startswith("file://"):
            return Path(url.removeprefix("file://")).read_bytes()[:MAX_SOURCE_BYTES]
        if url.startswith("/") or url.startswith("."):
            return Path(url).read_bytes()[:MAX_SOURCE_BYTES]
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) TraceLabs/0.1 Safari/537.36"
            ),
            "Accept": "application/pdf,text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8",
        }
        with httpx.Client(follow_redirects=True, timeout=SOURCE_FETCH_TIMEOUT_SECONDS, headers=headers) as client:
            response = client.get(url)
            response.raise_for_status()
            return response.content[:MAX_SOURCE_BYTES]

    def _download_error(self, title: str, url: str, exc: Exception) -> str:
        message = str(exc).replace("\n", " ").strip()
        if len(message) > 180:
            message = f"{message[:177]}..."
        label = title or url
        return f"{label}: could not download {url} ({type(exc).__name__}: {message})"

    def _extract_pages(self, raw: bytes, url: str) -> list[tuple[int | None, str]]:
        if url.lower().endswith(".pdf") or raw.startswith(b"%PDF"):
            try:
                from pypdf import PdfReader

                reader = PdfReader(BytesIO(raw))
                pages = []
                for index, page in enumerate(reader.pages, start=1):
                    text = page.extract_text() or ""
                    if text.strip():
                        pages.append((index, self._clean_text(text)))
                return pages
            except Exception:
                return []
        text = raw.decode("utf-8", errors="ignore")
        text = re.sub(r"<script\b.*?</script>", " ", text, flags=re.I | re.S)
        text = re.sub(r"<style\b.*?</style>", " ", text, flags=re.I | re.S)
        text = re.sub(r"<[^>]+>", " ", text)
        return [(None, self._clean_text(html.unescape(text)))]

    def _discover_reference_links(self, raw: bytes, extracted_text: str, base_url: str) -> list[str]:
        try:
            raw_text = raw.decode("utf-8", errors="ignore")
        except Exception:
            raw_text = ""
        candidates = []
        candidates.extend(re.findall(r"""href=["']([^"']+)["']""", raw_text, flags=re.I))
        candidates.extend(re.findall(r"https?://[^\s)'\"<>]+", raw_text))
        candidates.extend(re.findall(r"https?://[^\s)'\"<>]+", extracted_text))

        relevant_keywords = [
            "reference",
            "refdesign",
            "ref-design",
            "schematic",
            "application",
            "appnote",
            "app-note",
            "hardware",
            "evaluation",
            "evk",
            "design",
            "circuit",
        ]
        discovered = []
        for candidate in candidates:
            cleaned = html.unescape(candidate.strip().rstrip(".,;:)]}"))
            if not cleaned or cleaned.startswith("#") or cleaned.lower().startswith(("mailto:", "javascript:")):
                continue
            url = urljoin(base_url, cleaned)
            lowered = url.lower()
            if not any(keyword in lowered for keyword in relevant_keywords):
                continue
            if url not in discovered:
                discovered.append(url)
            if len(discovered) >= 6:
                break
        return discovered

    def _chunk_text(self, text: str, *, size: int = 3000, overlap: int = 300) -> list[str]:
        text = self._clean_text(text)
        if not text:
            return []
        chunks = []
        start = 0
        while start < len(text):
            chunks.append(text[start : start + size])
            start += size - overlap
        return chunks

    def _rank_chunks(self, chunks: list[SourceChunk]) -> list[SourceChunk]:
        keywords = [
            "pin",
            "pin description",
            "pin-out",
            "connection diagram",
            "application",
            "schematic",
            "recommended",
            "typical",
            "capacitor",
            "diode",
            "schottky",
            "resistor",
            "pull",
            "i2c",
            "spi",
            "sda",
            "scl",
            "xshut",
            "interrupt",
            "avdd",
            "vdd",
            "gnd",
            "layout",
            "reference",
        ]

        def score(chunk: SourceChunk) -> int:
            text = chunk.text.lower()
            title = chunk.title.lower()
            url = chunk.source_url.lower()
            result = sum(text.count(keyword) for keyword in keywords)
            if chunk.page is not None:
                result += 4
            if "datasheet" in title or "datasheet" in url:
                result += 10
            if any(marker in text for marker in ["pin description", "pin-out", "connection diagram"]):
                result += 25
            if any(marker in title or marker in url for marker in ["application_note", "reference", "evaluation"]):
                result += 4
            if "/applications-solutions/" in url:
                result -= 20
            return result

        return sorted(chunks, key=score, reverse=True)

    def _extract_reference_circuit(
        self,
        candidate: DatasheetCandidate,
        chunks: list[SourceChunk],
    ) -> ReferenceCircuitExtraction:
        heuristic = self._heuristic_extract(candidate, chunks)
        if self.ai_service.enabled:
            try:
                ai_extraction = self._extract_with_openai(candidate, chunks)
                return self._merge_extraction_evidence(ai_extraction, heuristic)
            except Exception as exc:
                heuristic.validation_warnings.append(f"OpenAI extraction failed, used local heuristic fallback: {exc}")
                return heuristic
        return heuristic

    def _merge_extraction_evidence(
        self,
        primary: ReferenceCircuitExtraction,
        supplemental: ReferenceCircuitExtraction,
    ) -> ReferenceCircuitExtraction:
        merged_pins = list(primary.pins)
        seen_pins = {(pin.number, pin.name) for pin in merged_pins}
        pins_added = 0
        for pin in supplemental.pins:
            key = (pin.number, pin.name)
            if key in seen_pins:
                continue
            merged_pins.append(pin)
            seen_pins.add(key)
            pins_added += 1

        merged_supports = list(primary.support_requirements)
        seen_supports = {
            (item.type.lower(), item.purpose.lower(), tuple(item.connects))
            for item in merged_supports
        }
        supports_added = 0
        for item in supplemental.support_requirements:
            key = (item.type.lower(), item.purpose.lower(), tuple(item.connects))
            if key in seen_supports:
                continue
            merged_supports.append(item)
            seen_supports.add(key)
            supports_added += 1

        notes = [*primary.extraction_notes]
        warnings = [*primary.validation_warnings]
        if pins_added or supports_added:
            notes.append(
                "Deterministic schematic-label extraction supplemented the AI extraction "
                f"with {pins_added} pin(s) and {supports_added} support component(s)."
            )
        return primary.model_copy(
            update={
                "package": primary.package or supplemental.package,
                "supply_range": primary.supply_range or supplemental.supply_range,
                "interface": primary.interface or supplemental.interface,
                "pins": merged_pins,
                "support_requirements": merged_supports,
                "nets": self._nets_from_pins_and_supports(merged_pins, merged_supports),
                "source_chunks": primary.source_chunks or supplemental.source_chunks,
                "source_urls": primary.source_urls or supplemental.source_urls,
                "unanswered_questions": list(dict.fromkeys([*primary.unanswered_questions, *supplemental.unanswered_questions])),
                "validation_warnings": list(dict.fromkeys(warnings)),
                "extraction_notes": list(dict.fromkeys(notes)),
            }
        )

    def _extract_with_openai(
        self,
        candidate: DatasheetCandidate,
        chunks: list[SourceChunk],
    ) -> ReferenceCircuitExtraction:
        payload = {
            "model": self.ai_service.model,
            "input": [
                {
                    "role": "system",
                    "content": (
                        "Extract a KiCad-ready reference circuit only from the supplied datasheet/reference chunks. "
                        "Every pin and support component must cite at least one chunk_id. Do not invent pins, values, "
                        "or passives. If evidence is missing, leave it out and add an unanswered question."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "candidate": candidate.model_dump(),
                            "chunks": [chunk.model_dump() for chunk in chunks],
                            "requirements": [
                                "Return real package/pin names and pin numbers.",
                                "Return support passives and diodes needed by the reference/typical application circuit.",
                                "Return nets that connect pins and support passives.",
                                (
                                    "Use concise values such as 100 nF, 4.7 kOhm, or DNP. Avoid TBD; only use it "
                                    "when the user explicitly said they are not sure."
                                ),
                            ],
                        },
                    ),
                },
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "tracelabs_reference_circuit_extraction",
                    "strict": True,
                    "schema": self._extraction_schema(),
                }
            },
            "max_output_tokens": self.ai_service.datasheet_max_output_tokens,
        }
        request = Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.ai_service.api_key}",
                "Content-Type": "application/json",
            },
        )
        with urlopen(request, timeout=self.ai_service.datasheet_timeout_seconds) as response:
            body = json.loads(response.read().decode("utf-8"))
        parsed = json.loads(self.ai_service._extract_output_text(body))
        extraction = ReferenceCircuitExtraction(
            part_number=str(parsed.get("part_number") or candidate.part_number),
            manufacturer=str(parsed.get("manufacturer") or candidate.manufacturer),
            package=str(parsed.get("package") or ""),
            supply_range=str(parsed.get("supply_range") or ""),
            interface=str(parsed.get("interface") or ""),
            pins=[PinDefinition(**item) for item in parsed.get("pins", [])],
            support_requirements=[SupportRequirement(**item) for item in parsed.get("support_requirements", [])],
            nets=[CircuitNet(**item) for item in parsed.get("nets", [])],
            source_chunks=chunks,
            source_urls=[chunk.source_url for chunk in chunks],
            unanswered_questions=[str(item) for item in parsed.get("unanswered_questions", [])],
            validation_warnings=[str(item) for item in parsed.get("validation_warnings", [])],
            extraction_notes=[str(item) for item in parsed.get("extraction_notes", [])],
            confidence=str(parsed.get("confidence") or "low"),
        )
        return extraction

    def _heuristic_extract(
        self,
        candidate: DatasheetCandidate,
        chunks: list[SourceChunk],
    ) -> ReferenceCircuitExtraction:
        joined = "\n".join(chunk.text for chunk in chunks)
        pins = self._heuristic_pins(chunks)
        supports = self._heuristic_supports(chunks, pins)

        nets = self._nets_from_pins_and_supports(pins, supports)
        warnings = []
        if not pins:
            warnings.append("Local heuristic could not extract a pin table.")
        if not supports:
            warnings.append("Local heuristic could not extract support passives.")
        return ReferenceCircuitExtraction(
            part_number=candidate.part_number,
            manufacturer=candidate.manufacturer,
            package=self._guess_package(joined),
            supply_range=self._guess_supply(joined),
            interface=self._guess_interface(joined, pins),
            pins=pins,
            support_requirements=supports,
            nets=nets,
            source_chunks=chunks,
            source_urls=[chunk.source_url for chunk in chunks],
            unanswered_questions=[],
            validation_warnings=warnings,
            extraction_notes=[
                *candidate.extraction_notes,
                "Local heuristic extraction used downloaded source chunks.",
            ],
            confidence="low",
        )

    def _heuristic_pins(self, chunks: list[SourceChunk]) -> list[PinDefinition]:
        pins: list[PinDefinition] = []
        seen: set[tuple[str, str]] = set()
        known_names_pattern = "|".join(sorted(re.escape(name) for name in KNOWN_PIN_NAMES))
        pin_patterns = [
            (re.compile(r"\b(?:pin\s*)?(\d{1,3})\s+([A-Z][A-Z0-9_/#-]{1,20})\b", re.I), 1, 2, False),
            (re.compile(r"\bpin\s*(\d{1,3})\s*[:\-–]\s*([A-Z][A-Z0-9_/#-]{1,20})\b", re.I), 1, 2, False),
            (re.compile(r"\b(\d{1,3})\s*[\).:\-–]\s*([A-Z][A-Z0-9_/#-]{1,20})\b", re.I), 1, 2, False),
            (re.compile(rf"\b({known_names_pattern})\s+(?:pin\s*)?(\d{{1,3}})\b", re.I), 2, 1, True),
            (re.compile(rf"\b({known_names_pattern})\s*\(\s*pin\s*(\d{{1,3}})\s*\)", re.I), 2, 1, True),
        ]
        for chunk in chunks:
            name_first_context = self._allows_name_first_pin_order(chunk.text)
            for pattern, number_group, name_group, requires_schematic in pin_patterns:
                if requires_schematic and not name_first_context:
                    continue
                for match in pattern.finditer(chunk.text):
                    number = match.group(number_group)
                    name = self._normalise_pin_name(match.group(name_group))
                    if not self._is_likely_pin_match(
                        chunk.text,
                        match.start(),
                        name,
                        match.group(0).lower().startswith("pin"),
                    ):
                        continue
                    key = (number, name)
                    if key in seen:
                        continue
                    context = self._pin_match_context(chunk.text, match)
                    pins.append(
                        PinDefinition(
                            number=number,
                            name=name,
                            electrical_type=self._electrical_type_for_pin(name),
                            net_name=self._net_for_pin_from_context(name, context),
                            source_citations=[chunk.chunk_id],
                        )
                    )
                    seen.add(key)
                    if len(pins) >= 48:
                        return pins
            for pin in self._schematic_label_pins(chunk):
                key = (pin.number, pin.name)
                if key in seen:
                    continue
                pins.append(pin)
                seen.add(key)
                if len(pins) >= 48:
                    return pins
        return pins

    def _schematic_label_pins(self, chunk: SourceChunk) -> list[PinDefinition]:
        if not self._allows_name_first_pin_order(chunk.text):
            return []
        compact = re.sub(r"\s+", " ", chunk.text)
        pins: list[PinDefinition] = []
        seen: set[tuple[str, str]] = set()
        for raw_name in sorted(KNOWN_PIN_NAMES, key=len, reverse=True):
            name = self._normalise_pin_name(raw_name)
            escaped_name = re.escape(name).replace("_", r"[_/\s-]*")
            for pattern in [
                re.compile(rf"\b{escaped_name}\b\s*(\d{{1,3}})", re.I),
                re.compile(rf"(\d{{1,3}})\s*\b{escaped_name}\b", re.I),
            ]:
                match = pattern.search(compact)
                if not match:
                    continue
                number = match.group(1)
                key = (number, name)
                if key in seen:
                    continue
                context = compact[max(0, match.start() - 120) : min(len(compact), match.end() + 120)]
                pins.append(
                    PinDefinition(
                        number=number,
                        name=name,
                        electrical_type=self._electrical_type_for_pin(name),
                        net_name=self._net_for_pin_from_context(name, context),
                        source_citations=[chunk.chunk_id],
                    )
                )
                seen.add(key)
                break
        return pins

    def _normalise_pin_name(self, value: str) -> str:
        normalised = value.strip().strip(".,;:()[]{}").upper().replace("-", "_").replace("/", "_")
        aliases = {
            "ENABLE": "EN",
            "BST": "BOOT",
            "PGOOD": "PG",
            "PWRGD": "PG",
            "PHASE": "PH",
            "RUNSS": "TRSS",
            "TR/SS": "TR_SS",
            "RT/SYNC": "RT_SYNC",
        }
        return aliases.get(normalised, normalised)

    def _is_likely_pin_match(self, text: str, start: int, name: str, has_pin_prefix: bool) -> bool:
        if name not in KNOWN_PIN_NAMES:
            return False
        if has_pin_prefix:
            return True
        if start > 0 and text[start - 1] in ".-":
            return False
        nearby = text[max(0, start - 900) : min(len(text), start + 900)].lower()
        immediate_before = text[max(0, start - 12) : start].lower()
        if re.search(r"\bpin\s*$", immediate_before):
            return True
        return any(
            marker in nearby
            for marker in [
                "pin description",
                "pin function",
                "pin functions",
                "pin configuration",
                "pin assignment",
                "pin no",
                "pin number",
                "pin-out",
                "pinout",
                "pin numbering",
                "input/output pins",
                "uses the following pins",
                "simplified schematic",
                "typical application",
                "application schematic",
                "terminal functions",
                "terminal function",
            ]
        )

    def _allows_name_first_pin_order(self, text: str) -> bool:
        lowered = text.lower()
        return self._looks_like_reference_schematic(text) or any(
            marker in lowered
            for marker in [
                "pin function",
                "pin functions",
                "pin configuration",
                "pin assignment",
                "pinout diagram",
                "pin-out diagram",
                "pin no",
                "pin number",
                "terminal functions",
                "terminal function",
            ]
        )

    def _looks_like_reference_schematic(self, text: str) -> bool:
        lowered = text.lower()
        return any(
            marker in lowered
            for marker in [
                "simplified schematic",
                "typical application",
                "application schematic",
                "reference design",
                "connection diagram",
            ]
        )

    def _pin_match_context(self, text: str, match: re.Match[str]) -> str:
        next_pin = re.search(
            r"\b\d{1,3}\s+(?:"
            + "|".join(sorted(re.escape(name) for name in KNOWN_PIN_NAMES))
            + r")\b",
            text[match.end() :],
            flags=re.I,
        )
        end = match.end() + (next_pin.start() if next_pin else 180)
        return text[match.start() : min(len(text), end)]

    def _net_for_pin_from_context(self, name: str, context: str) -> str:
        upper_context = context.upper()
        if name in {"VIN", "PVIN", "AVIN"}:
            return "VIN"
        if name in {"SW", "LX", "PH"}:
            return "SW"
        if name in {"BOOT", "BST"}:
            return "BOOT"
        if name == "FB":
            return "FB"
        if name in {"EN", "RUN"}:
            return "EN"
        if name == "RT_SYNC":
            return "RT_SYNC"
        if name == "SDI" and "SDA" in upper_context:
            return "SDA"
        if name in {"SCK", "SCLK"} and "SCL" in upper_context:
            return "SCL"
        if name == "CSB" and "VDDIO" in upper_context:
            return "+3V3"
        if name in {"SDO", "SA0", "ADDR", "AD0"}:
            if "GND" in upper_context and ("DEFAULT ADDRESS" in upper_context or "ADDRESS" in upper_context):
                return "GND"
            if "VDDIO" in upper_context:
                return "+3V3"
        return self._net_for_pin(name)

    def _heuristic_supports(
        self,
        chunks: list[SourceChunk],
        pins: list[PinDefinition],
    ) -> list[SupportRequirement]:
        if not pins:
            return []
        supports: list[SupportRequirement] = []
        seen: set[tuple[str, str, tuple[str, ...]]] = set()
        power_net = self._primary_power_net(pins)
        has_i2c_sda = any(pin.name == "SDA" or pin.net_name == "SDA" for pin in pins)
        has_i2c_scl = any(pin.name in {"SCL", "SCK"} or pin.net_name == "SCL" for pin in pins)
        for chunk in chunks:
            text = chunk.text
            normalised = self._normalise_passive_text(text)
            if self._mentions_decoupling_capacitor(normalised):
                cap_count = 2 if re.search(r"\bC\s*1\b.*\bC\s*2\b|\bC1\b.*\bC2\b", text, re.I) else 1
                for purpose in self._decoupling_purposes(pins, cap_count):
                    self._append_support(
                        supports,
                        seen,
                        SupportRequirement(
                            reference_prefix="C",
                            type="capacitor",
                            value="100 nF",
                            purpose=purpose,
                            connects=[power_net, "GND"],
                            footprint="Capacitor_SMD:C_0603_1608Metric",
                            placement_note="Place close to the IC supply pins.",
                            source_citations=[chunk.chunk_id],
                        ),
                    )
            if self._mentions_i2c_pullups(normalised) and has_i2c_sda and has_i2c_scl:
                explicit_pullup = bool(re.search(r"4[,.]7\s*k", text, re.I))
                pullup_value = "4.7 kOhm"
                placement_note = (
                    "Datasheet/reference text gives 4.7 kOhm as the pull-up value; verify against bus capacitance and I2C speed."
                    if explicit_pullup
                    else (
                        "Starter value selected because the source required I2C pull-ups but did not give a value; "
                        "verify against bus capacitance and I2C speed."
                    )
                )
                for signal in ("SDA", "SCL"):
                    self._append_support(
                        supports,
                        seen,
                        SupportRequirement(
                            reference_prefix="R",
                            type="resistor",
                            value=pullup_value,
                            purpose=f"I2C {signal} pull-up",
                            connects=[signal, power_net],
                            footprint="Resistor_SMD:R_0603_1608Metric",
                            placement_note=placement_note,
                            source_citations=[chunk.chunk_id],
                        ),
                    )
            for requirement in self._buck_converter_supports(chunk, pins):
                self._append_support(supports, seen, requirement)
        return supports

    def _primary_power_net(self, pins: list[PinDefinition]) -> str:
        preferred = ["VIN", "+VIN", "+12V", "+5V", "+3V3"]
        pin_nets = [pin.net_name for pin in pins]
        for net in preferred:
            if net in pin_nets:
                return net
        return next((net for net in pin_nets if net.startswith("+") or net.upper().startswith("V")), "+3V3")

    def _buck_converter_supports(
        self,
        chunk: SourceChunk,
        pins: list[PinDefinition],
    ) -> list[SupportRequirement]:
        pin_names = {pin.name for pin in pins}
        pin_nets = {pin.net_name for pin in pins}
        if not ({"SW", "FB"} & pin_names or {"SW", "FB"} <= pin_nets):
            return []
        if "VIN" not in pin_names and "VIN" not in pin_nets:
            return []

        lowered = chunk.text.lower()
        if not (
            self._looks_like_reference_schematic(chunk.text)
            or "buck" in lowered
            or "step-down" in lowered
            or "switching regulator" in lowered
        ):
            return []

        requirements: list[SupportRequirement] = []
        if self._label_present(chunk.text, ["CIN", "C_IN", "CINPUT"]) or "input capacitor" in lowered:
            requirements.append(
                SupportRequirement(
                    reference_prefix="C",
                    type="capacitor",
                    value=(
                        self._value_near_label(chunk.text, ["CIN", "C_IN"])
                        or self._starter_support_value("buck_input_capacitor")
                    ),
                    purpose="input bypass capacitor",
                    connects=["VIN", "GND"],
                    footprint="Capacitor_SMD:C_0603_1608Metric",
                    placement_note="Place close to VIN and GND pins; verify capacitance, voltage rating, and ripple current.",
                    source_citations=[chunk.chunk_id],
                )
            )
        if self._label_present(chunk.text, ["CBOOT", "C_BOOT", "CBST"]) or "bootstrap capacitor" in lowered:
            requirements.append(
                SupportRequirement(
                    reference_prefix="C",
                    type="capacitor",
                    value=(
                        self._value_near_label(chunk.text, ["CBOOT", "C_BOOT", "CBST"])
                        or self._starter_support_value("buck_bootstrap_capacitor")
                    ),
                    purpose="bootstrap capacitor",
                    connects=["BOOT", "SW"],
                    footprint="Capacitor_SMD:C_0603_1608Metric",
                    placement_note="Connect between BOOT and SW as shown in the reference schematic; verify the datasheet-recommended value.",
                    source_citations=[chunk.chunk_id],
                )
            )
        if self._label_present(chunk.text, ["LO", "L_O", "L0"]) or "output inductor" in lowered:
            requirements.append(
                SupportRequirement(
                    reference_prefix="L",
                    type="inductor",
                    value=(
                        self._value_near_label(chunk.text, ["LO", "L_O", "L0"])
                        or self._starter_support_value("buck_output_inductor")
                    ),
                    purpose="buck output inductor",
                    connects=["SW", "VOUT"],
                    footprint="Inductor_SMD:L_4.0x4.0mm",
                    placement_note=(
                        "Starter value selected until the requested operating point is calculated; "
                        "verify current rating and saturation against the datasheet design procedure."
                    ),
                    source_citations=[chunk.chunk_id],
                    calculation_role="buck_output_inductor",
                    calculation_inputs=[
                        "calc_input_voltage_v",
                        "calc_output_voltage_v",
                        "calc_output_current_a",
                        "calc_switching_frequency_khz",
                        "calc_inductor_ripple_percent",
                    ],
                    calculation_formula="L = Vout * (Vin - Vout) / (Vin * fsw * ripple_current)",
                )
            )
        if self._label_present(chunk.text, ["CO", "C_O", "COUT", "C_OUT"]) or "output capacitor" in lowered:
            requirements.append(
                SupportRequirement(
                    reference_prefix="C",
                    type="capacitor",
                    value=(
                        self._value_near_label(chunk.text, ["CO", "C_O", "COUT"])
                        or self._starter_support_value("buck_output_capacitor")
                    ),
                    purpose="output capacitor",
                    connects=["VOUT", "GND"],
                    footprint="Capacitor_SMD:C_0603_1608Metric",
                    placement_note="Starter value selected; verify capacitance, ESR, voltage rating, and loop stability.",
                    source_citations=[chunk.chunk_id],
                )
            )
        if self._label_present(chunk.text, ["RFB1", "R_FB1"]):
            requirements.append(
                SupportRequirement(
                    reference_prefix="R",
                    type="resistor",
                    value=(
                        self._value_near_label(chunk.text, ["RFB1", "R_FB1"])
                        or self._starter_support_value("feedback_divider_upper")
                    ),
                    purpose="upper feedback divider resistor",
                    connects=["VOUT", "FB"],
                    footprint="Resistor_SMD:R_0603_1608Metric",
                    placement_note=(
                        "Starter value selected until the requested output voltage is calculated using the datasheet equation."
                    ),
                    source_citations=[chunk.chunk_id],
                    calculation_role="feedback_divider_upper",
                    calculation_inputs=[
                        "calc_output_voltage_v",
                        "calc_feedback_reference_voltage_v",
                        "calc_feedback_lower_resistance_kohm",
                    ],
                    calculation_formula="Rupper = Rlower * (Vout / Vref - 1)",
                )
            )
        if self._label_present(chunk.text, ["RFB2", "R_FB2"]):
            requirements.append(
                SupportRequirement(
                    reference_prefix="R",
                    type="resistor",
                    value=(
                        self._value_near_label(chunk.text, ["RFB2", "R_FB2"])
                        or self._starter_support_value("feedback_divider_lower")
                    ),
                    purpose="lower feedback divider resistor",
                    connects=["FB", "GND"],
                    footprint="Resistor_SMD:R_0603_1608Metric",
                    placement_note=(
                        "Starter value selected until the requested output voltage is calculated using the datasheet equation."
                    ),
                    source_citations=[chunk.chunk_id],
                    calculation_role="feedback_divider_lower",
                    calculation_inputs=["calc_feedback_lower_resistance_kohm"],
                    calculation_formula="Rlower = selected reference divider lower resistance",
                )
            )
        return requirements

    def _starter_support_value(self, role: str) -> str:
        values = {
            "buck_input_capacitor": "10 uF",
            "buck_bootstrap_capacitor": "100 nF",
            "buck_output_inductor": "4.7 uH",
            "buck_output_capacitor": "22 uF",
            "feedback_divider_upper": "100 kOhm",
            "feedback_divider_lower": "100 kOhm",
        }
        return values[role]

    def _label_present(self, text: str, labels: list[str]) -> bool:
        for label in labels:
            pattern = re.escape(label).replace("_", r"[_\s]*")
            if re.search(rf"(?<![A-Z0-9]){pattern}(?![A-Z0-9])", text, re.I):
                return True
        return False

    def _value_near_label(self, text: str, labels: list[str]) -> str:
        value_pattern = re.compile(
            r"\b\d+(?:[.,]\d+)?\s*(?:nF|uF|µF|pF|mH|uH|µH|nH|kOhm|kΩ|ohm|Ω|R)\b",
            re.I,
        )
        for label in labels:
            match = re.search(re.escape(label).replace("_", r"[_\s]*"), text, re.I)
            if not match:
                continue
            window = text[max(0, match.start() - 80) : min(len(text), match.end() + 120)]
            value_match = value_pattern.search(window)
            if value_match:
                return value_match.group(0).replace("µ", "u").replace("Ω", "Ohm")
        return ""

    def _normalise_passive_text(self, text: str) -> str:
        normalised = text.lower().replace("µ", "u").replace("Ω", "ohm").replace("ω", "ohm")
        return re.sub(r"\s+", " ", normalised)

    def _mentions_decoupling_capacitor(self, text: str) -> bool:
        return bool(
            re.search(r"\b100\s*nf\b|\b100nf\b|\b0[.,]1\s*u?f\b", text)
            and re.search(r"\bcapacitor|connection diagram|connection|typical application|schematic|decoupl", text)
        )

    def _decoupling_purposes(self, pins: list[PinDefinition], cap_count: int) -> list[str]:
        supply_names = {pin.name for pin in pins if pin.net_name.startswith("+") or pin.name.startswith("V")}
        if cap_count > 1 and "VDDIO" in supply_names and "VDD" in supply_names:
            return ["VDD supply decoupling", "VDDIO interface supply decoupling"]
        return ["supply decoupling"]

    def _mentions_i2c_pullups(self, text: str) -> bool:
        return bool(re.search(r"\bpull\s*-?\s*up", text) and ("sda" in text or "scl" in text or "i2c" in text))

    def _append_support(
        self,
        supports: list[SupportRequirement],
        seen: set[tuple[str, str, tuple[str, ...]]],
        requirement: SupportRequirement,
    ) -> None:
        key = (requirement.type, requirement.purpose, tuple(requirement.connects))
        if key in seen:
            return
        supports.append(requirement)
        seen.add(key)

    def _validation_errors(self, extraction: ReferenceCircuitExtraction) -> list[str]:
        errors = []
        citation_ids = {chunk.chunk_id for chunk in extraction.source_chunks}
        if not extraction.pins:
            errors.append("No cited pin map was extracted.")
        if not any(pin.net_name == "GND" or pin.name.upper() == "GND" for pin in extraction.pins):
            errors.append("No ground pin was extracted.")
        if not any(self._is_supply_pin(pin) for pin in extraction.pins):
            errors.append("No supply pin was extracted.")
        if not extraction.support_requirements:
            errors.append("No cited support passives or reference-circuit components were extracted.")
        for pin in extraction.pins:
            if not pin.source_citations or not set(pin.source_citations).issubset(citation_ids):
                errors.append(f"Pin {pin.number} {pin.name} is missing a valid source citation.")
        for requirement in extraction.support_requirements:
            if not requirement.source_citations or not set(requirement.source_citations).issubset(citation_ids):
                errors.append(f"Support component {requirement.purpose} is missing a valid source citation.")
        return list(dict.fromkeys(errors))

    def _is_supply_pin(self, pin: PinDefinition) -> bool:
        name = pin.name.upper()
        net_name = pin.net_name.upper()
        return (
            pin.net_name.startswith("+")
            or net_name in {"VIN", "VOUT"}
            or name in {"VIN", "PVIN", "AVIN"}
            or "VDD" in name
            or "VCC" in name
        )

    def _cad_notes(self, candidate: DatasheetCandidate) -> list[str]:
        if candidate.supplier_part_number:
            return [f"Supplier CAD lookup will prefer {candidate.supplier or 'LCSC'} {candidate.supplier_part_number}."]
        return ["No supplier part number was captured; export will try KiCad/LCSC lookup by MPN and fail if no CAD asset is found."]

    def _nets_from_pins_and_supports(
        self,
        pins: list[PinDefinition],
        supports: list[SupportRequirement],
    ) -> list[CircuitNet]:
        net_names = {pin.net_name for pin in pins}
        for support in supports:
            net_names.update(support.connects)
        nets = []
        for name in sorted(net_names):
            role = "other"
            upper = name.upper()
            if name == "GND":
                role = "ground"
            elif name.startswith("+") or upper.startswith("V"):
                role = "power"
            elif upper in {"SDA", "SCL", "MISO", "MOSI", "SCK", "CS"} or "I2C" in upper or "SPI" in upper:
                role = "interface"
            elif upper in {"EN", "MODE", "SYNC", "PG", "PGOOD"}:
                role = "configuration"
            elif "INT" in upper:
                role = "interrupt"
            elif "RESET" in upper or "XSHUT" in upper:
                role = "reset"
            nets.append(
                CircuitNet(
                    name=name,
                    role=role,
                    external=role in {"power", "ground", "interface", "interrupt", "reset", "configuration"},
                    connected_pins=[pin.name for pin in pins if pin.net_name == name],
                )
            )
        return nets

    def _net_for_pin(self, name: str) -> str:
        upper = name.upper()
        if upper in {"GND", "GNDA", "PGND", "AGND", "VSS"}:
            return "GND"
        if upper in {"VDD", "VCC", "AVDD", "IOVDD", "VDDIO"}:
            return "+3V3"
        if upper in {"VIN", "PVIN", "AVIN"}:
            return "VIN"
        if upper in {"SW", "LX", "PH"}:
            return "SW"
        if upper in {"BOOT", "BST"}:
            return "BOOT"
        if upper in {
            "BIAS",
            "FB",
            "EN",
            "RUN",
            "MODE",
            "RT",
            "RT_SYNC",
            "SS",
            "SS_TR",
            "TRSS",
            "TR_SS",
            "PG",
            "COMP",
            "INTVCC",
            "VC",
        }:
            return upper
        if upper in {"SDA", "SCL", "MISO", "MOSI", "SCK", "CS", "CSB"}:
            return upper
        if "INT" in upper:
            return upper
        if upper in {"XSHUT", "RESET", "NRST", "SHDN"}:
            return upper
        return upper

    def _electrical_type_for_pin(self, name: str) -> str:
        upper = name.upper()
        if upper in {"GND", "GNDA", "PGND", "AGND", "VSS"}:
            return "power_in"
        if upper in {"VDD", "VCC", "AVDD", "IOVDD", "VDDIO", "VIN", "PVIN", "AVIN", "BIAS", "INTVCC"}:
            return "power_in"
        if upper in {"SW", "LX", "PH", "BOOT", "PG", "PGOOD"}:
            return "output"
        if upper in {"SDA", "MISO", "MOSI"}:
            return "bidirectional"
        if upper in {
            "SCL",
            "SCK",
            "CS",
            "CSB",
            "XSHUT",
            "RESET",
            "NRST",
            "SHDN",
            "EN",
            "RUN",
            "MODE",
            "RT",
            "RT_SYNC",
            "SS",
            "SS_TR",
            "TRSS",
            "TR_SS",
            "FB",
            "VC",
        }:
            return "input"
        if "INT" in upper:
            return "output"
        return "passive"

    def _guess_package(self, text: str) -> str:
        match = re.search(r"\b(?:LGA|QFN|DFN|BGA|WLCSP|TSSOP|SOIC|SOT)[-_ ]?\d+[A-Za-z0-9_.-]*", text, re.I)
        return match.group(0) if match else ""

    def _guess_supply(self, text: str) -> str:
        match = re.search(r"\b\d(?:\.\d+)?\s*(?:V|volts?)\s*(?:to|-|–)\s*\d(?:\.\d+)?\s*(?:V|volts?)", text, re.I)
        return match.group(0) if match else ""

    def _guess_interface(self, text: str, pins: list[PinDefinition]) -> str:
        pin_names = {pin.name for pin in pins}
        compact = re.sub(r"[^a-z0-9]+", "", text.lower())
        if {"SW", "FB"} <= pin_names or ("buck" in compact or "stepdown" in compact):
            return "buck regulator power stage"
        if re.search(r"\bI2C|I²C|SDA|SCL\b", text, re.I):
            return "I2C"
        if re.search(r"\bSPI|MISO|MOSI|SCK\b", text, re.I):
            return "SPI"
        return ""

    def _clean_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    def _update(self, job_id: str, status: str, progress: float, message: str) -> None:
        job = self.get(job_id)
        job.status = status
        job.progress = progress
        job.message = message
        self._store(job)

    def _fail(
        self,
        job_id: str,
        message: str,
        *,
        errors: list[str] | None = None,
        extraction: ReferenceCircuitExtraction | None = None,
    ) -> None:
        job = self.get(job_id)
        job.status = "failed"
        job.progress = 1.0
        job.message = message
        job.errors = errors or [message]
        job.extraction = extraction
        self._store(job)

    def _store(self, job: ComponentExtractionJobResponse) -> None:
        with self._lock:
            self._jobs[job.job_id] = job.model_copy(deep=True)

    def _extraction_schema(self) -> dict[str, Any]:
        pin_schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "number": {"type": "string"},
                "name": {"type": "string"},
                "electrical_type": {"type": "string"},
                "net_name": {"type": "string"},
                "required": {"type": "boolean"},
                "notes": {"type": "string"},
                "source_citations": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["number", "name", "electrical_type", "net_name", "required", "notes", "source_citations"],
        }
        support_schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "reference_prefix": {"type": "string"},
                "type": {"type": "string"},
                "value": {"type": "string"},
                "purpose": {"type": "string"},
                "connects": {"type": "array", "items": {"type": "string"}},
                "footprint": {"type": "string"},
                "required": {"type": "boolean"},
                "placement_note": {"type": "string"},
                "source_citations": {"type": "array", "items": {"type": "string"}},
            },
            "required": [
                "reference_prefix",
                "type",
                "value",
                "purpose",
                "connects",
                "footprint",
                "required",
                "placement_note",
                "source_citations",
            ],
        }
        net_schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "name": {"type": "string"},
                "role": {
                    "type": "string",
                    "enum": ["power", "ground", "interface", "reset", "interrupt", "configuration", "internal", "other"],
                },
                "external": {"type": "boolean"},
                "connected_pins": {"type": "array", "items": {"type": "string"}},
                "notes": {"type": "string"},
            },
            "required": ["name", "role", "external", "connected_pins", "notes"],
        }
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "part_number": {"type": "string"},
                "manufacturer": {"type": "string"},
                "package": {"type": "string"},
                "supply_range": {"type": "string"},
                "interface": {"type": "string"},
                "pins": {"type": "array", "items": pin_schema},
                "support_requirements": {"type": "array", "items": support_schema},
                "nets": {"type": "array", "items": net_schema},
                "unanswered_questions": {"type": "array", "items": {"type": "string"}},
                "validation_warnings": {"type": "array", "items": {"type": "string"}},
                "extraction_notes": {"type": "array", "items": {"type": "string"}},
                "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            },
            "required": [
                "part_number",
                "manufacturer",
                "package",
                "supply_range",
                "interface",
                "pins",
                "support_requirements",
                "nets",
                "unanswered_questions",
                "validation_warnings",
                "extraction_notes",
                "confidence",
            ],
        }
