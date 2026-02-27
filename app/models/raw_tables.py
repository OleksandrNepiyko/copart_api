from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.dialects.mysql import TINYINT, MEDIUMTEXT
from database import Base # Твій імпорт Base

class RawAuctionLot(Base):
    __tablename__ = "test_flat_listings" # Зміни на реальну назву своєї таблиці

    # 1. Ідентифікатори та базові дані
    listing_id = Column(Integer, primary_key=True, autoincrement=True) # Зробив автоінкремент, щоб БД сама давала ID
    lot_number = Column(String(255), nullable=True)
    lot_url = Column(String(255), nullable=True)
    odometer_km = Column(Integer, nullable=True)
    odometer_miles = Column(Integer, nullable=True)
    parsed_at = Column(DateTime, nullable=True)
    vin = Column(String(50), nullable=False) # Обов'язкове поле
    year = Column(Integer, nullable=True)
    carfax_available = Column(TINYINT, default=0)

    # 2. Довідники
    make_name = Column(String(255), nullable=True)
    model_name = Column(String(255), nullable=True)
    trim_name = Column(String(255), nullable=True)
    body_type = Column(String(255), nullable=True)
    color_name = Column(String(255), nullable=True)

    # 3. Двигун та пальне
    engine_raw = Column(String(255), nullable=True)
    aspiration = Column(String(255), nullable=True)
    cylinders = Column(String(50), nullable=True) # Ти писав varchar
    displacement = Column(String(50), nullable=True) # Ти писав varchar
    fuel_type = Column(String(255), nullable=True)
    transmission_type = Column(String(255), nullable=True)
    drive_type = Column(String(255), nullable=True)

    # 4. Стан, пробіг та локація
    auction_name = Column(String(255), nullable=True)
    auction_location = Column(String(255), nullable=True)
    doc_status = Column(String(255), nullable=True)
    odometer_status = Column(String(255), nullable=True)
    lot_status = Column(String(255), nullable=True)
    highlight_desc = Column(Text, nullable=True) # text

    # 5. Списки (серіалізовані в JSON)
    lot_images = Column(MEDIUMTEXT, nullable=True)
    lot_damages = Column(MEDIUMTEXT, nullable=True)
    lot_announcements = Column(MEDIUMTEXT, nullable=True)
    vehicle_type = Column(String(255), nullable=True)
    exterior_color = Column(String(255), nullable=True)
    interior_color = Column(String(255), nullable=True)

    auction_country = Column(String(255), nullable=True)
    sale_date_time = Column(String(255), nullable=True)
    ensurance_name = Column(String(255), nullable=True)

    buy_now_bid = Column(Integer, default=0)
    current_bid = Column(Integer, default=0)
    estimated_real_price = Column(Integer, default=0)

    raw_json = Column(Text, nullable=True) # Text підходить для JSON