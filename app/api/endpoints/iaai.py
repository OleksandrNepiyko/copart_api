from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from schemas.iaai_schema import IAAIRawPayload
from services.parsers_logic.iaai_parser import parse_iaai_to_pydantic
from services import lot_saver

# Імпорт функції, яка буде виконувати кроки 2-8 у фоні
# from services.background_worker import process_lot_pipeline

router = APIRouter()

@router.post("/lots")
async def receive_iaai_lots(
    payload: IAAIRawPayload,
    background_tasks: BackgroundTasks, # Додаємо підтримку фонових задач
    db: AsyncSession = Depends(get_db)
):
    try:
        # 1. Перетворюємо сирий JSON у твою універсальну Pydantic-модель
        parsed_data = parse_iaai_to_pydantic(payload.lot_data)

        #for test:
        await lot_saver.save_raw_lot(parsed_data, db)

        # 2. Зберігаємо в "Сиру таблицю цього аукціону" (Крок 1 на схемі)
        # Тут має бути твій SQLAlchemy код для вставки parsed_data в БД
        # db.add(RawIAAIModel(**parsed_data.model_dump()))
        # await db.commit()

        # 3. Відправляємо лот у фонову обробку (Кроки 2-8: VIN, картинки, AutoData)
        # background_tasks.add_task(process_lot_pipeline, parsed_data, db)

        return {"status": "success", "message": f"Lot {parsed_data.lot_number} received and queued for processing."}

    except Exception as e:
        # Якщо парсер прислав такий кривий JSON, що твоя функція впала
        raise HTTPException(status_code=400, detail=f"Error parsing IAAI data: {str(e)}")