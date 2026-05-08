from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app, raise_server_exceptions=True)

payload = {
    "players": [
        {"account_id": 185602862, "hero_id": 1,  "role": 1, "is_radiant": True},
        {"account_id": 105774679, "hero_id": 11, "role": 2, "is_radiant": True},
        {"account_id": 97129625,  "hero_id": 2,  "role": 3, "is_radiant": True},
        {"account_id": None,      "hero_id": 86, "role": 4, "is_radiant": True},
        {"account_id": 135953784, "hero_id": 26, "role": 5, "is_radiant": True},
        {"account_id": 124437009, "hero_id": 8,  "role": 1, "is_radiant": False},
        {"account_id": None,      "hero_id": 17, "role": 2, "is_radiant": False},
        {"account_id": 104794975, "hero_id": 28, "role": 3, "is_radiant": False},
        {"account_id": None,      "hero_id": 35, "role": 4, "is_radiant": False},
        {"account_id": 90972450,  "hero_id": 29, "role": 5, "is_radiant": False},
    ]
}

r = client.post("/probability/predict", json=payload)
print("Status:", r.status_code)
if r.status_code == 200:
    d = r.json()
    print(f"Radiant win%: {d['win_probability_radiant']*100:.1f}%")
    print(f"Confidence:   {d['confidence']}")
    print(f"Score diff:   {d['score_diff']:+.2f}")
    print(f"Matchup cvg:  {d['matchup_coverage']:.1%}")
    print("Top factors:")
    for f in d["top_factors"]:
        print(f"  [{f['signal']}] {f['label']}: {f['value']:+.2f}")
else:
    print(r.text[:600])

# Test reload endpoint
r2 = client.post("/probability/reload")
print("\nReload status:", r2.status_code)
print("Reload signals:", r2.json().get("signals"))
