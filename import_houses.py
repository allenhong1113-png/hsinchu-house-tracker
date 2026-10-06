from database import init_db, upsert_house

init_db()

houses = [
    {
        "name": "竹科潤隆",
        "district": "新竹市",
        "address": "新竹市東區埔頂三路30號",
        "price": 1986,
        "area": 31.25,
        "age": 3.3,
        "rooms": 2,
        "parking": "坡道平面",
        "floor": "",
        "source": "房仲",
        "url": "",
        "lat": None,
        "lon": None
    },

    {
        "name": "美學苑",
        "district": "新竹市",
        "address": "新竹市北區經國路二段",
        "price": 1398,
        "area": 32.88,
        "age": 19.8,
        "rooms": 2,
        "parking": "坡道平面",
        "floor": "2F",
        "source": "房仲",
        "url": "",
        "lat": None,
        "lon": None
    },

    {
        "name": "佳陞禾樂",
        "district": "竹北市",
        "address": "新竹縣竹北市光明十五街",
        "price": 1728,
        "area": 37.34,
        "age": 4.2,
        "rooms": 2,
        "parking": "坡道平面",
        "floor": "",
        "source": "永慶",
        "url": "",
        "lat": None,
        "lon": None
    },

    {
        "name": "星都匯D區",
        "district": "竹東鎮",
        "address": "新竹縣竹東鎮旭光一路",
        "price": 1528,
        "area": 34.78,
        "age": 0.3,
        "rooms": 2,
        "parking": "坡道平面",
        "floor": "14F",
        "source": "永慶",
        "url": "",
        "lat": None,
        "lon": None
    }
]

for house in houses:

    result = upsert_house(house)

    print(
        house["name"],
        "=>",
        result
    )

print("資料庫更新完成")
