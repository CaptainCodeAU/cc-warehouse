"""Read-only questions about the archive, asked through a bounded thread pool.

Ticket 46 option A step 1 (open item W-20260929-A91; ruling: Gavin, 2026-09-29).
With the archive on SMB over Wi-Fi the cost is paid PER FILE OPENED, not per byte:
one small file takes 50 to 64 ms cold, one at a time, and the daily sweep spent
4h30m waiting on the share with 16 minutes of CPU. Reads that overlap cost far
less each (21 / 11 / 7 ms per file at 8 / 16 / 32 threads, measured on the share).

READS ONLY, and that is the whole contract of this module. Nothing here writes,
and nothing that calls it hands a writer to a worker: every write stays on the
main thread, in the order it always had, through the same writers
(tests/test_parallel_reads.py::test_no_write_happens_off_the_main_thread).
Nor is the SQLite catalog connection ever shared with a worker.

Two shapes, because the callers need two things:

- `map_reads` answers a question per item and hands the answers back in item
  order. A worker that raises becomes that item's `Read.error`, re-raised by
  `Read.get()` where the serial code would have met it, so a batch reports the
  item and carries on exactly as before (R10).
- `read_ahead` answers nothing. It reads the files a serial writer is about to
  re-read, one chunk ahead, so the writer's own compare finds them in the SMB
  client's cache (measured: a just-read file re-reads in about 0 ms and the
  cache fades within 20 to 60 s). Correctness never depends on it: a warm-up
  that raises or misses a file only costs the time it was meant to save.

`workers <= 1` runs everything inline on the calling thread and starts no pool,
which is both the serial baseline the tests compare against and the reason the
single-session hook path can never start one.
"""

from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import cast

# Threads per pool. Measured on the share over Wi-Fi, 2026-09-29, against real
# archive folders (harness/tickets/46-network-share-running-cost.md):
# 16 is where the per-file cost flattens; 32 buys little more and doubles the
# worst-case bytes in flight. Read at call time, so a test can set it to 1 for
# the serial baseline.
READ_WORKERS = 16

# Items checked ahead of where the serial loop acts. The build acts on a head
# at most this many heads after it was checked, so a check is seconds old, not
# hours (ticket 46; ideas-sweep-software "Idea 3"). Also the read-ahead span,
# kept well inside the 20 s the SMB client cache was measured to hold a file.
READ_CHUNK = 64


@dataclass(frozen=True)
class Read[R]:
    """One item's answer: its value, or the exception its read raised."""

    value: R | None = None
    error: Exception | None = None

    def get(self) -> R:
        """The value, or the worker's exception raised here, on the caller's
        thread, where the serial code would have met it."""
        if self.error is not None:
            raise self.error
        return cast(R, self.value)


def _answer[T, R](fn: Callable[[T], R], item: T) -> Read[R]:
    try:
        return Read(fn(item))
    except Exception as exc:  # noqa: BLE001 - R10: the item's failure, handed back
        return Read(error=exc)


def map_reads[T, R](
    fn: Callable[[T], R], items: Sequence[T], *, workers: int | None = None
) -> list[Read[R]]:
    """`fn` over every item, at most `workers` at once, answers in item order.

    BYTES IN FLIGHT are bounded by the pool, not by a budget: each worker holds
    one item's reads at a time, so the peak is `workers` times the largest file
    one call reads, never a whole set of files.
    """
    count = READ_WORKERS if workers is None else workers
    if count <= 1 or len(items) <= 1:
        return [_answer(fn, item) for item in items]
    def one(item: T) -> Read[R]:
        return _answer(fn, item)

    with ThreadPoolExecutor(max_workers=min(count, len(items))) as pool:
        return list(pool.map(one, items))


def chunks[T](items: Sequence[T], size: int | None = None) -> Iterator[Sequence[T]]:
    """`items` in consecutive slices of `size` (default `READ_CHUNK`)."""
    step = max(1, READ_CHUNK if size is None else size)
    for start in range(0, len(items), step):
        yield items[start : start + step]


def read_ahead[T](
    items: Sequence[T],
    warm: Callable[[T], object],
    *,
    chunk: int | None = None,
    workers: int | None = None,
) -> Iterator[T]:
    """Yield `items` in order; just before each chunk, run `warm` over it in the pool.

    `warm`'s answers and exceptions are both discarded: it exists to have READ
    something, and the serial loop that consumes this iterator does the real
    work unchanged. With one worker, or a chunk of one item, nothing is warmed:
    warming inline, one file at a time, would only double the reads.
    """
    count = READ_WORKERS if workers is None else workers
    if count <= 1:
        yield from items
        return
    for part in chunks(items, chunk):
        if len(part) > 1:
            map_reads(warm, part, workers=count)
        yield from part
