from fastapi import FastAPI
from api.routers import api_router

app = FastAPI(title="Auctions API")

# Підключаємо всі ендпоінти одним рядком
app.include_router(api_router, prefix="/api/v1")






# from fastapi import FastAPI, Depends, HTTPException
# from contextlib import asynccontextmanager
# from sqlalchemy.ext.asyncio import AsyncSession
# from sqlalchemy import select, func
# from sqlalchemy.dialects.mysql import insert as mysql_insert # <--- Специфічно для MariaDB
# from typing import List

# from app.database import get_db, engine, Base
# from app.schemas import BatchCheckRequest, BatchCheckRequestLink, BatchCheckResponse

# from app.models import Lot, DimAuction, IaaiLot
# import logging, sys
# from pathlib import Path

# log_dir = Path('app/logs')
# log_dir.mkdir(parents=True, exist_ok=True)
# log_file_path = log_dir / 'check_if_present.log'

# logging.basicConfig(
#     level=logging.INFO,
#     format="%(asctime)s [%(levelname)s] %(message)s",
#     handlers=[
#         logging.FileHandler(log_file_path, encoding='utf-8'), # Запис у файл
#         logging.StreamHandler(sys.stdout)                     # Вивід у консоль
#     ]
# )
# logger = logging.getLogger("CheckIfPresent")

# @asynccontextmanager
# async def lifespan(app: FastAPI):
#     # Код, що виконується при запуску
#     logger.info("Starting up database...")
#     async with engine.begin() as conn:
#         await conn.run_sync(Base.metadata.create_all)

#     yield  # Тут додаток працює

#     # Код, що виконується при вимкненні
#     logger.info("Shutting down database...")
#     await engine.dispose()

# app = FastAPI(
#     title="Auction Core API",
#     lifespan=lifespan
# )

# # === 1. ПЕРЕВІРКА НАЯВНОСТІ (BATCH CHECK) ===
# @app.post("/lots/get-missing-from-batch", response_model=BatchCheckResponse)
# async def get_missing_lots(request: BatchCheckRequest, db: AsyncSession = Depends(get_db)):
#     try:
#         # 1. Формуємо запит
#         stmt = (
#             select(Lot.lot_number)
#             .join(DimAuction, Lot.auction_id == DimAuction.id)
#             .where(
#                 # Приводимо обидві сторони до нижнього регістру для надійного порівняння
#                 func.lower(DimAuction.slug) == request.auction_type.lower(),
#                 # Шукаємо тільки серед тих лотів, що прийшли в масиві
#                 Lot.lot_number.in_(request.lot_numbers)
#             )
#         )

#         # 2. Виконуємо запит
#         result = await db.execute(stmt)

#         # 3. ВАЖЛИВО: scalars() перетворює [('id',)] у просто ['id']
#         existing_lots_list = result.scalars().all()

#         # 4. Робимо множину для миттєвого пошуку
#         existing_set = set(existing_lots_list)

#         # 5. Знаходимо те, чого немає (порівнюємо str з str)
#         missing_ids = [ln for ln in request.lot_numbers if ln not in existing_set]

#         return BatchCheckResponse(missing_ids=missing_ids)

#     except Exception as e:
#         # Дивись цей принт у терміналі, там буде справжня причина!
#         logger.error(f"ERROR is HERE: {e}")
#         raise HTTPException(status_code=500, detail=str(e))

# @app.post("/lots/get-missing-from-batch-links", response_model=BatchCheckResponse)
# async def get_missing_lots_iaai(request: BatchCheckRequestLink, db: AsyncSession = Depends(get_db)):
#     try:
#         # 1. Формуємо запит
#         stmt = (
#             select(IaaiLot.lot_url)
#             # .join(DimAuction, Lot.auction_id == DimAuction.id)
#             .where(
#                 # Приводимо обидві сторони до нижнього регістру для надійного порівняння
#                 # func.lower(DimAuction.slug) == request.auction_type.lower(),
#                 # Шукаємо тільки серед тих лотів, що прийшли в масиві
#                 IaaiLot.lot_url.in_(request.links)
#             )
#         )

#         # 2. Виконуємо запит
#         result = await db.execute(stmt)

#         # 3. ВАЖЛИВО: scalars() перетворює [('id',)] у просто ['id']
#         existing_lots_list = result.scalars().all()

#         # 4. Робимо множину для миттєвого пошуку
#         existing_set = set(existing_lots_list)

#         # 5. Знаходимо те, чого немає (порівнюємо str з str)
#         missing_ids = [ln for ln in request.links if ln not in existing_set]

#         return BatchCheckResponse(missing_ids=missing_ids)

#     except Exception as e:
#         # Дивись цей принт у терміналі, там буде справжня причина!
#         logger.error(f"ERROR is HERE: {e}")
#         raise HTTPException(status_code=500, detail=str(e))


# # === 2. ДОДАВАННЯ/ОНОВЛЕННЯ ЛОТА (UPSERT для MariaDB) ===
# # Це приклад, як правильно записувати дані в MariaDB, щоб не було помилок дублікатів
# @app.post("/lots/upsert")
# async def upsert_lot(
#     lot_number: str,
#     auction_type: str,
#     status: str,
#     db: AsyncSession = Depends(get_db)
# ):
#     try:
#         # Готуємо інструкцію INSERT
#         insert_stmt = mysql_insert(Lot).values(
#             lot_number=lot_number,
#             auction_type=auction_type,
#             status=status,
#             data_json={}
#         )

#         # Кажемо: якщо такий (lot_number + auction_type) вже є,
#         # то онови поле status (ON DUPLICATE KEY UPDATE)
#         upsert_stmt = insert_stmt.on_duplicate_key_update(
#             status=insert_stmt.inserted.status
#         )

#         await db.execute(upsert_stmt)
#         await db.commit()
#         return {"status": "saved"}

#     except Exception as e:
#         await db.rollback()
#         raise HTTPException(status_code=500, detail=str(e))