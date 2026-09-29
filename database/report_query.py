from datetime import date

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from database.db import async_session_maker
from database.models import ReportDelivery


class ReportRepository:
    @staticmethod
    async def get(chat_id: int, kind: str, start: date):
        async with async_session_maker() as session:
            return await session.get(ReportDelivery, (chat_id, kind, start))

    @staticmethod
    async def prepare(chat_id: int, kind: str, start: date, chunks: list[str]):
        async with async_session_maker() as session:
            await session.execute(
                insert(ReportDelivery)
                .values(
                    chat_id=chat_id,
                    kind=kind,
                    period_start=start,
                    chunks=chunks,
                    next_chunk=0,
                )
                .on_conflict_do_nothing()
            )
            await session.commit()
            return await session.get(ReportDelivery, (chat_id, kind, start))

    @staticmethod
    async def advance(chat_id: int, kind: str, start: date, next_chunk: int):
        async with async_session_maker() as session:
            row = await session.get(ReportDelivery, (chat_id, kind, start))
            row.next_chunk = next_chunk
            await session.commit()

    @staticmethod
    async def pending(chat_id: int):
        async with async_session_maker() as session:
            rows = (
                await session.scalars(
                    select(ReportDelivery).where(
                        ReportDelivery.chat_id == chat_id,
                        ReportDelivery.next_chunk < func.json_array_length(ReportDelivery.chunks),
                    )
                )
            ).all()
            return list(rows)
