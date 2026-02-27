import re
import json
from typing import Dict, Any

# Імпортуємо твою фінальну Pydantic-модель (шлях залежить від того, де ти її створив)
from schemas.common_schema import AuctionLotParsedData

# Якщо parse_odometer лежить в іншому файлі (наприклад, utils.py), імпортуємо її:
# from utils.helpers import parse_odometer

# Допоміжна функція для очищення грошових значень, яка була в твоєму старому коді
def clean_money(val_str):
    if not val_str:
        return 0
    cleaned = re.sub(r'[^\d]', '', str(val_str).split('.')[0])
    return int(cleaned) if cleaned else 0

def parse_odometer(odo_str):
    """
    Вхід: '61,321 mi (Actual)'
    Вихід: (61321, 'mi', 'Actual')
    """
    if not odo_str:
        return None, None, None

    val = None
    unit = 'mi' # default
    status = None

    # Витягуємо число
    val_match = re.search(r'([\d,]+)', odo_str)
    if val_match:
        val = int(val_match.group(1).replace(',', ''))

    # Витягуємо статус в дужках
    status_match = re.search(r'\((.*?)\)', odo_str)
    if status_match:
        status = status_match.group(1)

    # Витягуємо unit (mi або km)
    if 'km' in odo_str.lower():
        unit = 'km'

    return val, unit, status

