"""Coordinate independent outbox consumers without allowing event races."""

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from apps.worker.worker.acquisition_worker import AcquisitionWorker
from apps.worker.worker.knowledge_processing_worker import KnowledgeProcessingWorker
from apps.worker.worker.notification_worker import NotificationWorker
from apps.worker.worker.settings import WorkerSettings
from apps.worker.worker.sla_worker import SlaWorker


class ApplicationWorker:
    def __init__(
        self,
        sla_worker: SlaWorker,
        notification_worker: NotificationWorker,
        acquisition_worker: AcquisitionWorker,
        knowledge_processing_worker: KnowledgeProcessingWorker,
        settings: WorkerSettings,
    ) -> None:
        self._sla = sla_worker
        self._notifications = notification_worker
        self._acquisition = acquisition_worker
        self._knowledge_processing = knowledge_processing_worker
        self._settings = settings

    async def run_forever(self) -> None:
        next_due_scan = datetime.now(UTC)
        while True:
            handled = 0
            for _ in range(self._settings.worker_batch_size):
                if await self._sla.process_one():
                    handled += 1
                    continue
                if await self._notifications.process_one():
                    handled += 1
                    continue
                if await self._acquisition.process_one():
                    handled += 1
                    continue
                if await self._knowledge_processing.process_one():
                    handled += 1
                    continue
                break
            now = datetime.now(UTC)
            if now >= next_due_scan:
                await self._sla.process_due(now)
                next_due_scan = now + timedelta(seconds=self._settings.worker_due_scan_seconds)
            if handled == 0:
                await asyncio.sleep(self._settings.worker_poll_seconds)


def create_application_worker(settings: WorkerSettings) -> tuple[ApplicationWorker, AsyncEngine]:
    engine = create_async_engine(
        settings.worker_database_url.get_secret_value(),
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    return (
        ApplicationWorker(
            SlaWorker(sessions, settings),
            NotificationWorker(sessions, settings),
            AcquisitionWorker(sessions, settings),
            KnowledgeProcessingWorker(sessions, settings),
            settings,
        ),
        engine,
    )
