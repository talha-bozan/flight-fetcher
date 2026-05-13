# flight-fetcher

Hollanda → İstanbul uçuş fiyatlarını her 6 saatte bir kontrol eder; bir uçuş **10,000 TL altına** düşerse `zubeyirtemel@outlook.com` adresine mail atar. GitHub Actions üzerinde **ücretsiz serverless** çalışır.

## Mimari

- `fast-flights` (Google Flights scraper, API key yok)
- `Frankfurter API` ile EUR→TRY dönüşümü
- Gmail SMTP ile mail gönderimi
- GitHub Actions cron (her 6 saatte bir)
- `state.json` repo'ya commit edilerek dedupe sağlanır

## Konfigürasyon

Tüm ayarlar `src/config.py` içinde. En sık değiştirilen alan:

```python
DEPARTURE_DATES = [
    "2026-07-20", "2026-07-21", "2026-07-22",
    "2026-07-23", "2026-07-24", "2026-07-25",
]
THRESHOLD_TRY = 10000
```

Workflow ortam değişkenleri ile de override edilebilir: `FF_DATES`, `FF_ORIGINS`, `FF_DESTINATIONS`, `FF_THRESHOLD_TRY`.

## Kurulum (tek seferlik)

### 1. Gmail App Password

1. https://myaccount.google.com/security → **2-Step Verification** açık olmalı
2. https://myaccount.google.com/apppasswords → uygulama adı `flight-fetcher` → **Create**
3. 16 haneli şifreyi kopyala (boşlukları olabilir; SMTP boşluksuz da kabul eder)

### 2. GitHub repo

1. https://github.com/new → name `flight-fetcher` → **Public** (sınırsız ücretsiz Actions için) → Create
2. Lokal klasörden push'la:
   ```bash
   git remote add origin https://github.com/<KULLANICI>/flight-fetcher.git
   git branch -M main
   git push -u origin main
   ```

### 3. Secret ekle

Repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**
- Name: `GMAIL_APP_PASSWORD`
- Value: (yukarıdaki 16 haneli şifre)

### 4. İlk run

Repo → **Actions** tab → "Flight Check" workflow → **Run workflow** düğmesi → Run

## Lokal test

```bash
python -m venv .venv
. .venv/Scripts/activate    # Windows
pip install -r requirements.txt

# DRY_RUN: hiç mail göndermez, sadece log yazar
$env:DRY_RUN = "true"
python -m src.main
```

## Test mail'i tetiklemek

Eşiği geçici olarak 999999 yap (her uçuş ucuz görünür):
```bash
$env:FF_THRESHOLD_TRY = "999999"
$env:GMAIL_APP_PASSWORD = "..."  # gerçek app password
python -m src.main
```

## Sorun giderme

- **Hiç uçuş gelmiyor**: 3 ardışık başarısızlıkta admin mail gelir. Sebep genelde Google Flights tarafında rate-limit veya `fast-flights` kütüphanesinin geçici bir sorunu. 6 saat bekle, kendi kendine düzelir.
- **Mail spam**: `state.json` dedupe yapar. Aynı uçuş 24 saat içinde tekrar mail tetiklemez. 500 TL altı fiyat değişimleri de yeniden tetiklemez.
- **Cron çalışmıyor**: GitHub, **60 gün hiç push olmazsa** zamanlanmış workflow'ları durdurur. `state.json` commit'i her run'da bunu engeller.

## Dosya yapısı

```
flight-fetcher/
├── .github/workflows/check.yml   # cron
├── src/
│   ├── config.py                 # AYARLAR BURADA
│   ├── fetcher.py                # fast-flights
│   ├── currency.py               # EUR→TRY
│   ├── notifier.py               # Gmail SMTP
│   ├── state.py                  # dedupe
│   └── main.py                   # orkestratör
├── state.json                    # commit'lenen dedupe state
├── requirements.txt
└── README.md
```
