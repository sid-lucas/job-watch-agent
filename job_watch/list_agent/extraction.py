"""Offer extraction from the observations of a list agent run, outside the agent conversation.

The code, not the agent, decides what is extracted: every observation that brought new
text. The full new text (Observation.new_text_full) is cut into chunks small enough for the
extractor to list every offer.
"""
CHUNK_CHARS = 8000      # target size of one chunk sent to the extractor
OVERLAP_LINES = 6       # lines repeated from the end of the previous chunk (an offer spans a few lines)


def chunks(text: str, max_chars: int = CHUNK_CHARS, overlap_lines: int = OVERLAP_LINES) -> list[str]:
    """Cut text between lines into chunks of at most max_chars, each one starting with the
    last overlap_lines lines of the previous chunk.

    A single line longer than max_chars is cut into pieces of max_chars. Every line of the
    text is in at least one chunk, in order.
    """
    lines: list[str] = []
    for line in text.splitlines():
        lines += [line[i:i + max_chars] for i in range(0, len(line), max_chars)] or [""]

    result: list[str] = []
    start = 0
    while start < len(lines):
        end, size = start, 0
        while end < len(lines) and (end == start or size + len(lines[end]) + 1 <= max_chars):
            size += len(lines[end]) + 1
            end += 1
        result.append("\n".join(lines[start:end]))
        if end == len(lines):
            break
        # Next chunk starts overlap_lines earlier, but always moves forward by at least one line
        start = max(end - overlap_lines, start + 1)
    return [chunk for chunk in result if chunk.strip()]
