import json
import re
import os  # <--- НОВЕ: для перевірки файлів
from typing import Dict, Any
from sqlalchemy import create_engine, text

# ==========================================
# 1. КОНФІГУРАЦІЯ БАЗИ ТА КЛАСТЕРА
# ==========================================
SOURCE_DB_URL = 'mysql+pymysql://root:root@10.30.0.100:3310/iaai_lots'
TARGET_DB_URL = 'mysql+pymysql://auto:0qNjdftat729AGQt@10.30.0.113:3308/manheim'

SOURCE_TABLE_NAME = 'iaai_lots_clear'
COL_JSON_SOURCE = 'json_of_lot'
COL_IMAGES = 'images'

# Налаштування для розподілу між 3 ноутами:
START_ID = 300000
END_ID = 10000000  # На другому ноуті зміни на 200000, на віртуалці на 300000

BATCH_SIZE = 500
TEST_LIMIT = 5   # ЗАКОМЕНТУЙ ЦЕЙ РЯДОК ДЛЯ ПОВНОГО ЗАПУСКУ: # TEST_LIMIT = None

# <--- НОВЕ: Файл прогресу (унікальний для кожного воркера)
PROGRESS_FILE = f"progress_{START_ID}.txt"

source_engine = create_engine(SOURCE_DB_URL, pool_size=5)
target_engine = create_engine(TARGET_DB_URL, pool_size=10, max_overflow=20)

# ==========================================
# 2. ЛОГІКА ПАРСИНГУ
# ==========================================
from app.schemas.common_schema import AuctionLotParsedData

def clean_money(val_str):
    if not val_str:
        return 0
    cleaned = re.sub(r'[^\d]', '', str(val_str).split('.')[0])
    return int(cleaned) if cleaned else 0

def parse_odometer(odo_str):
    if not odo_str: return None, None, None
    val, unit, status = None, 'mi', None
    val_match = re.search(r'([\d,]+)', odo_str)
    if val_match: val = int(val_match.group(1).replace(',', ''))
    status_match = re.search(r'\((.*?)\)', odo_str)
    if status_match: status = status_match.group(1)
    if 'km' in odo_str.lower(): unit = 'km'
    return val, unit, status

