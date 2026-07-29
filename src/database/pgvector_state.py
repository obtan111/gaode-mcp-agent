_PGVECTOR_AVAILABLE = True


def set_pgvector_available(available: bool):
    global _PGVECTOR_AVAILABLE
    _PGVECTOR_AVAILABLE = available


def is_pgvector_available() -> bool:
    return _PGVECTOR_AVAILABLE