def parse_iaai_to_pydantic(lot_obj: Dict[str, Any]) -> AuctionLotParsedData:
    """
    Функція для парсингу сирого JSON об'єкта IAAI
    та конвертації його у валідовану Pydantic-модель.
    """
    # 1. Безпечно дістаємо вкладені словники
    specs = lot_obj.get('specs') or {}
    prod_details = lot_obj.get('ProductDetailsVM') or {}

    # Витягуємо обидва словники, бо в IAAI дані розкидані
    real_inventory = prod_details.get('inventory') or {}
    inventory_view = prod_details.get('inventoryView') or {}
    attributes = inventory_view.get('attributes') or {}

    # Залишаємо inventory для сумісності з іншим кодом
    inventory = real_inventory if real_inventory else inventory_view

    # ==========================================
    # Допоміжна логіка (Пробіг, Колір, Двигун)
    # ==========================================

    # -- Пробіг --
    odometer_raw = lot_obj.get('odometer') # <--- ЦЕЙ РЯДОК БУВ ПРОПУЩЕНИЙ

    # Крок 1: Шукаємо у масиві vehicleInformation (там, де key = Odometer)
    if not odometer_raw:
        veh_info_list = inventory_view.get('vehicleInformation', {}).get('$values', [])
        for item in veh_info_list:
            if item.get('key') == 'Odometer':
                odometer_raw = item.get('value')  # Знайде "336,603 mi (Actual)"
                break

    # Резервний крок 2: Шукаємо по старих полях attributes або inventory
    if not odometer_raw:
        val = real_inventory.get('odoValue') or attributes.get('ODOValue')
        unit = real_inventory.get('odoUoM') or attributes.get('ODOUoM') or ''
        brand = real_inventory.get('odoBrand') or attributes.get('ODOBrand') or ''

        # Записуємо тільки якщо реально є цифри
        if val:
            odometer_raw = f"{val} {unit} ({brand})".strip()

    # Запобіжник: якщо після всіх пошуків нічого немає
    if odometer_raw and odometer_raw.strip() == "()":
        odometer_raw = None

    # Парсимо знайдений рядок (якщо він є)
    if odometer_raw:
        odo_val, odo_unit, odo_status = parse_odometer(odometer_raw)
    else:
        odo_val, odo_unit, odo_status = None, None, None

    odometer_miles = None
    odometer_km = None

    if odo_val is not None:
        try:
            odo_val_float = float(odo_val)
            if odo_unit == 'mi':
                odometer_miles = int(odo_val_float)
                odometer_km = int(odo_val_float * 1.609344)
            elif odo_unit == 'km':
                odometer_km = int(odo_val_float)
                odometer_miles = int(odo_val_float / 1.609344)
        except ValueError:
            pass # Якщо прийшов якийсь текст замість цифр

    if not odo_status and odo_unit:
        odo_status = str(odo_unit)

    # -- Колір (ОНОВЛЕНО: додано розбивку на exterior та interior) --
    ext_int = inventory.get('exterior_interior') or specs.get('exterior_interior')
    color_name = None
    exterior_color_val = None
    interior_color_val = None
    if ext_int:
        parts = ext_int.split('/')
        if len(parts) > 0:
            color_name = parts[0].strip()
            exterior_color_val = parts[0].strip()
        if len(parts) > 1:
            interior_color_val = parts[1].strip()

    # -- Циліндри --
    cylinders_raw = specs.get('cylinders')
    cylinders_val = None
    if cylinders_raw:
        cyl_clean = cylinders_raw.replace('Cylinders', '').strip()
        if cyl_clean.isdigit():
            cylinders_val = str(cyl_clean)

    # -- Літраж --
    disp_raw = attributes.get('DisplLiters')
    displacement_val = disp_raw.replace('L', '').strip() if disp_raw else None

    # -- Двигун та Аспірація --
    engine_val = lot_obj.get('engine') or inventory.get('engineSize') or attributes.get('EngineSize', '').strip() or attributes.get('EngineInformation')
    aspiration_val = None
    if engine_val:
        eng_lower = engine_val.lower()
        if 'turbo' in eng_lower:
            aspiration_val = 'Turbo'
        elif 'supercharged' in eng_lower:
            aspiration_val = 'Supercharged'

    # -- Пошкодження --
    primary_damage = lot_obj.get('primary_damage') or inventory.get('primaryDamageDesc') or attributes.get('PrimaryDamageDesc')
    secondary_damage = lot_obj.get('secondary_damage') or inventory.get('secondaryDamageDesc') or attributes.get('SecondaryDamageDesc')
    lot_damages_list = [d for d in [primary_damage, secondary_damage] if d]

    # -- Оголошення (Notes) --
    notes_raw = specs.get('notes')
    lot_announcements_list = [notes_raw.strip()] if notes_raw else []

    # -- Рік --
    year_raw = lot_obj.get('year') or inventory.get('year') or attributes.get('Year')
    year_val = None
    try:
        if year_raw: year_val = int(year_raw)
    except ValueError:
        pass

    # ==========================================
    # НОВІ ПОЛЯ: Витягування даних для оновленої "Сніжинки"
    # ==========================================

    # 1. Ціни та Ставки
    buy_now_raw = specs.get('buy_now_price') or prod_details.get('auctionInformation', {}).get('biddingInformation', {}).get('buyNowPrice')
    buy_now_bid_val = clean_money(buy_now_raw)

    current_bid_raw = prod_details.get('auctionInformation', {}).get('prebidInformation', {}).get('highBidAmount')
    current_bid_val = clean_money(current_bid_raw)

    acv_raw = specs.get('actual_cash_value') or attributes.get('ActualCashValue')
    estimated_real_price_val = clean_money(acv_raw)

    # 2. Тип транспорту
    vehicle_type_val = lot_obj.get('type') or inventory.get('inventoryType') or attributes.get('InventoryType')

    # 3. Країна аукціону (Шукаємо Tenant, наприклад "US")
    tenant = attributes.get('Tenant')
    auction_country_val = "USA" if tenant == "US" else tenant

    # 4. Дата продажу
    sale_date_time_val = attributes.get('AuctionDateTime') or specs.get('auction_date_and_time')

    # 5. Страхова компанія (Селлер)
    ensurance_name_val = specs.get('seller') or attributes.get('ProviderName')

    # 6. Raw JSON
    raw_json_val = json.dumps(lot_obj, ensure_ascii=False)


    # ==========================================
    # 2. Формування Pydantic Моделі (Строго за порядком)
    # ==========================================
    lot_number_val = lot_obj.get('stock_id') or inventory.get('stockNumber') or attributes.get('StockNumber')

    return AuctionLotParsedData(
        listing_id=None,
        lot_number=str(lot_number_val) if lot_number_val else "UNKNOWN",
        lot_url=f"https://www.iaai.com/VehicleDetail/{lot_number_val}" if lot_number_val else None,
        odometer_km=odometer_km,
        odometer_miles=odometer_miles,

        # --- НОВІ ПОЛЯ (Ціни) ---
        buy_now_bid=buy_now_bid_val,
        current_bid=current_bid_val,
        estimated_real_price=estimated_real_price_val,

        vin=lot_obj.get('vin') or inventory.get('vin') or attributes.get('VINMask', '').split(' ')[0],
        year=year_val,
        carfax_available=0,

        # --- НОВЕ ПОЛЕ (Тип авто) ---
        vehicle_type=vehicle_type_val,

        # --- НОВІ ПОЛЯ (Кольори детально) ---
        exterior_color=exterior_color_val,
        interior_color=interior_color_val,

        make_name=attributes.get('Make'),
        model_name=lot_obj.get('model') or inventory.get('model') or attributes.get('Model'),
        trim_name=specs.get('series') or attributes.get('Series'),
        body_type=attributes.get('BodyStyleName') or specs.get('body_style'),
        engine_raw=engine_val,
        aspiration=aspiration_val,
        cylinders=cylinders_val,
        displacement=displacement_val,
        fuel_type=specs.get('fuel_type') or attributes.get('fuelTypeDesc') or attributes.get('FuelTypeCode'),
        transmission_type=lot_obj.get('transmission') or inventory.get('transmission') or attributes.get('Transmission'),
        drive_type=attributes.get('DriveLineTypeDesc') or specs.get('drive_line_type'),
        auction_name="IAAI",
        auction_location=specs.get('branch') or inventory.get('branchName') or attributes.get('BranchName'),

        # --- НОВІ ПОЛЯ (Аукціон, Страхова, Дата) ---
        auction_country=auction_country_val,
        sale_date_time=sale_date_time_val,
        ensurance_name=ensurance_name_val,

        doc_status=specs.get('title_sale_doc') or inventory.get('title') or attributes.get('TitleSaleDoc'),
        color_name=color_name,
        odometer_status=odo_status,
        lot_status=specs.get('auction_date_and_time') or attributes.get('AuctionDateTime'),
        highlight_desc=specs.get('start_code') or inventory.get('startsDesc') or attributes.get('StartsDesc'),

        # --- НОВЕ ПОЛЕ (Сирий JSON) ---
        raw_json=raw_json_val,

        lot_images=lot_obj.get('images', []),
        lot_damages=lot_damages_list,
        lot_announcements=lot_announcements_list
    )