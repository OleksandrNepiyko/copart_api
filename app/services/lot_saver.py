import json
from sqlalchemy.ext.asyncio import AsyncSession
from schemas.common_schema import AuctionLotParsedData
from models.raw_tables import RawAuctionLot

async def save_raw_lot(parsed_data: AuctionLotParsedData, db: AsyncSession):
    # Конвертуємо Pydantic-модель у звичайний словник
    data_dict = parsed_data.model_dump()

    # Витягуємо списки і перетворюємо їх на JSON-рядки
    # ensure_ascii=False зберігає нормальні символи, якщо там є кирилиця чи спецсимволи
    images_str = json.dumps(data_dict.pop('lot_images', []), ensure_ascii=False)
    damages_str = json.dumps(data_dict.pop('lot_damages', []), ensure_ascii=False)
    announcements_str = json.dumps(data_dict.pop('lot_announcements', []), ensure_ascii=False)

    # Створюємо об'єкт для бази даних, розпакувавши словник (**data_dict)
    new_raw_lot = RawAuctionLot(
        **data_dict,
        lot_images=images_str,
        lot_damages=damages_str,
        lot_announcements=announcements_str
    )

    # Додаємо в сесію і зберігаємо
    db.add(new_raw_lot)
    await db.commit()