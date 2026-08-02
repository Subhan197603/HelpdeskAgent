"""Deterministic structure-aware chunking with bounded token estimates."""

import hashlib
import json
import re
from dataclasses import asdict, dataclass

from ingestion.parsers import ParsedDocument, ParsedSection


@dataclass(frozen=True, slots=True)
class ChunkingConfig:
    target_tokens: int = 600
    maximum_tokens: int = 800
    minimum_tokens: int = 300
    overlap_tokens: int = 40

    def __post_init__(self) -> None:
        if not (50 <= self.minimum_tokens <= self.target_tokens <= self.maximum_tokens <= 2000):
            raise ValueError("Invalid semantic chunking bounds")
        if not 0 <= self.overlap_tokens <= self.minimum_tokens // 2:
            raise ValueError("Chunk overlap is excessive")

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


@dataclass(frozen=True, slots=True)
class Chunk:
    sequence: int
    heading_path: tuple[str, ...]
    content: str
    page_number: int | None
    anchor: str | None
    content_type: str
    token_count: int
    content_hash: str
    embedding_input: str
    embedding_input_hash: str


class SemanticChunker:
    name = "semantic-structure"
    version = "1"

    def __init__(self, config: ChunkingConfig | None = None) -> None:
        self.config = config or ChunkingConfig()

    def chunk(self, title: str, document: ParsedDocument) -> tuple[Chunk, ...]:
        groups: list[tuple[tuple[str, ...], list[ParsedSection]]] = []
        for section in document.sections:
            for piece in _split_oversized(section, self.config.maximum_tokens):
                combined = (
                    "\n\n".join([*(part.text for part in groups[-1][1]), piece.text])
                    if groups
                    else piece.text
                )
                if (
                    groups
                    and groups[-1][0] == piece.heading_path
                    and _tokens(combined) <= self.config.target_tokens
                    and piece.table_markdown is None
                ):
                    groups[-1][1].append(piece)
                else:
                    groups.append((piece.heading_path, [piece]))
        chunks: list[Chunk] = []
        for sequence, (heading, sections) in enumerate(groups, start=1):
            content = "\n\n".join(section.text for section in sections).strip()
            if not content:
                continue
            heading_text = " > ".join(heading)
            embedding_input = "\n".join(
                part
                for part in (
                    f"Title: {title}",
                    f"Heading: {heading_text}" if heading else "",
                    content,
                )
                if part
            )
            chunks.append(
                Chunk(
                    sequence,
                    heading,
                    content,
                    sections[0].page_number,
                    sections[0].anchor,
                    sections[0].content_type,
                    _tokens(content),
                    hashlib.sha256(content.encode()).hexdigest(),
                    embedding_input,
                    hashlib.sha256(embedding_input.encode()).hexdigest(),
                )
            )
        return tuple(chunks)


def _tokens(value: str) -> int:
    return max(1, len(re.findall(r"\w+|[^\w\s]", value, flags=re.UNICODE)))


def _split_oversized(section: ParsedSection, maximum: int) -> list[ParsedSection]:
    if _tokens(section.text) <= maximum or section.table_markdown is not None:
        return [section]
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", section.text) if part.strip()]
    if len(paragraphs) == 1:
        words = section.text.split()
        paragraphs = [
            " ".join(words[index : index + maximum]) for index in range(0, len(words), maximum)
        ]
    result: list[ParsedSection] = []
    buffer: list[str] = []
    for paragraph in paragraphs:
        if buffer and _tokens("\n\n".join([*buffer, paragraph])) > maximum:
            result.append(_piece(section, "\n\n".join(buffer)))
            buffer = []
        buffer.append(paragraph)
    if buffer:
        result.append(_piece(section, "\n\n".join(buffer)))
    return result


def _piece(section: ParsedSection, text: str) -> ParsedSection:
    return ParsedSection(
        section.heading_path,
        text,
        section.page_number,
        section.anchor,
        section.content_type,
    )
