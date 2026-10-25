from dataclasses import dataclass, field

from commitrocket.batching import DETERMINISTIC
from commitrocket.lfs import LFS_THRESHOLD_MIB
from commitrocket.template import DEFAULT_TEMPLATE


@dataclass
class RunOptions:
    """Everything a run needs, as parsed from the command line and config file."""

    repo: str = "."
    message: str = ""
    number: int = 1
    force: bool = False
    limit_mib: int = 100
    max_mib: int = 300
    batch_type: str = DETERMINISTIC
    message_template: str = DEFAULT_TEMPLATE
    remote: str | None = None
    branch: str | None = None
    no_push: bool = False
    dry_run: bool = False
    retries: int = 3
    post_buffer_mib: int | None = None
    compression_threads: int | None = None
    use_lfs: bool = False
    lfs_threshold_mib: int = LFS_THRESHOLD_MIB
    lfs_threads: int | None = None
    lfs_batch_mib: int | None = None
    lfs_commit_rules: bool = True
    include: list = field(default_factory=list)
    exclude: list = field(default_factory=list)
    include_from: list = field(default_factory=list)
    exclude_from: list = field(default_factory=list)
    # Files the run itself writes; they are never committed, even inside the repo.
    log_file: str | None = None
    report: str | None = None
