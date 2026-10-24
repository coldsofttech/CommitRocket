from commitrocket.git import get_file_size

MIB = 1024 * 1024

SEQUENTIAL = "sequential"
DETERMINISTIC = "deterministic"
SOFT = "soft"
BATCH_TYPES = (SEQUENTIAL, DETERMINISTIC, SOFT)


def _select_in_order(
    eligible, limit_bytes, max_bytes, lfs_files, lfs_limit_bytes, soft
):
    """Take files strictly in order, stopping at the first one that doesn't fit.

    soft: keep adding until the batch reaches or passes limit_bytes, as long as
    the total stays within max_bytes. Otherwise the batch never passes limit_bytes
    (a single larger file travels alone).
    """
    first_path, first_size = eligible[0]
    selected = []
    total_bytes = 0

    if first_path in lfs_files and first_size > limit_bytes:
        # Consecutive LFS files are grouped so they can upload concurrently.
        for path, size in eligible:
            if path not in lfs_files or size <= limit_bytes:
                break
            if selected and total_bytes + size > lfs_limit_bytes:
                break
            selected.append(path)
            total_bytes += size
        return selected, total_bytes

    for path, size in eligible:
        if selected:
            if soft and (total_bytes >= limit_bytes or total_bytes + size > max_bytes):
                break
            if not soft and total_bytes + size > limit_bytes:
                break
        selected.append(path)
        total_bytes += size

    return selected, total_bytes


def select_batch(
    repo,
    files,
    limit_bytes,
    max_bytes,
    lfs_files=frozenset(),
    lfs_limit_bytes=0,
    batch_type=DETERMINISTIC,
):
    """Choose the next batch of files.

    Files exceeding max_bytes are deferred. batch_type decides how the rest are
    picked:

    - deterministic: a file above limit_bytes goes first and alone, otherwise
      files are packed first-fit, skipping any that don't fit.
    - sequential: strict order; stops at the first file that doesn't fit.
    - soft: strict order; the limit may be crossed (up to max_bytes in total).

    LFS files above limit_bytes are grouped up to lfs_limit_bytes (always at
    least one file) so their uploads can run concurrently.
    """
    sized_files = [(path, get_file_size(repo, path)) for path in files]

    deferred = [(path, size) for path, size in sized_files if size > max_bytes]

    eligible = [(path, size) for path, size in sized_files if size <= max_bytes]

    if eligible and batch_type != DETERMINISTIC:
        selected, total_bytes = _select_in_order(
            eligible,
            limit_bytes,
            max_bytes,
            lfs_files,
            lfs_limit_bytes,
            soft=batch_type == SOFT,
        )
        return selected, deferred, total_bytes

    # Process a larger-than-normal file by itself.
    large_files = [(path, size) for path, size in eligible if size > limit_bytes]

    if large_files:
        lfs_large = [(path, size) for path, size in large_files if path in lfs_files]
        if lfs_large:
            selected = []
            total_bytes = 0
            for path, size in lfs_large:
                if not selected or total_bytes + size <= lfs_limit_bytes:
                    selected.append(path)
                    total_bytes += size
            return selected, deferred, total_bytes

        path, size = large_files[0]
        return [path], deferred, size

    # Pack ordinary files without exceeding the normal batch limit.
    selected = []
    total_bytes = 0

    for path, size in eligible:
        if total_bytes + size <= limit_bytes:
            selected.append(path)
            total_bytes += size

    return selected, deferred, total_bytes


def plan_batches(
    repo,
    files,
    limit_bytes,
    max_bytes,
    lfs_files=frozenset(),
    lfs_limit_bytes=0,
    batch_type=DETERMINISTIC,
):
    """All batches a run would create, plus the files deferred for being too large.

    Returns ([(paths, total_bytes), ...], [(path, size), ...]).
    """
    remaining = list(files)
    batches = []
    deferred = []

    while remaining:
        selected, deferred, total_bytes = select_batch(
            repo,
            remaining,
            limit_bytes,
            max_bytes,
            lfs_files,
            lfs_limit_bytes,
            batch_type,
        )

        if not selected:
            break

        batches.append((selected, total_bytes))
        selected_set = set(selected)
        remaining = [path for path in remaining if path not in selected_set]

    return batches, deferred


def estimate_batch_count(
    repo,
    files,
    limit_bytes,
    max_bytes,
    lfs_files=frozenset(),
    lfs_limit_bytes=0,
    batch_type=DETERMINISTIC,
):
    """Estimate batches using the same selection rules as execution."""
    remaining = list(files)
    batches = 0

    while remaining:
        selected, _, _ = select_batch(
            repo,
            remaining,
            limit_bytes,
            max_bytes,
            lfs_files,
            lfs_limit_bytes,
            batch_type,
        )

        if not selected:
            break

        selected_set = set(selected)
        remaining = [path for path in remaining if path not in selected_set]
        batches += 1

    return batches
