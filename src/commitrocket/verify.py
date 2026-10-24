import logging
import subprocess
import time
from pathlib import PurePosixPath

from commitrocket.errors import CommitRocketError, GitError
from commitrocket.git import get_remote_head, run_git
from commitrocket.lfs import LFS_EXCLUDED

logger = logging.getLogger(__name__)

POINTER_PREFIX = b"version https://git-lfs.github.com/spec/v1"
MAX_POINTER_BYTES = 1024


def verify_remote_head(repo, remote, ref, retries=0, sleep=time.sleep):
    """Raise unless the remote's branch points at the local HEAD."""
    local = run_git(repo, "rev-parse", "HEAD").stdout.strip()

    attempt = 0
    while True:
        try:
            remote_head = get_remote_head(repo, remote, ref)
            break
        except GitError:
            if attempt >= retries:
                raise
            attempt += 1
            sleep(2**attempt)

    if remote_head != local:
        raise CommitRocketError(
            f"Push verification failed: {remote} {ref} is at "
            f"{(remote_head or 'nothing')[:10]} but local HEAD is {local[:10]}."
        )
    logger.info("Verified %s %s is at %s", remote, ref, local[:10])


def expected_lfs_paths(selected, lfs_paths):
    """Files in a batch that should have been stored as LFS pointers."""
    wanted = set(lfs_paths)
    return [
        path
        for path in selected
        if path in wanted and PurePosixPath(path).name not in LFS_EXCLUDED
    ]


def _git_cat_file(repo, mode, specs):
    result = subprocess.run(
        ["git", "-C", str(repo), "cat-file", mode],
        input="".join(f"{spec}\n" for spec in specs).encode("utf-8"),
        capture_output=True,
    )
    if result.returncode != 0:
        error = result.stderr.decode(errors="replace")
        raise GitError(f"git cat-file failed:\n{error}")
    return result.stdout


def _is_pointer(content):
    return content.startswith(POINTER_PREFIX)


def unpushed_has_lfs_pointers(repo, revs):
    """True if commits not yet pushed contain LFS pointer files.

    Pushing those without the LFS hooks installed would publish pointers whose
    data was never uploaded.
    """
    objects = run_git(repo, "rev-list", "--objects", *revs).stdout
    if not objects.strip():
        return False

    info = _git_cat_file(
        repo,
        "--batch-check=%(objecttype) %(objectname) %(objectsize) %(rest)",
        objects.splitlines(),
    )
    small = []
    for line in info.decode("utf-8", errors="replace").splitlines():
        kind, name, size = (line.split(" ", 3) + ["", "", ""])[:3]
        if kind == "blob" and size.isdigit() and int(size) <= MAX_POINTER_BYTES:
            small.append(name)

    if not small:
        return False

    data = _git_cat_file(repo, "--batch", small)
    position = 0
    for _ in small:
        newline = data.index(b"\n", position)
        size = int(data[position:newline].split()[2])
        content = data[newline + 1 : newline + 1 + size]
        position = newline + 1 + size + 1
        if _is_pointer(content):
            return True
    return False


def find_non_pointers(repo, paths):
    """Paths whose committed content in HEAD is not an LFS pointer."""
    if not paths:
        return []

    specs = [f"HEAD:{path}" for path in paths]
    sizes = _git_cat_file(repo, "--batch-check=%(objectsize)", specs)
    sizes = sizes.decode("utf-8", errors="replace").splitlines()

    bad = []
    small = []
    for path, size in zip(paths, sizes, strict=True):
        if size.endswith("missing") or int(size) > MAX_POINTER_BYTES:
            bad.append(path)
        else:
            small.append(path)

    if small:
        data = _git_cat_file(repo, "--batch", [f"HEAD:{path}" for path in small])
        position = 0
        for path in small:
            newline = data.index(b"\n", position)
            size = int(data[position:newline].split()[2])
            content = data[newline + 1 : newline + 1 + size]
            position = newline + 1 + size + 1
            if not content.startswith(POINTER_PREFIX):
                bad.append(path)

    return bad
