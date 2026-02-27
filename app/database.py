from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

# DATABASE_URL = "mysql+aiomysql://auto:0qNjdftat729AGQt@10.30.0.113:3308/manheim"
DATABASE_URL = "mysql+aiomysql://root:root@10.30.0.100:3310/iaai_lots"

# Створюємо єдиний engine на всю програму.
# pool_size - скільки з'єднань тримати відкритими постійно.
# max_overflow - скільки додаткових з'єднань можна відкрити при піковому навантаженні.
engine = create_async_engine(
    DATABASE_URL,
    echo=False, # Постав True, якщо хочеш бачити SQL-запити в консолі під час дебагу
    pool_recycle=3600,
    pool_size=20,
    max_overflow=10
)

# Фабрика для створення нових сесій БД
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False
)

# Базовий клас для всіх твоїх моделей таблиць (Сира, Проміжна, Фінальна)
class Base(DeclarativeBase):
    pass

# Залежність (Dependency) для FastAPI, яка видаватиме сесію БД кожному запиту
async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()