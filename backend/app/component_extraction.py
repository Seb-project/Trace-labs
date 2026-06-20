from __future__ import annotations

import base64
import html
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

import httpx

from .ai_service import PCBStreamAIService
from .models import (
    CircuitNet,
    ComponentExtractionJobResponse,
    DatasheetCandidate,
    PinDefinition,
    ReferenceCircuitExtraction,
    SourceChunk,
    SupportRequirement,
)


EXTRACT_CANDIDATE_PREFIX = "extract_candidate::"
MAX_SOURCE_BYTES = 8_000_000
MAX_CHUNKS_FOR_MODEL = 28


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
    def __init__(self, ai_service: PCBStreamAIService):
        self.ai_service = ai_service
        self._jobs: dict[str, ComponentExtractionJobResponse] = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pcbstream-extract")

    def start(self, candidate: DatasheetCandidate, *, run_inline: bool = False) -> ComponentExtractionJobResponse:
        job_id = str(uuid4())
        job = ComponentExtractionJobResponse(
            job_id=job_id,
            status="queued",
            progress=0.0,
            message=f"Queued datasheet extraction for {candidate.manufacturer} {candidate.part_number}.",
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
            self._update(job_id, "fetching_sources", 0.15, "Downloading selected datasheet and reference sources.")
            download_errors: list[str] = []
            chunks = self._fetch_source_chunks(candidate, download_errors)
            if not chunks:
                self._fail(
                    job_id,
                    "No readable datasheet text could be downloaded from the selected sources.",
                    errors=download_errors
                    or [
                        "PCBStream had source URLs for this candidate, but none produced readable text for extraction."
                    ],
                )
                return

            self._update(job_id, "extracting", 0.45, "Extracting pin map, required passives, and reference nets.")
            extraction = self._extract_reference_circuit(candidate, chunks)

            self._update(job_id, "acquiring_cad", 0.72, "Checking CAD asset requirements for the selected part.")
            extraction.extraction_notes.extend(self._cad_notes(candidate))

            self._update(job_id, "validating", 0.88, "Validating extracted circuit evidence.")
            errors = self._validation_errors(extraction)
            if errors:
                self._fail(
                    job_id,
                    "Datasheet extraction was incomplete; PCBStream will not generate a placeholder schematic.",
                    errors=errors,
                    extraction=extraction,
                )
                return

            self._store(
                ComponentExtractionJobResponse(
                    job_id=job_id,
                    status="ready",
                    progress=1.0,
                    message=(
                        f"Extraction ready for {candidate.manufacturer} {candidate.part_number}. "
                        "PCBStream found cited pins and support components."
                    ),
                    candidate=candidate,
                    extraction=extraction,
                )
            )
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, httpx.HTTPError) as exc:
            self._fail(job_id, f"Datasheet extraction failed: {exc}")

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
                "AppleWebKit/537.36 (KHTML, like Gecko) PCBStream/0.1 Safari/537.36"
            ),
            "Accept": "application/pdf,text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8",
        }
        with httpx.Client(follow_redirects=True, timeout=35.0, headers=headers) as client:
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
            "application",
            "schematic",
            "recommended",
            "typical",
            "capacitor",
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
            return sum(text.count(keyword) for keyword in keywords)

        return sorted(chunks, key=score, reverse=True)

    def _extract_reference_circuit(
        self,
        candidate: DatasheetCandidate,
        chunks: list[SourceChunk],
    ) -> ReferenceCircuitExtraction:
        if self.ai_service.enabled:
            try:
                return self._extract_with_openai(candidate, chunks)
            except Exception as exc:
                fallback = self._heuristic_extract(candidate, chunks)
                fallback.validation_warnings.append(f"OpenAI extraction failed, used local heuristic fallback: {exc}")
                return fallback
        return self._heuristic_extract(candidate, chunks)

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
                                "Return support passives needed by the reference/typical application circuit.",
                                "Return nets that connect pins and support passives.",
                                "Use concise values such as 100 nF, 4.7 kOhm, DNP, or TBD only if source says unresolved.",
                            ],
                        },
                        indent=2,
                    ),
                },
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "pcbstream_reference_circuit_extraction",
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
        citation = chunks[0].chunk_id if chunks else ""
        pins: list[PinDefinition] = []
        pin_pattern = re.compile(r"\b(?:pin\s*)?(\d{1,3})\s+([A-Z][A-Z0-9_/#-]{1,20})\b", re.I)
        for match in pin_pattern.finditer(joined):
            name = match.group(2).upper()
            if name in {"PIN", "TABLE", "FIGURE"}:
                continue
            net_name = self._net_for_pin(name)
            if any(pin.number == match.group(1) and pin.name == name for pin in pins):
                continue
            pins.append(
                PinDefinition(
                    number=match.group(1),
                    name=name,
                    electrical_type=self._electrical_type_for_pin(name),
                    net_name=net_name,
                    source_citations=[citation] if citation else [],
                )
            )
            if len(pins) >= 32:
                break

        supports: list[SupportRequirement] = []
        if pins:
            power_net = next((pin.net_name for pin in pins if pin.net_name.startswith("+")), "+3V3")
            if "100 nF" in joined or "100nF" in joined or "0.1" in joined:
                supports.append(
                    SupportRequirement(
                        reference_prefix="C",
                        type="capacitor",
                        value="100 nF",
                        purpose="supply decoupling",
                        connects=[power_net, "GND"],
                        footprint="Capacitor_SMD:C_0603_1608Metric",
                        placement_note="Place close to the IC supply pins.",
                        source_citations=[citation] if citation else [],
                    )
                )
            if re.search(r"\bpull-?up\b", joined, re.I) and any(pin.name in {"SDA", "SCL"} for pin in pins):
                for signal in ("SDA", "SCL"):
                    if any(pin.name == signal for pin in pins):
                        supports.append(
                            SupportRequirement(
                                reference_prefix="R",
                                type="resistor",
                                value="TBD",
                                purpose=f"I2C {signal} pull-up",
                                connects=[signal, power_net],
                                footprint="Resistor_SMD:R_0603_1608Metric",
                                placement_note="Value depends on bus capacitance and I2C speed.",
                                source_citations=[citation] if citation else [],
                            )
                        )

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
            interface="I2C" if re.search(r"\bI2C|I²C|SDA|SCL\b", joined, re.I) else "",
            pins=pins,
            support_requirements=supports,
            nets=nets,
            source_chunks=chunks,
            source_urls=[chunk.source_url for chunk in chunks],
            unanswered_questions=[],
            validation_warnings=warnings,
            extraction_notes=["Local heuristic extraction used downloaded source chunks."],
            confidence="low",
        )

    def _validation_errors(self, extraction: ReferenceCircuitExtraction) -> list[str]:
        errors = []
        citation_ids = {chunk.chunk_id for chunk in extraction.source_chunks}
        if not extraction.pins:
            errors.append("No cited pin map was extracted.")
        if not any(pin.net_name == "GND" or pin.name.upper() == "GND" for pin in extraction.pins):
            errors.append("No ground pin was extracted.")
        if not any(pin.net_name.startswith("+") or "VDD" in pin.name.upper() or "VCC" in pin.name.upper() for pin in extraction.pins):
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
            elif "INT" in upper:
                role = "interrupt"
            elif "RESET" in upper or "XSHUT" in upper:
                role = "reset"
            nets.append(
                CircuitNet(
                    name=name,
                    role=role,
                    external=role in {"power", "ground", "interface", "interrupt", "reset"},
                    connected_pins=[pin.name for pin in pins if pin.net_name == name],
                )
            )
        return nets

    def _net_for_pin(self, name: str) -> str:
        upper = name.upper()
        if upper in {"GND", "GNDA", "VSS"}:
            return "GND"
        if upper in {"VDD", "VCC", "AVDD", "IOVDD", "VDDIO", "VIN"}:
            return "+3V3"
        if upper in {"SDA", "SCL", "MISO", "MOSI", "SCK", "CS", "CSB"}:
            return upper
        if "INT" in upper:
            return upper
        if upper in {"XSHUT", "RESET", "NRST", "SHDN"}:
            return upper
        return upper

    def _electrical_type_for_pin(self, name: str) -> str:
        upper = name.upper()
        if upper in {"GND", "GNDA", "VSS"}:
            return "power_in"
        if upper in {"VDD", "VCC", "AVDD", "IOVDD", "VDDIO", "VIN"}:
            return "power_in"
        if upper in {"SDA", "MISO", "MOSI"}:
            return "bidirectional"
        if upper in {"SCL", "SCK", "CS", "CSB", "XSHUT", "RESET", "NRST", "SHDN"}:
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
