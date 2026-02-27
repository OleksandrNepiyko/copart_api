from fastapi import APIRouter

# Імпортуємо роутери з наших файлів ендпоінтів
# from .endpoints import copart, iaai, manheim
from .endpoints import iaai

# Створюємо головний роутер для всього API
api_router = APIRouter()

# Підключаємо роутери аукціонів до головного
# prefix додасть відповідний шлях до всіх ендпоінтів у файлі (напр., /api/v1/copart/...)
# tags допоможуть красиво згрупувати їх у документації Swagger (http://localhost:8000/docs)
# api_router.include_router(copart.router, prefix="/copart", tags=["Copart Parser"])
api_router.include_router(iaai.router, prefix="/iaai", tags=["IAAI Parser"])
# api_router.include_router(manheim.router, prefix="/manheim", tags=["Manheim Parser"])