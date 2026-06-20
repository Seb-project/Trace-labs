from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


KICAD_FOOTPRINTS_PROJECT = "kicad%2Flibraries%2Fkicad-footprints"
KICAD_SYMBOLS_PROJECT = "kicad%2Flibraries%2Fkicad-symbols"


@dataclass(frozen=True)
class DownloadedSource:
    kind: str
    project: str
    path: str
    url: str
    confidence: str = "downloaded_needs_review"


@dataclass(frozen=True)
class DownloadedLibraryAssets:
    symbol_text: str | None = None
    footprint_text: str | None = None
    footprint_name: str | None = None
    sources: list[DownloadedSource] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def has_any_asset(self) -> bool:
        return self.symbol_text is not None or self.footprint_text is not None


@dataclass(frozen=True)
class SupplierMatch:
    lcsc_id: str
    url: str = ""
    model: str = ""
    brand: str = ""
    package: str = ""


class GitLabKiCadLibraryClient:
    api_root = "https://gitlab.com/api/v4/projects"
    raw_root = "https://gitlab.com/kicad/libraries"

    def __init__(self, timeout_seconds: float = 6.0):
        self.timeout_seconds = timeout_seconds

    def list_tree(
        self,
        project: str,
        path: str = "",
        *,
        per_page: int = 100,
        max_pages: int = 3,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for page in range(1, max_pages + 1):
            query = {
                "per_page": str(per_page),
                "page": str(page),
            }
            if path:
                query["path"] = path
            url = f"{self.api_root}/{project}/repository/tree?{urllib.parse.urlencode(query)}"
            page_items = self._get_json(url)
            if not isinstance(page_items, list):
                return items
            items.extend(item for item in page_items if isinstance(item, dict))
            if len(page_items) < per_page:
                break
        return items

    def raw_file(self, repo_name: str, path: str) -> tuple[str, str]:
        encoded_path = urllib.parse.quote(path, safe="/._-")
        last_error: Exception | None = None
        for branch in ("master", "main"):
            url = f"{self.raw_root}/{repo_name}/-/raw/{branch}/{encoded_path}"
            try:
                return self._get_text(url), url
            except (OSError, TimeoutError, urllib.error.URLError, urllib.error.HTTPError, ValueError) as exc:
                last_error = exc
        raise ValueError(f"Could not download {path}: {last_error}") from last_error

    def _get_json(self, url: str) -> Any:
        text = self._get_text(url)
        return json.loads(text)

    def _get_text(self, url: str) -> str:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json,text/plain,*/*",
                "User-Agent": "PCBStream/0.1 KiCadLibraryLookup",
            },
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            return response.read().decode("utf-8")


class EasyEDALCSCProvider:
    def __init__(self, *, enabled: bool | None = None):
        if enabled is None:
            enabled = os.getenv("PCBSTREAM_LCSC_LOOKUP_ENABLED", "true").lower() not in {
                "0",
                "false",
                "no",
                "off",
            }
        self.enabled = enabled
        self.timeout_seconds = float(os.getenv("PCBSTREAM_LCSC_LOOKUP_TIMEOUT_SECONDS", "90"))
        self.search_enabled = os.getenv("PCBSTREAM_LCSC_SEARCH_ENABLED", "true").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self.import_symbols = os.getenv("PCBSTREAM_SUPPLIER_SYMBOL_IMPORT_ENABLED", "false").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    def acquire_for_block(
        self,
        block: Any,
        *,
        symbol_name: str,
        footprint_name: str,
        footprint_id: str,
    ) -> DownloadedLibraryAssets | None:
        if not self.enabled:
            return None
        supplier_matches = self._supplier_matches_for_block(block)
        if not supplier_matches:
            return None

        warnings: list[str] = []
        for supplier_match in supplier_matches[:6]:
            result = self._convert_supplier_match(
                block,
                supplier_match=supplier_match,
                symbol_name=symbol_name,
                footprint_name=footprint_name,
                footprint_id=footprint_id,
            )
            if result.has_any_asset:
                return result
            warnings.extend(result.warnings)
        return DownloadedLibraryAssets(warnings=warnings) if warnings else None

    def _convert_supplier_match(
        self,
        block: Any,
        *,
        supplier_match: SupplierMatch,
        symbol_name: str,
        footprint_name: str,
        footprint_id: str,
    ) -> DownloadedLibraryAssets:
        lcsc_id = supplier_match.lcsc_id
        supplier_footprint_name = self._supplier_footprint_name(footprint_name, lcsc_id)
        with tempfile.TemporaryDirectory(prefix="pcbstream_lcsc_") as tmp_dir:
            output_base = Path(tmp_dir) / f"PCBStream_{lcsc_id}"
            command = [
                sys.executable,
                "-m",
                "easyeda2kicad",
                "--footprint",
                f"--lcsc_id={lcsc_id}",
                f"--output={output_base}",
                "--overwrite",
            ]
            if self.import_symbols:
                command.insert(3, "--symbol")

            try:
                result = subprocess.run(
                    command,
                    cwd=tmp_dir,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    check=False,
                )
            except FileNotFoundError:
                return DownloadedLibraryAssets(
                    warnings=["LCSC lookup skipped: easyeda2kicad is not installed in the backend Python environment."]
                )
            except subprocess.TimeoutExpired:
                return DownloadedLibraryAssets(warnings=[f"LCSC lookup timed out for {lcsc_id}."])

            if result.returncode != 0:
                detail = (result.stderr or result.stdout or "").strip().splitlines()
                message = detail[-1] if detail else "easyeda2kicad returned a non-zero exit status."
                return DownloadedLibraryAssets(warnings=[f"LCSC lookup failed for {lcsc_id}: {message}"])

            footprint_text = self._read_footprint(output_base, supplier_footprint_name, block.main_component.value)
            symbol_text = self._read_symbol(output_base, symbol_name, block.main_component.value, footprint_id)
            if not footprint_text and not symbol_text:
                return DownloadedLibraryAssets(warnings=[f"LCSC lookup produced no KiCad library files for {lcsc_id}."])

            sources = [
                DownloadedSource(
                    kind="supplier_footprint",
                    project="LCSC/EasyEDA via easyeda2kicad",
                    path=lcsc_id,
                    url=self._lcsc_url(block, supplier_match),
                    confidence="supplier_downloaded_needs_review",
                )
            ]
            if symbol_text:
                sources.append(
                    DownloadedSource(
                        kind="supplier_symbol",
                        project="LCSC/EasyEDA via easyeda2kicad",
                        path=lcsc_id,
                        url=self._lcsc_url(block, supplier_match),
                        confidence="supplier_downloaded_needs_review",
                    )
                )
            return DownloadedLibraryAssets(
                symbol_text=symbol_text,
                footprint_text=footprint_text,
                footprint_name=supplier_footprint_name,
                sources=sources,
            )

    def _read_footprint(self, output_base: Path, footprint_name: str, value: str) -> str | None:
        pretty_dir = output_base.with_suffix(".pretty")
        footprint_files = sorted(pretty_dir.glob("*.kicad_mod")) if pretty_dir.exists() else []
        if not footprint_files:
            return None
        text = footprint_files[0].read_text(encoding="utf-8")
        text = re.sub(r'^\(module\s+(?:"[^"]+"|[^\s)]+)', f'(footprint "{footprint_name}"', text, count=1)
        text = re.sub(r'^\(footprint\s+"[^"]+"', f'(footprint "{footprint_name}"', text, count=1)
        text = re.sub(r'\(property "Value" "[^"]+"', f'(property "Value" "{value}"', text, count=1)
        text = re.sub(r'\(fp_text\s+value\s+"[^"]+"', f'(fp_text value "{value}"', text, count=1)
        return text

    def _supplier_footprint_name(self, footprint_name: str, lcsc_id: str) -> str:
        if footprint_name.endswith("_PLACEHOLDER"):
            return f"{footprint_name.removesuffix('_PLACEHOLDER')}_LCSC_{lcsc_id}"
        if lcsc_id not in footprint_name:
            return f"{footprint_name}_LCSC_{lcsc_id}"
        return footprint_name

    def _read_symbol(self, output_base: Path, symbol_name: str, value: str, footprint_id: str) -> str | None:
        if not self.import_symbols:
            return None
        symbol_file = output_base.with_suffix(".kicad_sym")
        if not symbol_file.exists():
            return None
        text = symbol_file.read_text(encoding="utf-8")
        symbol = self._first_symbol(text)
        if not symbol:
            return None
        symbol = re.sub(r'\(symbol\s+"[^"]+"', f'(symbol "{symbol_name}"', symbol, count=1)
        symbol = re.sub(r'\(property "Value" "[^"]*"', f'(property "Value" "{value}"', symbol, count=1)
        symbol = re.sub(r'\(property "Footprint" "[^"]*"', f'(property "Footprint" "{footprint_id}"', symbol, count=1)
        return symbol

    def _first_symbol(self, library_text: str) -> str | None:
        match = re.search(r'\(symbol\s+"([^"]+)"', library_text)
        if not match:
            return None
        return _balanced_sexpr(library_text, match.start())

    def _supplier_matches_for_block(self, block: Any) -> list[SupplierMatch]:
        fields = [
            getattr(block.main_component, "supplier_part_number", None),
            getattr(block.main_component, "supplier_url", None),
            block.main_component.mpn,
            block.main_component.value,
            block.summary,
            *(source.url for source in block.datasheet_sources),
            *(source.notes or "" for source in block.datasheet_sources),
        ]
        for field in fields:
            match = re.search(r"\bC\d{3,}\b", str(field or "").upper())
            if match:
                return [SupplierMatch(lcsc_id=match.group(0), url=getattr(block.main_component, "supplier_url", None) or "")]
        return self._search_lcsc_by_mpn(block)

    def _search_lcsc_by_mpn(self, block: Any) -> list[SupplierMatch]:
        if not self.search_enabled:
            return []
        keyword = str(block.main_component.mpn or block.main_component.value or "").strip()
        if not keyword or re.fullmatch(r"C\d{3,}", keyword.upper()):
            return []
        try:
            from easyeda2kicad.easyeda.easyeda_api import EasyedaApi
        except ImportError:
            return []
        try:
            results = EasyedaApi().search_jlcpcb_components(keyword=keyword, page_size=8).get("results", [])
        except Exception:
            return []
        needle = _normalised_token(keyword)
        matches: list[tuple[int, SupplierMatch]] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            lcsc_id = str(item.get("lcsc") or "")
            if not lcsc_id:
                continue
            haystacks = [
                str(item.get("model") or ""),
                str(item.get("name") or ""),
                str(item.get("description") or ""),
            ]
            if any(_normalised_token(value) == needle for value in haystacks):
                score = 100
            elif any(needle and needle in _normalised_token(value) for value in haystacks):
                score = 70
            else:
                continue
            package = str(item.get("package") or "")
            if any(token in package.upper() for token in ("QFN", "DFN", "LGA", "BGA", "SOP", "SOIC", "SOT")):
                score += 5
            matches.append(
                (
                    score,
                    SupplierMatch(
                        lcsc_id=lcsc_id,
                        url=str(item.get("url") or item.get("datasheet") or ""),
                        model=str(item.get("model") or ""),
                        brand=str(item.get("brand") or ""),
                        package=package,
                    ),
                )
            )
        return [match for _, match in sorted(matches, key=lambda item: -item[0])]

    def _lcsc_url(self, block: Any, supplier_match: SupplierMatch) -> str:
        supplier_url = getattr(block.main_component, "supplier_url", None)
        if supplier_url:
            return supplier_url
        if supplier_match.url:
            return supplier_match.url
        return f"https://www.lcsc.com/datasheet/{supplier_match.lcsc_id}.pdf"


class OnlineLibraryAcquisitionService:
    footprint_dirs = [
        "Package_LGA.pretty",
        "Package_DFN_QFN.pretty",
        "Package_CSP.pretty",
        "OptoDevice.pretty",
        "Sensor.pretty",
        "Module.pretty",
    ]
    symbol_dirs = [
        "Sensor.kicad_symdir",
        "Sensor_Motion.kicad_symdir",
        "Interface_Optical.kicad_symdir",
        "Interface.kicad_symdir",
        "Module.kicad_symdir",
        "RF_Module.kicad_symdir",
    ]

    def __init__(
        self,
        client: GitLabKiCadLibraryClient | None = None,
        *,
        enabled: bool | None = None,
    ):
        if enabled is None:
            enabled = os.getenv("PCBSTREAM_ONLINE_LIBRARY_LOOKUP_ENABLED", "true").lower() not in {
                "0",
                "false",
                "no",
                "off",
            }
        timeout = float(os.getenv("PCBSTREAM_LIBRARY_LOOKUP_TIMEOUT_SECONDS", "6"))
        self.client = client or GitLabKiCadLibraryClient(timeout_seconds=timeout)
        self.enabled = enabled
        self.import_symbols = os.getenv("PCBSTREAM_ONLINE_SYMBOL_IMPORT_ENABLED", "false").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self.lcsc_provider = EasyEDALCSCProvider()

    def acquire_for_block(
        self,
        block: Any,
        *,
        library_name: str,
        symbol_name: str,
        footprint_name: str,
        footprint_id: str,
    ) -> DownloadedLibraryAssets | None:
        if not self.enabled:
            return None

        part_number = str(block.main_component.mpn or block.main_component.value or "").strip()
        if not part_number:
            return None

        warnings: list[str] = []
        sources: list[DownloadedSource] = []
        symbol_text: str | None = None
        footprint_text: str | None = None
        symbol_footprint_hint: str | None = None

        supplier_result = self.lcsc_provider.acquire_for_block(
            block,
            symbol_name=symbol_name,
            footprint_name=footprint_name,
            footprint_id=footprint_id,
        )
        if supplier_result and supplier_result.has_any_asset:
            return supplier_result
        if supplier_result:
            warnings.extend(supplier_result.warnings)

        try:
            symbol = self._find_symbol(part_number, symbol_name, block.main_component.value, footprint_id)
            if symbol:
                symbol_text = symbol[0] if self.import_symbols else None
                source = symbol[1] if self.import_symbols else DownloadedSource(
                    "symbol_hint",
                    symbol[1].project,
                    symbol[1].path,
                    symbol[1].url,
                    "used_for_footprint_match",
                )
                sources.append(source)
                symbol_footprint_hint = symbol[2]
        except Exception as exc:
            warnings.append(f"Symbol lookup failed: {exc}")

        try:
            footprint = self._find_footprint(block, footprint_name, symbol_footprint_hint)
            if footprint:
                footprint_text = footprint[0]
                sources.append(footprint[1])
        except Exception as exc:
            warnings.append(f"Footprint lookup failed: {exc}")

        result = DownloadedLibraryAssets(symbol_text=symbol_text, footprint_text=footprint_text, sources=sources, warnings=warnings)
        return result if result.has_any_asset or result.warnings else None

    def _find_symbol(
        self,
        part_number: str,
        symbol_name: str,
        value: str,
        footprint_id: str,
    ) -> tuple[str, DownloadedSource, str | None] | None:
        candidates = self._matching_files(KICAD_SYMBOLS_PROJECT, self._symbol_dirs_for(part_number), part_number, ".kicad_sym")
        for candidate in candidates[:5]:
            text, url = self.client.raw_file("kicad-symbols", candidate["path"])
            symbol = self._extract_symbol_from_library(text, part_number)
            if symbol and "(extends " not in symbol:
                footprint_hint = self._property_value(symbol, "Footprint")
                rewritten = self._rewrite_symbol(symbol, symbol_name, value, footprint_id)
                source = DownloadedSource("symbol", "kicad-symbols", candidate["path"], url)
                return rewritten, source, footprint_hint
        return None

    def _find_footprint(
        self,
        block: Any,
        footprint_name: str,
        symbol_footprint_hint: str | None,
    ) -> tuple[str, DownloadedSource] | None:
        try:
            direct = self._download_footprint_hint(symbol_footprint_hint, footprint_name, block.main_component.value)
            if direct:
                return direct
        except Exception:
            pass

        search_terms = self._footprint_search_terms(block, symbol_footprint_hint)
        for term in search_terms:
            candidates = self._matching_files(KICAD_FOOTPRINTS_PROJECT, self._footprint_dirs_for(term), term, ".kicad_mod")
            for candidate in candidates[:8]:
                text, url = self.client.raw_file("kicad-footprints", candidate["path"])
                if '(footprint "' not in text:
                    continue
                rewritten = self._rewrite_footprint(text, footprint_name, block.main_component.value)
                source = DownloadedSource("footprint", "kicad-footprints", candidate["path"], url)
                return rewritten, source
        return None

    def _download_footprint_hint(
        self,
        footprint_hint: str | None,
        footprint_name: str,
        value: str,
    ) -> tuple[str, DownloadedSource] | None:
        if not footprint_hint or ":" not in footprint_hint:
            return None
        library, footprint = footprint_hint.split(":", 1)
        if not library or not footprint:
            return None
        path = f"{library}.pretty/{footprint}.kicad_mod"
        text, url = self.client.raw_file("kicad-footprints", path)
        if '(footprint "' not in text:
            return None
        return (
            self._rewrite_footprint(text, footprint_name, value),
            DownloadedSource("footprint", "kicad-footprints", path, url),
        )

    def _matching_files(
        self,
        project: str,
        directories: list[str],
        search_term: str,
        extension: str,
    ) -> list[dict[str, Any]]:
        needle = _normalised_token(search_term)
        if not needle:
            return []

        matches: list[dict[str, Any]] = []
        for directory in directories:
            try:
                items = self.client.list_tree(project, directory)
            except Exception:
                continue
            for item in items:
                if item.get("type") != "blob":
                    continue
                path = str(item.get("path", ""))
                if not path.endswith(extension):
                    continue
                score = self._match_score(needle, path)
                if score <= 0:
                    continue
                item = {**item, "_pcbstream_score": score}
                matches.append(item)
        return sorted(matches, key=lambda item: (-int(item["_pcbstream_score"]), str(item.get("path", ""))))

    def _match_score(self, needle: str, path: str) -> int:
        filename = path.rsplit("/", 1)[-1]
        stem = filename.rsplit(".", 1)[0]
        haystack = _normalised_token(stem)
        path_haystack = _normalised_token(path)
        if haystack == needle:
            return 100
        if needle in haystack:
            return 80
        if needle in path_haystack:
            return 60
        return 0

    def _extract_symbol_from_library(self, library_text: str, part_number: str) -> str | None:
        needle = _normalised_token(part_number)
        matches: list[tuple[int, int, str]] = []
        for match in re.finditer(r'\(symbol\s+"([^"]+)"', library_text):
            name = match.group(1)
            normalised_name = _normalised_token(name)
            if normalised_name == needle:
                matches.append((100, match.start(), name))
            elif needle and needle in normalised_name:
                matches.append((80, match.start(), name))

        for _, start, _ in sorted(matches, key=lambda item: -item[0]):
            symbol = self._balanced_sexpr(library_text, start)
            if symbol:
                return symbol
        return None

    def _balanced_sexpr(self, text: str, start: int) -> str | None:
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    return text[start : index + 1]
        return None

    def _rewrite_symbol(self, symbol: str, symbol_name: str, value: str, footprint_id: str) -> str:
        current_name = re.match(r'\s*\(symbol\s+"([^"]+)"', symbol)
        if current_name:
            original = current_name.group(1)
            symbol = re.sub(
                r'\(symbol\s+"' + re.escape(original) + r'"',
                f'(symbol "{symbol_name}"',
                symbol,
                count=1,
            )
            symbol = re.sub(
                r'\(symbol\s+"' + re.escape(original) + r"_",
                f'(symbol "{symbol_name}_',
                symbol,
            )
        symbol = self._replace_or_add_property(symbol, "Value", value)
        symbol = self._replace_or_add_property(symbol, "Footprint", footprint_id)
        symbol = self._replace_or_add_property(symbol, "Description", "PCBStream downloaded KiCad symbol candidate; review before fabrication")
        return symbol

    def _replace_or_add_property(self, symbol: str, name: str, value: str) -> str:
        escaped_value = value.replace("\\", "\\\\").replace('"', '\\"')
        pattern = rf'\(property "{re.escape(name)}" "[^"]*"'
        if re.search(pattern, symbol):
            return re.sub(pattern, f'(property "{name}" "{escaped_value}"', symbol, count=1)
        insert = f'      (property "{name}" "{escaped_value}" (at 0 0 0) (effects (font (size 1.27 1.27)) hide))\n'
        first_newline = symbol.find("\n")
        if first_newline < 0:
            return symbol
        return symbol[: first_newline + 1] + insert + symbol[first_newline + 1 :]

    def _property_value(self, symbol: str, name: str) -> str | None:
        match = re.search(rf'\(property "{re.escape(name)}" "([^"]*)"', symbol)
        return match.group(1) if match else None

    def _rewrite_footprint(self, text: str, footprint_name: str, value: str) -> str:
        text = re.sub(r'^\(footprint\s+"[^"]+"', f'(footprint "{footprint_name}"', text, count=1)
        text = re.sub(
            r'\(property "Value" "[^"]+"',
            f'(property "Value" "{value}"',
            text,
            count=1,
        )
        if "PCBStream downloaded KiCad footprint candidate" not in text:
            text = text.replace(
                "\n  (tags ",
                '\n  (descr "PCBStream downloaded KiCad footprint candidate; review package and land pattern before fabrication")\n  (tags ',
                1,
            )
        return text

    def _footprint_search_terms(self, block: Any, symbol_footprint_hint: str | None) -> list[str]:
        component = block.main_component
        existing_footprint = component.footprint.split(":", 1)[1] if ":" in component.footprint else component.footprint
        if "PLACEHOLDER" in existing_footprint.upper():
            existing_footprint = ""
        raw_terms = [
            symbol_footprint_hint.split(":", 1)[1] if symbol_footprint_hint and ":" in symbol_footprint_hint else symbol_footprint_hint,
            component.mpn,
            component.value,
            existing_footprint,
            self._specific_package_hint(component.purpose),
            self._specific_package_hint(block.summary),
        ]
        return _unique_terms(raw_terms)

    def _footprint_dirs_for(self, search_term: str) -> list[str]:
        token = search_term.lower()
        dirs = list(self.footprint_dirs)
        if any(item in token for item in ("lga", "land grid")):
            dirs.insert(0, "Package_LGA.pretty")
        if any(item in token for item in ("qfn", "dfn", "ufqf", "tqfn")):
            dirs.insert(0, "Package_DFN_QFN.pretty")
        if any(item in token for item in ("bga", "csp", "wlcsp")):
            dirs.insert(0, "Package_CSP.pretty")
        return _dedupe(dirs)

    def _symbol_dirs_for(self, part_number: str) -> list[str]:
        token = part_number.lower()
        dirs = list(self.symbol_dirs)
        if any(item in token for item in ("mpu", "imu", "accel", "gyro")):
            dirs.insert(0, "Sensor_Motion.kicad_symdir")
        if any(item in token for item in ("vl53", "tof", "optical", "laser")):
            dirs.insert(0, "Interface_Optical.kicad_symdir")
            dirs.insert(1, "Sensor.kicad_symdir")
        return _dedupe(dirs)

    def _package_hint(self, text: str) -> str:
        match = re.search(r"\b(?:LGA|QFN|DFN|BGA|WLCSP|CSP|TSSOP|SOIC|SOT)[-_ ]?\d+[A-Za-z0-9_.-]*", text or "", re.IGNORECASE)
        return match.group(0) if match else ""

    def _specific_package_hint(self, text: str) -> str:
        hint = self._package_hint(text)
        if not hint:
            return ""
        if re.search(r"\d(?:x|X)\d", hint) or re.search(r"\bP\d", hint, re.IGNORECASE):
            return hint
        return ""


def _normalised_token(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "", str(value).upper())


def _balanced_sexpr(text: str, start: int) -> str | None:
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def _unique_terms(values: list[str]) -> list[str]:
    terms: list[str] = []
    for value in values:
        if not value:
            continue
        stripped = str(value).strip()
        if not stripped:
            continue
        terms.append(stripped)
    return _dedupe(terms)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped
