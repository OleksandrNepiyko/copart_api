import requests
import json

def test_api():
    number = 63137155
    resp = requests.get(f'http://localhost:8000/lot/{number}', timeout=40)

    if resp.status_code == 200:
        data = resp.json()
        with open ('response.json', 'w') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    else:
        print(f"Error: {resp.status_code}")

if __name__ == "__main__":
    test_api()