import logging
import os
from pathlib import Path

_logger = logging.getLogger("nba_chatbot")

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
_cache: dict[str, tuple[str, float]] = {}


def get_prompt_cached(name: str) -> str:
    cached, mtime = _cache.get(name, (None, 0))
    file_path = _PROMPTS_DIR / name

    try:
        current_mtime = os.path.getmtime(file_path)
    except OSError:
        _logger.warning("[prompt_cache] file not found: %s", file_path)
        return cached or f"<prompt {name} not found>"

    if cached is not None and current_mtime <= mtime:
        return cached

    content = file_path.read_text(encoding="utf-8")
    _cache[name] = (content, current_mtime)
    _logger.debug("[prompt_cache] loaded %s (%d chars)", name, len(content))
    return content


def clear_prompt_cache() -> None:
    _cache.clear()


def preload_prompts() -> None:
    if not _PROMPTS_DIR.is_dir():
        _logger.warning("[prompt_cache] prompts dir not found: %s", _PROMPTS_DIR)
        return
    for fpath in sorted(_PROMPTS_DIR.iterdir()):
        if fpath.suffix == ".txt":
            get_prompt_cached(fpath.name)
    _logger.info("[prompt_cache] preloaded %d prompts", len(_cache))
