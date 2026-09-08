# AXS — Docker

Два образа. Оба: Chrome **152.0.7977.82**, NoDriver, прокси, UI на `8080`.

## Production (сдача ТЗ)

Экран Xvfb + noVNC. Chrome не headless — так проходит Cloudflare.

- `Dockerfile`
- `docker-compose.yml`

```
docker compose up -d --build
```

UI: http://127.0.0.1:8080  
Экран: http://127.0.0.1:6080/vnc.html

## Тесты (меньше RAM)

Без Xvfb/noVNC, Chrome headless. Быстрее поднять, Turnstile чаще режет. Не для сдачи.

- `Dockerfile.headless`
- `docker-compose.headless.yml`

```
docker compose down
docker compose -f docker-compose.headless.yml up -d --build
```

Только http://127.0.0.1:8080 — блока «Экран в Docker» нет.

Оба стека сразу нельзя: один порт 8080.
