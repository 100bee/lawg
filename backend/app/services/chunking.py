import re
from dataclasses import dataclass

from llama_index.core import Document as LlamaDocument
from llama_index.core.node_parser import SentenceSplitter

from app.config import settings


@dataclass(slots=True)
class Chunk:
    index: int
    heading: str
    content: str
    token_count: int


def _find_heading(content: str) -> str:
    match = re.search(r"^#{1,6}\s+(.+)$", content, flags=re.MULTILINE)
    return match.group(1).strip() if match else "본문"


def split_document(content: str, metadata: dict[str, str]) -> list[Chunk]:
    if metadata.get("document_type") in ("statute", "guide", "precedent", "sentencing"):
        # One article (or guide, precedent, guideline) = one chunk, so a citation always points at a whole source.
        content = content.strip()
        return [Chunk(index=0, heading=metadata.get("title", "본문")[:255], content=content,
                      token_count=len(content.split()))] if content else []
    splitter = SentenceSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )
    document = LlamaDocument(text=content, metadata=metadata)
    nodes = splitter.get_nodes_from_documents([document], show_progress=False)
    return [
        Chunk(
            index=index,
            heading=_find_heading(node.text),
            content=node.text.strip(),
            token_count=len(node.text.split()),
        )
        for index, node in enumerate(nodes)
        if node.text.strip()
    ]

