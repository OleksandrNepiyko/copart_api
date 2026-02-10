import requests
import json
import time

def test_api():
    numbers = [63137155, 73737055, 99382185]

    for number in numbers:
        # Фіксуємо час початку
        start_time = time.time()

        try:
            resp = requests.get(f'http://localhost:8000/lot/{number}', timeout=1000)

            # Обчислюємо тривалість
            duration = time.time() - start_time
            print(f"Запит для лоту {number}: {duration:.4f} сек (Статус: {resp.status_code})")

            if resp.status_code == 200:
                data = resp.json()
                # Зберігаємо останній успішний запит у файл
                with open('response.json', 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
            else:
                print(f"Помилка для {number}: {resp.status_code}")

        except requests.exceptions.RequestException as e:
            print(f"Помилка з'єднання для {number}: {e}")

if __name__ == "__main__":
    test_api()