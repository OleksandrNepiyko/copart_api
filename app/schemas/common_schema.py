from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime

class AuctionLotParsedData(BaseModel):
    # ==========================================
    # 1. Ідентифікатори та базові дані
    # ==========================================
    listing_id: Optional[int] = 0           # int (default 0)
    lot_number: Optional[str] = None        # varchar
    lot_url: Optional[str] = None           # varchar
    vin: str                                # varchar (NO NULL - обов'язкове поле!)
    parsed_at: datetime = Field(default_factory=datetime.now) # datetime (буде ставити поточний час)
    carfax_available: Optional[int] = 0     # tinyint (default 0)

    # ==========================================
    # 2. Довідники (Текст, який піде в інші таблиці або залишиться тут)
    # ==========================================
    vehicle_type: Optional[str] = None      # varchar (НОВЕ ПОЛЕ)
    make_name: Optional[str] = None         # varchar
    model_name: Optional[str] = None        # varchar
    trim_name: Optional[str] = None         # varchar
    body_type: Optional[str] = None         # varchar
    color_name: Optional[str] = None        # varchar (Загальний колір)
    exterior_color: Optional[str] = None    # varchar (НОВЕ ПОЛЕ)
    interior_color: Optional[str] = None    # varchar (НОВЕ ПОЛЕ)

    # ==========================================
    # 3. Двигун та пальне
    # ==========================================
    engine_raw: Optional[str] = None        # varchar
    aspiration: Optional[str] = None        # varchar
    cylinders: Optional[str] = None         # varchar (у базі varchar, тому str)
    displacement: Optional[str] = None      # varchar
    fuel_type: Optional[str] = None         # varchar
    transmission_type: Optional[str] = None # varchar
    drive_type: Optional[str] = None        # varchar

    # ==========================================
    # 4. Стан, пробіг, локація та АУКЦІОН
    # ==========================================
    year: Optional[int] = None              # int
    odometer_km: Optional[int] = None       # int
    odometer_miles: Optional[int] = None    # int
    odometer_status: Optional[str] = None   # varchar
    auction_name: Optional[str] = None      # varchar
    auction_location: Optional[str] = None  # varchar
    auction_country: Optional[str] = None   # varchar (НОВЕ ПОЛЕ)
    sale_date_time: Optional[str] = None    # varchar (НОВЕ ПОЛЕ - дата у форматі рядка з JSON)
    ensurance_name: Optional[str] = None    # varchar (НОВЕ ПОЛЕ - страхова/селлер)
    doc_status: Optional[str] = None        # varchar
    lot_status: Optional[str] = None        # varchar
    highlight_desc: Optional[str] = None    # text

    # ==========================================
    # 5. Ціни та фінанси (НОВИЙ БЛОК)
    # ==========================================
    buy_now_bid: Optional[int] = 0          # int (default 0)
    current_bid: Optional[int] = 0          # int (default 0)
    estimated_real_price: Optional[int] = 0 # int (default 0)

    # ==========================================
    # 6. Списки та сирі дані (JSON масиви / mediumtext / longtext)
    # ==========================================
    raw_json: Optional[str] = None                             # longtext (НОВЕ ПОЛЕ)
    # В API ми приймаємо їх як списки для зручності,
    # а перед записом в БД (де mediumtext) перетворимо в JSON-рядок через json.dumps()
    lot_images: List[str] = Field(default_factory=list)        # mediumtext
    lot_damages: List[str] = Field(default_factory=list)       # mediumtext
    lot_announcements: List[str] = Field(default_factory=list) # mediumtext