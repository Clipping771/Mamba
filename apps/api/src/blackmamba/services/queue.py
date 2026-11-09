"""Background job queue (Redis + RQ). Abstracted so tests can capture enqueued jobs."""

import uuid
from functools import lru_cache
from typing import Protocol

from redis import Redis
from rq import Queue

from blackmamba.core.config import get_settings

ARCHIVE_QUEUE = "archive"
ARCHIVE_JOB_FUNC = "blackmamba.workers.archive.run_archive_job"


class JobQueue(Protocol):
    def enqueue_archive(self, job_id: uuid.UUID) -> None: ...


class RQJobQueue:
    def __init__(self, redis_url: str, timeout_seconds: int) -> None:
        self._queue = Queue(ARCHIVE_QUEUE, connection=Redis.from_url(redis_url))
        self._timeout = timeout_seconds

    def enqueue_archive(self, job_id: uuid.UUID) -> None:
        self._queue.enqueue(
            ARCHIVE_JOB_FUNC,
            str(job_id),
            job_id=f"archive-{job_id}",
            job_timeout=self._timeout,
            result_ttl=86400,
            failure_ttl=7 * 86400,
        )


@lru_cache
def get_job_queue() -> JobQueue:
    settings = get_settings()
    # Browser timeout + time to upload/hash/save.
    return RQJobQueue(settings.redis_url, settings.archive_timeout_seconds + 120)