def parse_iaai_to_pydantic(lot_obj: Dict[str, Any]) -> AuctionLotParsedData:
    specs = lot_obj.get('specs') or {}
    prod_details = lot_obj.get('ProductDetailsVM') or {}
    real_inventory = prod_details.get('inventory') or {}
    inventory_view = prod_details.get('inventoryView') or {}
    attributes = inventory_view.get('attributes') or {}
    inventory = real_inventory if real_inventory else inventory_view

    odometer_raw = lot_obj.get('odometer')
    if not odometer_raw:
        for item in inventory_view.get('vehicleInformation', {}).get('$values', []):
            if item.get('key') == 'Odometer':
                odometer_raw = item.get('value')
                break
    if not odometer_raw:
        val = real_inventory.get('odoValue') or attributes.get('ODOValue')
        unit = real_inventory.get('odoUoM') or attributes.get('ODOUoM') or ''
        brand = real_inventory.get('odoBrand') or attributes.get('ODOBrand') or ''
        if val: odometer_raw = f"{val} {unit} ({brand})".strip()

    if odometer_raw and odometer_raw.strip() == "()": odometer_raw = None
    if odometer_raw:
        odo_val, odo_unit, odo_status = parse_odometer(odometer_raw)
    else:
        odo_val, odo_unit, odo_status = None, None, None

    odometer_miles, odometer_km = None, None
    if odo_val is not None:
        try:
            odo_val_float = float(odo_val)
            if odo_unit == 'mi':
                odometer_miles = int(odo_val_float)
                odometer_km = int(odo_val_float * 1.609344)
            elif odo_unit == 'km':
                odometer_km = int(odo_val_float)
                odometer_miles = int(odo_val_float / 1.609344)
        except ValueError: pass

    if not odo_status and odo_unit: odo_status = str(odo_unit)

    ext_int = inventory.get('exterior_interior') or specs.get('exterior_interior')
    color_name, exterior_color_val, interior_color_val = None, None, None
    if ext_int:
        parts = ext_int.split('/')
        if len(parts) > 0:
            color_name = parts[0].strip()
            exterior_color_val = parts[0].strip()
        if len(parts) > 1: interior_color_val = parts[1].strip()

    cylinders_raw = specs.get('cylinders')
    cylinders_val = None
    if cylinders_raw:
        cyl_clean = cylinders_raw.replace('Cylinders', '').strip()
        if cyl_clean.isdigit(): cylinders_val = str(cyl_clean)

    disp_raw = attributes.get('DisplLiters')
    displacement_val = disp_raw.replace('L', '').strip() if disp_raw else None

    engine_val = lot_obj.get('engine') or inventory.get('engineSize') or attributes.get('EngineSize', '').strip() or attributes.get('EngineInformation')
    aspiration_val = None
    if engine_val:
        eng_lower = engine_val.lower()
        if 'turbo' in eng_lower: aspiration_val = 'Turbo'
        elif 'supercharged' in eng_lower: aspiration_val = 'Supercharged'

    primary_damage = lot_obj.get('primary_damage') or inventory.get('primaryDamageDesc') or attributes.get('PrimaryDamageDesc')
    secondary_damage = lot_obj.get('secondary_damage') or inventory.get('secondaryDamageDesc') or attributes.get('SecondaryDamageDesc')
    lot_damages_list = [d for d in [primary_damage, secondary_damage] if d]

    notes_raw = specs.get('notes')
    lot_announcements_list = [notes_raw.strip()] if notes_raw else []

    year_raw = lot_obj.get('year') or inventory.get('year') or attributes.get('Year')
    year_val = None
    try:
        if year_raw: year_val = int(year_raw)
    except ValueError: pass

    buy_now_raw = specs.get('buy_now_price') or prod_details.get('auctionInformation', {}).get('biddingInformation', {}).get('buyNowPrice')
    buy_now_bid_val = clean_money(buy_now_raw)
    current_bid_raw = prod_details.get('auctionInformation', {}).get('prebidInformation', {}).get('highBidAmount')
    current_bid_val = clean_money(current_bid_raw)
    acv_raw = specs.get('actual_cash_value') or attributes.get('ActualCashValue')
    estimated_real_price_val = clean_money(acv_raw)

    vehicle_type_val = lot_obj.get('type') or inventory.get('inventoryType') or attributes.get('InventoryType')
    tenant = attributes.get('Tenant')
    auction_country_val = "USA" if tenant == "US" else tenant
    sale_date_time_val = attributes.get('AuctionDateTime') or specs.get('auction_date_and_time')
    ensurance_name_val = specs.get('seller') or attributes.get('ProviderName')
    raw_json_val = json.dumps(lot_obj, ensure_ascii=False)

    link_number_val = attributes.get('Id') or f"{attributes.get('SalvageId')}~{attributes.get('Tenant')}" or f"{attributes.get('SalvageId')}~{attributes.get('StorageLocationBranchLink')}" or lot_obj.get('stock_id') or attributes.get('StockNumber')
    lot_number_val = lot_obj.get('stock_id')
    return AuctionLotParsedData(
        listing_id=None,
        lot_number=str(lot_number_val) if link_number_val else "UNKNOWN",
        lot_url=f"https://www.iaai.com/VehicleDetail/{link_number_val}" if link_number_val else None,
        odometer_km=odometer_km, odometer_miles=odometer_miles,
        buy_now_bid=buy_now_bid_val, current_bid=current_bid_val, estimated_real_price=estimated_real_price_val,
        vin=lot_obj.get('vin') or inventory.get('vin') or attributes.get('VINMask', '').split(' ')[0],
        year=year_val, carfax_available=0, vehicle_type=vehicle_type_val,
        exterior_color=exterior_color_val, interior_color=interior_color_val,
        make_name=attributes.get('Make'), model_name=lot_obj.get('model') or inventory.get('model') or attributes.get('Model'),
        trim_name=specs.get('series') or attributes.get('Series'), body_type=attributes.get('BodyStyleName') or specs.get('body_style'),
        engine_raw=engine_val, aspiration=aspiration_val, cylinders=cylinders_val, displacement=displacement_val,
        fuel_type=specs.get('fuel_type') or attributes.get('fuelTypeDesc') or attributes.get('FuelTypeCode'),
        transmission_type=lot_obj.get('transmission') or inventory.get('transmission') or attributes.get('Transmission'),
        drive_type=attributes.get('DriveLineTypeDesc') or specs.get('drive_line_type'),
        auction_name="IAAI", auction_location=specs.get('branch') or inventory.get('branchName') or attributes.get('BranchName'),
        auction_country=auction_country_val, sale_date_time=sale_date_time_val, ensurance_name=ensurance_name_val,
        doc_status=specs.get('title_sale_doc') or inventory.get('title') or attributes.get('TitleSaleDoc'),
        color_name=color_name, odometer_status=odo_status,
        lot_status=inventory_view.get('prebidInformation').get('vehicleStatus'),
        highlight_desc=specs.get('start_code') or inventory.get('startsDesc') or attributes.get('StartsDesc'),
        raw_json=raw_json_val,
        lot_images=lot_obj.get('images', []),
        lot_damages=lot_damages_list,
        lot_announcements=lot_announcements_list
    )


