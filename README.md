# AXS — Docker

Chrome **152.0.7977.82**, NoDriver, прокси, UI на `8080`. Стеки по одному: порт один.

## Production (сдача)

Headed Chrome + Xvfb/openbox, без VNC. Cloudflare как у полного образа, скриншот в `screenshots/`.

- `Dockerfile` + `docker-compose.yml`

```
docker compose up -d --build
```

UI: http://127.0.0.1:8080

## Тесты (есть экран)

То же headed-окружение плюс noVNC, чтобы смотреть Chrome.

- `Dockerfile.test` + `docker-compose.test.yml`

```
docker compose down
docker compose -f docker-compose.test.yml up -d --build
```

UI: http://127.0.0.1:8080  
Экран: http://127.0.0.1:6080/vnc.html
