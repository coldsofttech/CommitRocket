import time

# Wait for this much real upload time before trusting the measured speed.
MIN_SECONDS = 5.0


def format_duration(seconds):
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}"


class EtaEstimator:
    """ETA from the average speed of the whole run so far.

    Speed is bytes completed (including the part of the current batch already
    uploaded) divided by the time since the first batch started, so per-batch
    overhead such as `git add`, commit and push handshakes is included.
    """

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.started_at = None

    def start(self):
        if self.started_at is None:
            self.started_at = self.clock()

    def estimate(self, done_bytes, total_bytes):
        """Seconds remaining, or None while there is not enough data yet."""
        if self.started_at is None or done_bytes <= 0:
            return None

        elapsed = self.clock() - self.started_at
        if elapsed < MIN_SECONDS:
            return None

        remaining = max(0, total_bytes - done_bytes)
        return remaining / (done_bytes / elapsed)