# ==========================================
# 3. КЕШУВАННЯ ТА ЗАПИС В БД (СНІЖИНКА)
# ==========================================
class DBCache:
    def __init__(self, conn):
        self.conn = conn
        self.cache = {}

    def get_id(self, table: str, col: str, value: Any) -> int:
        if not value: return None
        val_str = str(value).strip()
        if not val_str: return None

        cache_key = f"{table}_{col}_{val_str}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        self.conn.execute(text(f"INSERT IGNORE INTO {table} ({col}) VALUES (:val)"), {"val": val_str})
        res = self.conn.execute(text(f"SELECT id FROM {table} WHERE {col} = :val LIMIT 1"), {"val": val_str}).scalar()

        self.cache[cache_key] = res
        return res

    def get_ext_int_color_id(self, ext: str, int_col: str) -> int:
        if not ext and not int_col: return None
        ext = str(ext).strip() if ext else ""
        int_col = str(int_col).strip() if int_col else ""

        cache_key = f"ext_int_{ext}_{int_col}"
        if cache_key in self.cache: return self.cache[cache_key]

        self.conn.execute(
            text("INSERT IGNORE INTO ref_ext_int_colors (ext_color, int_color) VALUES (:e, :i)"),
            {"e": ext, "i": int_col}
        )
        res = self.conn.execute(
            text("SELECT id FROM ref_ext_int_colors WHERE ext_color = :e AND int_color = :i LIMIT 1"),
            {"e": ext, "i": int_col}
        ).scalar()
        self.cache[cache_key] = res
        return res

    def get_auction_id(self, name: str, loc: str, country: str) -> int:
        if not name: return None
        loc = str(loc).strip() if loc else ""
        country = str(country).strip() if country else ""

        cache_key = f"auc_{name}_{loc}_{country}"
        if cache_key in self.cache: return self.cache[cache_key]

        self.conn.execute(
            text("INSERT IGNORE INTO dim_auctions (name, location, country) VALUES (:n, :l, :c)"),
            {"n": name, "l": loc, "c": country}
        )
        res = self.conn.execute(
            text("SELECT id FROM dim_auctions WHERE name = :n AND location = :l AND country = :c LIMIT 1"),
            {"n": name, "l": loc, "c": country}
        ).scalar()
        self.cache[cache_key] = res
        return res

    def get_drivetrain_id(self, engine: str, asp_id, cyl_id, disp_id, fuel_id, trans_id, drive_id) -> int:
        if not engine: return None
        cache_key = f"dt_{engine}_{asp_id}_{cyl_id}_{disp_id}_{fuel_id}_{trans_id}_{drive_id}"
        if cache_key in self.cache: return self.cache[cache_key]

        self.conn.execute(
            text("""INSERT IGNORE INTO dim_drivetrains
                    (engine_raw, aspiration_id, cylinders_id, displacement_id, fuel_id, transmission_id, drive_id)
                    VALUES (:e, :a, :c, :d, :f, :t, :dr)"""),
            {"e": engine, "a": asp_id, "c": cyl_id, "d": disp_id, "f": fuel_id, "t": trans_id, "dr": drive_id}
        )
        res = self.conn.execute(
            text("SELECT id FROM dim_drivetrains WHERE engine_raw = :e LIMIT 1"),
            {"e": engine}
        ).scalar()
        self.cache[cache_key] = res
        return res

