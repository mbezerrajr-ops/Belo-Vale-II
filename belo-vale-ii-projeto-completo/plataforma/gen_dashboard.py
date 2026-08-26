# -*- coding: utf-8 -*-
import json

BASE = "/tmp/claude-0/-home-user-Balancetes-porto/6cc42e22-5678-5e79-9cba-4f9e401567a5/scratchpad/leo_figueiroa"

cows = json.load(open(f"{BASE}/cows_final.json", encoding="utf-8"))
cows_json = json.dumps(cows, ensure_ascii=False, separators=(",", ":"))

trend = [
    {"date":"2022-11-14","n_vacas":111,"total_L":2044.0,"media_L_vaca":18.41},
    {"date":"2022-12-08","n_vacas":114,"total_L":2108.0,"media_L_vaca":18.49},
    {"date":"2022-12-25","n_vacas":108,"total_L":2040.0,"media_L_vaca":18.89},
    {"date":"2023-01-08","n_vacas":27,"total_L":321.5,"media_L_vaca":11.91},
    {"date":"2023-01-17","n_vacas":101,"total_L":1894.0,"media_L_vaca":18.75},
    {"date":"2023-02-15","n_vacas":106,"total_L":1814.0,"media_L_vaca":17.11},
    {"date":"2023-03-01","n_vacas":100,"total_L":1749.5,"media_L_vaca":17.5},
    {"date":"2023-03-13","n_vacas":24,"total_L":643.0,"media_L_vaca":26.79},
    {"date":"2023-03-27","n_vacas":100,"total_L":1736.0,"media_L_vaca":17.36},
    {"date":"2023-04-17","n_vacas":102,"total_L":1755.0,"media_L_vaca":17.21},
    {"date":"2023-05-09","n_vacas":118,"total_L":1815.5,"media_L_vaca":15.39},
    {"date":"2023-05-22","n_vacas":118,"total_L":1734.5,"media_L_vaca":14.7},
    {"date":"2023-06-10","n_vacas":114,"total_L":1782.5,"media_L_vaca":15.64},
    {"date":"2023-07-04","n_vacas":80,"total_L":1686.0,"media_L_vaca":21.07},
    {"date":"2023-07-19","n_vacas":87,"total_L":1788.0,"media_L_vaca":20.55},
    {"date":"2023-08-28","n_vacas":95,"total_L":1965.5,"media_L_vaca":20.69},
    {"date":"2023-09-11","n_vacas":98,"total_L":1957.5,"media_L_vaca":19.97},
    {"date":"2023-10-04","n_vacas":101,"total_L":2017.5,"media_L_vaca":19.98},
    {"date":"2023-10-19","n_vacas":75,"total_L":1163.5,"media_L_vaca":15.51},
    {"date":"2023-10-28","n_vacas":106,"total_L":2080.0,"media_L_vaca":19.62},
    {"date":"2023-11-28","n_vacas":113,"total_L":2278.0,"media_L_vaca":20.16},
    {"date":"2023-12-22","n_vacas":115,"total_L":2354.6,"media_L_vaca":20.47},
    {"date":"2024-01-27","n_vacas":129,"total_L":2666.5,"media_L_vaca":20.67},
    {"date":"2024-03-05","n_vacas":123,"total_L":2691.3,"media_L_vaca":21.88},
    {"date":"2024-04-19","n_vacas":120,"total_L":1953.0,"media_L_vaca":16.27},
    {"date":"2024-05-17","n_vacas":106,"total_L":1815.0,"media_L_vaca":17.12},
    {"date":"2024-06-03","n_vacas":110,"total_L":1905.5,"media_L_vaca":17.32},
    {"date":"2024-07-02","n_vacas":117,"total_L":2126.5,"media_L_vaca":18.18},
    {"date":"2024-07-19","n_vacas":121,"total_L":2449.0,"media_L_vaca":20.24},
    {"date":"2024-08-22","n_vacas":125,"total_L":2538.0,"media_L_vaca":20.3},
    {"date":"2024-09-26","n_vacas":138,"total_L":2758.0,"media_L_vaca":19.99},
    {"date":"2024-11-08","n_vacas":143,"total_L":2855.5,"media_L_vaca":19.97},
    {"date":"2025-01-07","n_vacas":138,"total_L":2964.5,"media_L_vaca":21.48},
    {"date":"2025-03-06","n_vacas":122,"total_L":2602.5,"media_L_vaca":21.33},
    {"date":"2025-04-16","n_vacas":122,"total_L":2439.0,"media_L_vaca":19.99},
    {"date":"2025-06-18","n_vacas":126,"total_L":2467.5,"media_L_vaca":19.58},
    {"date":"2025-07-21","n_vacas":125,"total_L":2720.0,"media_L_vaca":21.76},
    {"date":"2025-09-05","n_vacas":119,"total_L":2734.0,"media_L_vaca":22.97},
    {"date":"2025-10-06","n_vacas":129,"total_L":2748.5,"media_L_vaca":21.31},
    {"date":"2025-11-04","n_vacas":127,"total_L":2822.5,"media_L_vaca":22.22},
    {"date":"2025-12-02","n_vacas":126,"total_L":2850.0,"media_L_vaca":22.62},
]
# ultimo ponto recalculado com os dados finais (soma de AV entre todas as vacas, com ou sem lote)
av_vals = [c["av"] for c in cows if c["av"] is not None]
trend.append({
    "date": "2026-07-22",
    "n_vacas": len(av_vals),
    "total_L": round(sum(av_vals), 1),
    "media_L_vaca": round(sum(av_vals) / len(av_vals), 2)
})
trend_json = json.dumps(trend, ensure_ascii=False, separators=(",", ":"))

