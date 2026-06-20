from __future__ import annotations

import re
from dataclasses import dataclass


PART_NUMBER_RE = re.compile(r"\b(?=[A-Z0-9-]*\d)(?=[A-Z0-9-]*[A-Z])[A-Z][A-Z0-9-]{3,}\b", re.I)

IGNORED_PART_TOKENS = {
    "I2C",
    "SPI",
    "USB",
    "GPIO",
    "UART",
    "CAN",
    "GND",
    "VCC",
    "VDD",
    "VDDIO",
    "QFN",
    "LGA",
}

CONTEXT_PART_PREFIXES = (
    "ARDUINO",
    "ATMEGA",
    "ATSAMD",
    "ESP32",
    "ESP8266",
    "MSP430",
    "NRF52",
    "PIC",
    "RASPBERRY",
    "RP2040",
    "RPI",
    "STM32",
    "TEENSY",
)

PACKAGE_RE = re.compile(
    r"^(?:BGA|DFN|DIP|LGA|LQFP|MSOP|QFN|SOIC|SOT|TQFP|TSSOP|UQFN|WLCSP)-?\d+$",
    re.I,
)

GENERATION_TERMS = (
    "add",
    "build",
    "connect",
    "create",
    "draft",
    "generate",
    "hook up",
    "insert",
    "make",
    "need",
    "place",
    "use",
    "want",
)

EXPLORATORY_TERMS = (
    "compare",
    "option",
    "options",
    "recommend",
    "suggest",
    "tradeoff",
    "trade-off",
    "which",
    "what",
)

CATEGORY_TERMS = (
    "6-axis",
    "9-axis",
    "accelerometer",
    "adc",
    "amplifier",
    "charger",
    "converter",
    "dac",
    "driver",
    "fuel gauge",
    "gps",
    "gyro",
    "gyroscope",
    "humidity",
    "ic",
    "imu",
    "module",
    "pmic",
    "pressure",
    "regulator",
    "sensor",
    "switch",
    "temperature",
)

COMPLEX_CATEGORY_TERMS = (
    "buck",
    "boost",
    "charger",
    "ddr",
    "ethernet",
    "fpga",
    "high speed",
    "motor driver",
    "pmic",
    "processor",
    "radio",
    "rf",
    "switching regulator",
    "usb-c",
    "wifi",
)


@dataclass(frozen=True)
class PartMention:
    part_number: str
    role: str
    reason: str


@dataclass(frozen=True)
class PartIntent:
    target_part_numbers: list[str]
    context_part_numbers: list[str]
    all_part_numbers: list[str]
    has_generation_intent: bool
    has_exploratory_intent: bool
    has_category_request: bool
    complexity: str
    complexity_reasons: list[str]
    mentions: list[PartMention]


def analyse_part_intent(message: str) -> PartIntent:
    text = message.lower()
    has_generation_intent = _contains_any(text, GENERATION_TERMS)
    has_exploratory_intent = _contains_any(text, EXPLORATORY_TERMS)
    has_category_request = _contains_any(text, CATEGORY_TERMS)
    mentions: list[PartMention] = []
    target_parts: list[str] = []
    context_parts: list[str] = []
    all_parts: list[str] = []

    for match in PART_NUMBER_RE.finditer(message.upper()):
        token = match.group(0).strip("-")
        if not _is_candidate_part_token(token):
            continue

        role, reason = _classify_mention(
            message,
            match.start(),
            match.end(),
            token,
            has_generation_intent=has_generation_intent,
            has_exploratory_intent=has_exploratory_intent,
        )
        mentions.append(PartMention(part_number=token, role=role, reason=reason))
        _append_unique(all_parts, token)
        if role == "context":
            _append_unique(context_parts, token)
        else:
            _append_unique(target_parts, token)

    complexity, complexity_reasons = _assess_complexity(text, target_parts, has_category_request)
    return PartIntent(
        target_part_numbers=target_parts,
        context_part_numbers=context_parts,
        all_part_numbers=all_parts,
        has_generation_intent=has_generation_intent,
        has_exploratory_intent=has_exploratory_intent,
        has_category_request=has_category_request,
        complexity=complexity,
        complexity_reasons=complexity_reasons,
        mentions=mentions,
    )


def extract_target_part_numbers(message: str) -> list[str]:
    return analyse_part_intent(message).target_part_numbers


def normalise_part_number(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def _classify_mention(
    message: str,
    start: int,
    end: int,
    token: str,
    *,
    has_generation_intent: bool,
    has_exploratory_intent: bool,
) -> tuple[str, str]:
    prefix = message[max(0, start - 90) : start].lower()
    suffix = message[end : min(len(message), end + 80)].lower()
    normalised = normalise_part_number(token)

    context_prefix = re.search(
        r"\b(?:for|from|on|onto|to|using|with)\s+(?:an?\s+|the\s+|my\s+|a\s+)?$",
        prefix,
    )
    if context_prefix:
        return "context", "Part appears after a context preposition such as for/with/using."

    if re.match(
        r"\s+(?:board|controller|dev\s+board|development\s+board|host|mcu|microcontroller|project)\b",
        suffix,
    ):
        return "context", "Part is described as the host board, controller, MCU, or project context."

    explicit_target = re.search(
        r"\b(?:add|build|choose|connect|create|draft|generate|insert|make|pick|place|select|use)\s+"
        r"(?:an?\s+|the\s+|a\s+)?(?:[a-z0-9+/_-]+\s+){0,5}$",
        prefix,
    )
    if explicit_target:
        return "target", "Part appears after an explicit add/use/create/select instruction."

    if _looks_like_context_controller(normalised) and (has_exploratory_intent or has_generation_intent):
        return "context", "Part looks like a host controller or development-board family."

    return "target", "Part number is the best available target component."


def _assess_complexity(text: str, target_parts: list[str], has_category_request: bool) -> tuple[str, list[str]]:
    reasons = [term for term in COMPLEX_CATEGORY_TERMS if term in text]
    if reasons:
        return "complex", [f"Request mentions {term}." for term in reasons[:3]]
    if len(target_parts) > 1:
        return "moderate", ["Request mentions multiple target part numbers."]
    if has_category_request:
        return "moderate", ["Request is category-level and needs part selection before generation."]
    return "simple", []


def _is_candidate_part_token(token: str) -> bool:
    if re.fullmatch(r"C\d{3,}", token):
        return False
    if token in IGNORED_PART_TOKENS:
        return False
    if PACKAGE_RE.fullmatch(token):
        return False
    return True


def _looks_like_context_controller(normalised_token: str) -> bool:
    return any(normalised_token.startswith(prefix) for prefix in CONTEXT_PART_PREFIXES)


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text) for term in terms)


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)