def run_migration():
    processed_count = 0
    last_id = START_ID - 1

    # <--- НОВЕ: Читаємо ID з файлу прогресу перед стартом ---
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, 'r') as f:
                content = f.read().strip()
                if content:
                    saved_id = int(content)
                    if saved_id >= START_ID:
                        last_id = saved_id
                        print(f"🔄 Відновлено роботу з файлу. Продовжуємо з ID: {last_id}")
        except Exception as e:
            print(f"⚠️ Не вдалося прочитати файл прогресу: {e}")
    # ---------------------------------------------------------

    with source_engine.connect() as s_conn:
        while True:
            # Перевірка ліміту для тесту
            if TEST_LIMIT is not None and processed_count >= TEST_LIMIT:
                print(f"🛑 Досягнуто ліміт тестування: {TEST_LIMIT} лотів.")
                break

            query = text(f"SELECT id, {COL_JSON_SOURCE}, {COL_IMAGES} FROM {SOURCE_TABLE_NAME} WHERE id > :lid AND id <= :end_id ORDER BY id ASC LIMIT :b")
            rows = s_conn.execute(query, {"lid": last_id, "end_id": END_ID, "b": BATCH_SIZE}).fetchall()

            if not rows:
                print("✅ Дані закінчились або досягнуто END_ID.")
                break

            current_batch_last_id = rows[-1][0] # Зберігаємо ID останнього лота в цьому батчі
            print(f"Опрацювання батчу: ID {rows[0][0]} - {current_batch_last_id} (Записів: {len(rows)})")

            # Обробляємо і записуємо в Сніжинку
            with target_engine.begin() as t_conn:
                cache = DBCache(t_conn)

                for row in rows:
                    if TEST_LIMIT is not None and processed_count >= TEST_LIMIT: break

                    try:
                        raw_json_str = row[1]
                        raw_images_str = row[2]

                        raw_dict = json.loads(raw_json_str) if isinstance(raw_json_str, str) else raw_json_str

                        images_list = []
                        if raw_images_str:
                            if isinstance(raw_images_str, str):
                                try:
                                    images_list = json.loads(raw_images_str)
                                except Exception:
                                    pass
                            elif isinstance(raw_images_str, list):
                                images_list = raw_images_str

                        if isinstance(raw_dict, dict):
                            raw_dict['images'] = images_list

                        p = parse_iaai_to_pydantic(raw_dict)

                        if not p.vin or str(p.vin).strip() == "":
							p.vin = None

                        # 1. Заповнюємо довідники і отримуємо ID
                        make_id = cache.get_id('ref_makes', 'name', p.make_name)
                        model_id = cache.get_id('ref_models', 'name', p.model_name)
                        trim_id = cache.get_id('ref_trims', 'name', p.trim_name)
                        body_id = cache.get_id('ref_body_types', 'name', p.body_type)
                        vtype_id = cache.get_id('dim_vehicle_types', 'name', p.vehicle_type)
                        year_id = cache.get_id('ref_years', 'name', p.year)

                        ext_int_id = cache.get_ext_int_color_id(p.exterior_color, p.interior_color)

                        asp_id = cache.get_id('ref_aspirations', 'name', p.aspiration)
                        cyl_id = cache.get_id('ref_cylinders', 'name', p.cylinders)
                        disp_id = cache.get_id('ref_displacements', 'name', p.displacement)
                        fuel_id = cache.get_id('ref_fuels', 'name', p.fuel_type)
                        trans_id = cache.get_id('ref_transmissions', 'name', p.transmission_type)
                        drive_id = cache.get_id('ref_drives', 'name', p.drive_type)

                        dt_id = cache.get_drivetrain_id(p.engine_raw, asp_id, cyl_id, disp_id, fuel_id, trans_id, drive_id)

                        # 2. Записуємо dim_vehicles (UPSERT)
                        t_conn.execute(text("""
                            INSERT INTO dim_vehicles
                            (vin, make_id, model_id, trim_id, body_type_id, drivetrain_id, ext_int_color_id, vehicle_type_id, year_id, carfax_available)
                            VALUES (:v, :mk, :md, :tr, :bd, :dt, :eic, :vt, :yr, :cfx)
                            ON DUPLICATE KEY UPDATE
                                make_id=VALUES(make_id), model_id=VALUES(model_id), year_id=VALUES(year_id)
                        """), {
                            "v": p.vin, "mk": make_id, "md": model_id, "tr": trim_id, "bd": body_id,
                            "dt": dt_id, "eic": ext_int_id, "vt": vtype_id, "yr": year_id, "cfx": p.carfax_available
                        })

                        vehicle_id = t_conn.execute(text("SELECT id FROM dim_vehicles WHERE vin = :v LIMIT 1"), {"v": p.vin}).scalar()

                        # 3. Довідники для fact_listings
                        auc_id = cache.get_auction_id(p.auction_name, p.auction_location, p.auction_country)
                        date_id = cache.get_id('ref_dates', 'sale_date_time', p.sale_date_time)
                        ens_id = cache.get_id('ref_ensurances', 'name', p.ensurance_name)
                        doc_id = cache.get_id('dim_doc_statuses', 'status_name', p.doc_status)
                        col_id = cache.get_id('dim_colors', 'name', p.color_name)
                        odo_id = cache.get_id('dim_odometer_statuses', 'status_name', p.odometer_status)
                        lot_stat_id = cache.get_id('dim_lot_statuses', 'status_name', p.lot_status)
                        high_id = cache.get_id('dim_highlights', 'description', p.highlight_desc)

                        # 4. Записуємо fact_listings (UPSERT)
                        t_conn.execute(text("""
                            INSERT INTO fact_listings
                            (vehicle_id, auction_id, doc_status_id, color_id, odometer_status_id, lot_status_id, highlights_id,
                             sale_date_time_id, ensurance_id, lot_number, lot_url, odometer_km, odometer_miles,
                             buy_now_bid, current_bid, estimated_real_price, raw_json)
                            VALUES (:vid, :aid, :doc, :col, :odo, :ls, :high, :sdt, :ens, :ln, :url, :okm, :omi, :bnb, :cb, :erp, :rj)
                            ON DUPLICATE KEY UPDATE
                                odometer_km=VALUES(odometer_km), current_bid=VALUES(current_bid), raw_json=VALUES(raw_json)
                        """), {
                            "vid": vehicle_id, "aid": auc_id, "doc": doc_id, "col": col_id, "odo": odo_id, "ls": lot_stat_id,
                            "high": high_id, "sdt": date_id, "ens": ens_id, "ln": p.lot_number, "url": p.lot_url,
                            "okm": p.odometer_km, "omi": p.odometer_miles, "bnb": p.buy_now_bid, "cb": p.current_bid,
                            "erp": p.estimated_real_price, "rj": p.raw_json
                        })

                        listing_id = t_conn.execute(text("SELECT id FROM fact_listings WHERE lot_number = :ln AND auction_id = :aid LIMIT 1"),
                                                    {"ln": p.lot_number, "aid": auc_id}).scalar()

                        if listing_id:
                            # 5. Очищаємо старі списки
                            t_conn.execute(text("DELETE FROM lot_images WHERE listing_id = :lid"), {"lid": listing_id})
                            t_conn.execute(text("DELETE FROM lot_damages WHERE listing_id = :lid"), {"lid": listing_id})
                            t_conn.execute(text("DELETE FROM lot_announcements WHERE listing_id = :lid"), {"lid": listing_id})

                            # Вставляємо нові
                            if p.lot_images:
                                img_data = [{"lid": listing_id, "u": img} for img in p.lot_images if img]
                                if img_data:
                                    t_conn.execute(text("INSERT INTO lot_images (listing_id, url) VALUES (:lid, :u)"), img_data)

                            if p.lot_damages:
                                dmg_data = [{"lid": listing_id, "d": d} for d in p.lot_damages if d]
                                if dmg_data:
                                    t_conn.execute(text("INSERT INTO lot_damages (listing_id, damage_description) VALUES (:lid, :d)"), dmg_data)

                            if p.lot_announcements:
                                ann_data = [{"lid": listing_id, "n": n} for n in p.lot_announcements if n]
                                if ann_data:
                                    t_conn.execute(text("INSERT INTO lot_announcements (listing_id, note_text) VALUES (:lid, :n)"), ann_data)

                        processed_count += 1
                    except Exception as e:
                        print(f"Помилка при записі ID {row[0]}: {e}")

            # <--- НОВЕ: Записуємо прогрес ТІЛЬКИ після успішного підтвердження транзакції всього батчу
            last_id = current_batch_last_id
            try:
                with open(PROGRESS_FILE, 'w') as f:
                    f.write(str(last_id))
            except Exception as e:
                print(f"⚠️ Помилка запису файлу прогресу: {e}")
            # -----------------------------------------------------------------------------------------

    print(f"🎉 Міграція завершена! Успішно опрацьовано лотів: {processed_count}")

if __name__ == "__main__":
    run_migration()