parto_month = {"2023-02":1,"2023-03":2,"2023-04":6,"2023-05":5,"2023-06":2,"2023-09":4,"2023-10":2,"2023-11":2,"2023-12":4,"2024-01":2,"2024-02":4,"2024-03":2,"2024-04":2,"2024-05":9,"2024-06":4,"2024-07":6,"2024-08":9,"2024-09":4,"2024-10":5,"2024-11":5,"2024-12":6,"2025-01":7,"2025-02":6,"2025-03":9,"2025-04":8,"2025-05":18,"2025-06":14,"2025-07":14,"2025-08":10,"2025-09":10,"2025-10":11,"2025-11":10,"2025-12":1,"2026-01":9,"2026-02":12}
parto_json = json.dumps(parto_month, ensure_ascii=False, separators=(",", ":"))

feed_config = {
    "LOTE 1": {"Concentrado": 1018.2, "Caroço": 96.6, "Silagem": 630.0, "Casca de Mandioca": 220.0},
    "LOTE 2": {"Concentrado": 848.5, "Caroço": 96.6, "Silagem": 630.0, "Casca de Mandioca": 220.0},
    "LOTE 3": {"Concentrado": 169.7, "Caroço": 0.0, "Silagem": 210.0, "Casca de Mandioca": 55.0},
}
feed_json = json.dumps(feed_config, ensure_ascii=False, separators=(",", ":"))

PRECO_LEITE = 2.59

n_total = len(cows)
n_vl = sum(1 for c in cows if c["sit"] == "VL")
n_vs = sum(1 for c in cows if c["sit"] == "VS")
n_com_lote = sum(1 for c in cows if c["lote"])
n_sem_lote = n_total - n_com_lote

print("n_total", n_total, "VL", n_vl, "VS", n_vs, "com_lote", n_com_lote, "sem_lote", n_sem_lote)
print("cows_json bytes:", len(cows_json.encode("utf-8")))

with open(f"{BASE}/_inject.json", "w", encoding="utf-8") as f:
    json.dump({
        "cows_json": cows_json, "trend_json": trend_json, "parto_json": parto_json,
        "feed_json": feed_json, "preco_leite": PRECO_LEITE,
        "n_total": n_total, "n_vl": n_vl, "n_vs": n_vs, "n_com_lote": n_com_lote, "n_sem_lote": n_sem_lote
    }, f, ensure_ascii=False)
