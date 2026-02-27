import requests
import json
import time

def test_post_api(json_filepath: str):
    # 1. Читаємо твій тестовий JSON з файлу
    try:
        with open(json_filepath, 'r', encoding='utf-8') as f:
            raw_data = json.load(f)
    except FileNotFoundError:
        print(f"Помилка: Файл '{json_filepath}' не знайдено!")
        return
    except json.JSONDecodeError:
        print(f"Помилка: Файл '{json_filepath}' містить невалідний JSON!")
        return

    raw_data = raw_data[0]
    # 2. Формуємо payload згідно з нашою Pydantic-схемою.
    # Пам'ятаєш, в iaai_schema ми вказали: class IAAIRawPayload(BaseModel): lot_data: Dict[str, Any]
    payload = {
        "lot_data": raw_data
    }

    # Вкажи тут правильний URL твого ендпоінту
    # Якщо ти робив через routers.py, як ми обговорювали, то шлях буде приблизно такий:
    url = 'http://127.0.0.1:8000/api/v1/iaai/lots'

    print(f"Відправляємо POST запит на {url}...")
    start_time = time.time()

    try:
        # 3. Робимо POST запит, передаючи JSON
        resp = requests.post(url, json=payload, timeout=10)

        duration = time.time() - start_time
        print(f"Час обробки: {duration:.4f} сек (Статус: {resp.status_code})")

        # 4. Аналізуємо відповідь
        if resp.status_code == 200:
            print("Дані успішно прийняті! Відповідь сервера:")
            print(json.dumps(resp.json(), indent=2, ensure_ascii=False))
        elif resp.status_code == 422:
            print("Помилка валідації Pydantic (Unprocessable Entity)!")
            print("Деталі того, що пішло не так:")
            print(json.dumps(resp.json(), indent=2, ensure_ascii=False))
        else:
            print(f"Помилка сервера! Код: {resp.status_code}")
            print("Текст помилки:", resp.text)

    except requests.exceptions.RequestException as e:
        print(f"Помилка з'єднання: {e}")

if __name__ == "__main__":
    # Вкажи назву свого файлу з тестовим JSON (наприклад, 'iaai_sample.json')
    test_file_name = 'Automobile_2001.json'
    test_post_api(test_file_name)