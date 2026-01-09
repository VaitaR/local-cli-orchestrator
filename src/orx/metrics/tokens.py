"""Token counting utilities using tiktoken."""

from __future__ import annotations

import structlog

logger = structlog.get_logger()

# Global tokenizer cache
_TOKENIZER_CACHE: dict[str, object] = {}


def estimate_tokens(text: str, model: str | None = None) -> int:
    """Estimate token count for text using tiktoken.

    Args:
        text: Text to count tokens for.
        model: Model name (e.g., "gpt-4", "gpt-3.5-turbo"). If None, uses cl100k_base.

    Returns:
        Estimated token count.
    """
    if not text:
        return 0

    try:
        import tiktoken
    except ImportError:
        logger.warning("tiktoken not installed, using rough character estimate")
        # Rough fallback: ~4 characters per token
        return len(text) // 4

    # Determine encoding
    encoding_name = "cl100k_base"  # Default for GPT-4 and most modern models

    if model:
        # Map common model names to encodings
        model_lower = model.lower()
        if "gpt-4" in model_lower or "gpt-3.5" in model_lower or "gpt-5" in model_lower:
            encoding_name = "cl100k_base"
        elif "gemini" in model_lower or "claude" in model_lower or "sonnet" in model_lower or "opus" in model_lower:
            # Gemini and Claude use similar tokenization to GPT-4
            encoding_name = "cl100k_base"
        elif "grok" in model_lower or "cursor" in model_lower:
            # Grok/Cursor likely use cl100k_base or similar
            encoding_name = "cl100k_base"
        elif "codex" in model_lower:
            encoding_name = "p50k_base"

    # Get or create tokenizer
    cache_key = encoding_name
    if cache_key not in _TOKENIZER_CACHE:
        try:
            _TOKENIZER_CACHE[cache_key] = tiktoken.get_encoding(encoding_name)
        except Exception as e:
            logger.warning(
                "Failed to load tiktoken encoding, using fallback",
                encoding=encoding_name,
                error=str(e),
            )
            return len(text) // 4

    tokenizer = _TOKENIZER_CACHE[cache_key]

    try:
        tokens = tokenizer.encode(text)  # type: ignore[union-attr]
        return len(tokens)
    except Exception as e:
        logger.warning("Failed to encode text with tiktoken", error=str(e))
        return len(text) // 4
