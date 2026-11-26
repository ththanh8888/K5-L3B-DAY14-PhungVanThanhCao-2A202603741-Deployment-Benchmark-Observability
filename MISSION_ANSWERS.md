# Day 14 Lab - Mission Answers

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns found (`01-localhost-vs-production/develop/app.py`)

1. **API key và database URL hardcode** (dòng 17-18): `OPENAI_API_KEY = "sk-..."`, `DATABASE_URL = "postgresql://admin:password123@..."`. Push lên GitHub là lộ secret, và muốn đổi key phải sửa code rồi deploy lại.
2. **Không có quản lý cấu hình** (dòng 21-22): `DEBUG = True`, `MAX_TOKENS = 500` ghi cứng, không đổi được giữa dev/staging/production.
3. **Dùng `print()` thay vì logging** (dòng 33, 36, 38): không có level, không có timestamp, không phải JSON nên log aggregator không parse được.
4. **Log ra secret** (dòng 34): `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")` ghi API key vào log.
5. **Không có health check** (dòng 42-43): platform (Railway/Render/Kubernetes) không biết agent còn sống hay đã treo để restart.
6. **Port cố định** (dòng 52): `port=8000`, không đọc biến `PORT`. Railway/Render cấp port qua biến môi trường nên app không nhận được traffic.
7. **Host `localhost`** (dòng 51): chỉ nhận kết nối từ chính máy đó, trong container sẽ không truy cập được từ ngoài. Cần `0.0.0.0`.
8. **`reload=True`** (dòng 53): chế độ auto-reload dành cho phát triển, tốn tài nguyên và không an toàn trên production.
9. **Không xử lý shutdown** (toàn file): không có SIGTERM handler hay lifespan nên request đang chạy có thể bị cắt ngang khi tắt.

### Exercise 1.2: Chạy bản basic

```bash
cd 01-localhost-vs-production/develop
python app.py
# terminal khác:
curl -i -X POST "http://localhost:8000/ask?question=Hello"
curl -i -X POST http://localhost:8000/ask -H 'Content-Type: application/json' -d '{"question":"Hello"}'
```

Kết quả (query string):

```
HTTP/1.1 200 OK
server: uvicorn
content-type: application/json

{"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
```

Kết quả (gửi JSON body):

```
HTTP/1.1 422 Unprocessable Entity

{"detail":[{"type":"missing","loc":["query","question"],"msg":"Field required","input":null}]}
```

Log phía server in ra `[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this`, tức là app ghi secret ra log. Đây là anti-pattern ở 1.1. Ngoài ra `GET /health` trả 404 vì bản develop không có health check.

Quan sát: app chạy và trả lời được, nhưng chưa production-ready vì các vấn đề ở 1.1. Bản develop nhận `question` qua query string, không nhận JSON (gửi JSON bị 422).

### Exercise 1.3: Bảng so sánh develop và production

| Feature | Develop | Production | Tại sao quan trọng? |
|---------|---------|------------|---------------------|
| Config | Hardcode trong code (`app.py` dòng 17-22) | Đọc từ biến môi trường qua `config.py` (`os.getenv`), có `validate()` fail fast | Đổi cấu hình giữa môi trường mà không sửa code; secret không nằm trong repo |
| Secrets | Key và mật khẩu DB ghi thẳng trong code, còn in ra log | Lấy từ env (`OPENAI_API_KEY`, `AGENT_API_KEY`), không log secret | Tránh lộ key khi push GitHub hoặc đọc log |
| Port / Host | Cố định `localhost:8000` | `HOST` mặc định `0.0.0.0`, `PORT` từ env | Cloud inject `PORT`; container cần nhận kết nối từ ngoài |
| Health check | Không có | `GET /health` (liveness) và `GET /ready` (readiness, 503 khi chưa sẵn sàng) | Platform biết khi nào restart, load balancer biết khi nào được gửi traffic |
| Logging | `print()` | JSON có `event`, không log secret | Dễ tìm kiếm và phân tích trong Datadog/Loki; không rò rỉ dữ liệu nhạy cảm |
| Shutdown | Tắt đột ngột | `lifespan` + handler SIGTERM, đặt `is_ready=False` rồi hoàn tất request đang chạy | Deploy hoặc scale không làm rớt request của người dùng |
| Reload / Debug | `reload=True` luôn bật | `reload=settings.debug`, mặc định `false` | Không chạy chế độ phát triển trên production |
| Input validation | Tham số `question` qua query, không kiểm tra | Đọc JSON body, thiếu `question` thì trả lỗi 422 rõ ràng | API ổn định, lỗi đầu vào dễ hiểu |
| CORS | Không có | Chỉ cho phép origin cấu hình qua `ALLOWED_ORIGINS` | Giới hạn trang web nào được gọi API |

### Checkpoint 1

- Hardcode secret nguy hiểm vì code thường nằm trong git; một lần push là key lộ vĩnh viễn trong lịch sử commit.
- Environment variables tách cấu hình khỏi code (nguyên tắc 12-Factor).
- `/health` cho biết process còn sống; `/ready` cho biết có nhận traffic được chưa.
- Graceful shutdown: khi nhận SIGTERM, ngừng nhận request mới, xử lý xong request đang chạy rồi mới thoát.

---

## Part 2: Docker

### Exercise 2.1: Dockerfile develop (`02-docker/develop/Dockerfile`)

1. **Base image:** `python:3.11`, bản Python đầy đủ, nặng (khoảng 1 GB).
2. **Working directory:** `/app`. Các lệnh `COPY`, `RUN`, `CMD` phía sau chạy trong thư mục này.
3. **Vì sao `COPY requirements.txt` trước:** Docker cache theo từng layer. Requirements ít đổi nên layer `pip install` được dùng lại. Khi chỉ sửa `app.py`, Docker chỉ build lại từ bước copy code, không cài lại thư viện. Nếu copy code trước, mỗi lần sửa code đều phải cài lại toàn bộ thư viện.
4. **`CMD` khác `ENTRYPOINT`:** `CMD` là lệnh mặc định và có thể bị ghi đè khi `docker run image <lệnh khác>`. `ENTRYPOINT` là chương trình cố định của container; tham số truyền vào `docker run` được nối thêm vào sau nó.

### Exercise 2.2: Build và chạy bản develop

Build từ gốc repo: `docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .`

```
$ docker run -d --rm --name dev -p 8000:8000 my-agent:develop
$ curl localhost:8000/health
{"status":"ok","uptime_seconds":0.7,"container":true}
$ curl -X POST "localhost:8000/ask?question=Hello"
{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```

### Exercise 2.3: Multi-stage build

- **Stage 1 (builder):** dùng `python:3.11-slim`, cài `gcc`, `libpq-dev` và chạy `pip install --user`. Stage này chỉ để build, không dùng để deploy.
- **Stage 2 (runtime):** dùng `python:3.11-slim`, chỉ copy `/root/.local` (thư viện đã cài) và source, rồi chạy bằng user non-root `appuser`. Image không chứa `gcc` hay cache của apt.
- **Vì sao nhỏ hơn:** các công cụ build và layer của stage 1 bị bỏ đi; base image là slim thay vì bản đầy đủ.

Kích thước đo bằng `docker images` (cột Size) trên máy này:

| Image | Size (disk usage) | Content size |
|-------|-------------------|--------------|
| `my-agent:develop` | 1.67 GB (1667.8 MB) | 426 MB |
| `my-agent:advanced` | 240 MB (239.8 MB) | 57.4 MB |

Chênh lệch theo disk usage: (1667.8 − 239.8) / 1667.8 ≈ **85.6%** nhỏ hơn. Image advanced thỏa mục tiêu dưới 500 MB.

### Exercise 2.4: Docker Compose stack

Chạy `touch 02-docker/production/.env.local` rồi `docker compose up -d --build` trong `02-docker/production`.

```
NAME                  IMAGE                  SERVICE   STATUS
production-agent-1    production-agent       agent     Up (healthy)   8000/tcp
production-nginx-1    nginx:alpine           nginx     Up             0.0.0.0:80->80/tcp, 443->443/tcp
production-qdrant-1   qdrant/qdrant:v1.9.0   qdrant    Up (healthy)   6333-6334/tcp
production-redis-1    redis:7-alpine         redis     Up (healthy)   6379/tcp
```

Sơ đồ:

```
Client ──:80──> [nginx] ──> [agent :8000] ──> [redis :6379]   (session, rate limit)
                                         └──> [qdrant :6333]  (vector DB)
          (cả 4 service nằm trong network "internal"; chỉ nginx publish cổng ra ngoài)
```

- `depends_on` với `condition: service_healthy` bắt agent chờ redis và qdrant healthy rồi mới khởi động.
- Agent không publish cổng; mọi request phải đi qua Nginx (reverse proxy, load balancer, rate limit 10 req/s mỗi IP, thêm security header).

Test qua Nginx:

```
$ curl -i localhost/health
HTTP/1.1 200 OK
Server: nginx
X-Frame-Options: DENY
X-Content-Type-Options: nosniff

{"status":"ok","uptime_seconds":19.5,"version":"2.0.0","timestamp":"2026-11-26T10:40:24.076271"}

$ curl -X POST localhost/ask -H 'Content-Type: application/json' -d '{"question":"Hello"}'
{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```

Header `Server: nginx` và `X-Frame-Options` cho thấy request thực sự đi qua Nginx. Sau khi test tôi đã chạy `docker compose down`.

---

## Part 3: Cloud Deployment

### Exercise 3.1: Deploy

- **URL:** _(điền sau khi deploy agent Part 6)_
- **Nền tảng:** _(Railway hoặc Render)_
- **Bằng chứng:** xem `DEPLOYMENT.md` và thư mục `screenshots/`.

### Exercise 3.2: So sánh `railway.toml` và `render.yaml`

Đối chiếu hai file mẫu trong `03-cloud-deployment/railway/` và `03-cloud-deployment/render/`:

| Tiêu chí | `railway.toml` | `render.yaml` |
|----------|----------------|---------------|
| Định dạng | TOML, chỉ mô tả build và deploy của một service | YAML Blueprint, mô tả cả hạ tầng gồm nhiều service (web, redis) |
| Build | `[build] builder = "NIXPACKS"` (tự nhận Python); có thể đổi sang `"DOCKERFILE"` | `runtime: python` kèm `buildCommand: pip install -r requirements.txt` (hoặc `runtime: docker`) |
| Start command | `startCommand = "uvicorn app:app --host 0.0.0.0 --port $PORT"` | `startCommand: uvicorn app:app --host 0.0.0.0 --port $PORT` |
| Health check | `healthcheckPath = "/health"`, `healthcheckTimeout = 30` | `healthCheckPath: /health` |
| Restart | `restartPolicyType = "ON_FAILURE"`, `restartPolicyMaxRetries = 3` | Render tự restart service lỗi, không có khai báo tương đương trong file |
| Biến môi trường | Đặt qua dashboard hoặc `railway variables set` (file chỉ ghi chú) | Khai báo ngay trong file: giá trị cố định, `sync: false` (nhập tay trên dashboard), hoặc `generateValue: true` (Render tự sinh) |
| Redis | Thêm service Redis riêng trên dashboard | Khai báo `type: redis` ngay trong cùng file |
| Region và gói | Không khai báo trong file | `region: singapore`, `plan: free` |
| Tự deploy | Railway deploy khi có commit hoặc chạy `railway up` | `autoDeploy: true`; Render đồng bộ hạ tầng khi file được commit |

Cả hai đều khai báo health check path, nên platform biết khi nào service sẵn sàng và khi nào cần restart. Khác biệt chính: Render gom cả hạ tầng vào một file, còn Railway chỉ cấu hình build/deploy và phần còn lại làm trên dashboard.

### Exercise 3.3: Pipeline `cloudbuild.yaml` và `service.yaml` (GCP Cloud Run)

`cloudbuild.yaml` chạy 4 bước tuần tự: (1) `test` chạy `pytest` trong `python:3.11-slim`; (2) `build` dựng Docker image, gắn tag theo `$COMMIT_SHA` và `latest`, dùng `--cache-from` để tận dụng layer cache; (3) `push` đẩy image lên Container Registry; (4) `deploy` chạy `gcloud run deploy` ở region `asia-southeast1` với min 1 và max 10 instance, và lấy secret từ Secret Manager. Test lỗi thì pipeline dừng, image không được deploy. `service.yaml` là khai báo Knative cho Cloud Run: autoscale `minScale: 1` đến `maxScale: 10`, mỗi instance nhận tối đa 80 request đồng thời, giới hạn 1 CPU / 512 MiB, nạp secret qua `secretKeyRef`, có `livenessProbe` gọi `/health` và `startupProbe` gọi `/ready`.

---

## Part 4: API Security

### Exercise 4.1: API key (`04-api-gateway/develop/app.py`)

Chạy: `AGENT_API_KEY=secret-key-123 python app.py`

```
$ curl -i -X POST localhost:8000/ask -H 'Content-Type: application/json' -d '{"question":"hello"}'
HTTP/1.1 401 Unauthorized
{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

$ curl -i -X POST localhost:8000/ask -H 'X-API-Key: secret-key-123' -H 'Content-Type: application/json' -d '{"question":"hello"}'
HTTP/1.1 200 OK
{"question":"hello","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```

- **Kiểm tra key:** dependency `verify_api_key` đọc header `X-API-Key` (`APIKeyHeader(auto_error=False)`). Thiếu key trả 401, sai key trả 403.
- **Đổi key:** đặt biến môi trường `AGENT_API_KEY`, không sửa code.

### Exercise 4.2: JWT (`04-api-gateway/production`)

Lấy token ở `POST /auth/token` với `student` / `demo123`. Đăng nhập sai (ví dụ `admin`) trả `401 {"detail":"Invalid credentials"}`.

- Token là JWT ký bằng `JWT_SECRET`, chứa username, role và `exp` (hết hạn sau 60 phút).
- Gọi `/ask` kèm `Authorization: Bearer <token>`. Không có token trả 401 `Authentication required`; token hết hạn trả 401; token sai trả 403.

### Exercise 4.3: Rate limiting và cost guard

Vòng lặp 20 request liên tiếp bằng token của `student`:

```
1-10   HTTP/1.1 200 OK
11-20  HTTP/1.1 429 Too Many Requests
```

Ba trường hợp (token đã che):

```
# 401: không có token
$ curl -i -X POST localhost:8000/ask -H 'Content-Type: application/json' -d '{"question":"hello"}'
HTTP/1.1 401 Unauthorized
{"detail":"Authentication required. Include: Authorization: Bearer <token>"}

# 200: có token (request 1)
$ curl -i -X POST localhost:8000/ask -H "Authorization: Bearer <TOKEN>" -H 'Content-Type: application/json' -d '{"question":"hello"}'
HTTP/1.1 200 OK
content-type: application/json
x-content-type-options: nosniff
x-frame-options: DENY

{"question":"hello","answer":"Đây là câu trả lời từ AI agent (mock). ...","usage":{"requests_remaining":9,"budget_remaining_usd":2.1e-05}}

# 429: request thứ 11 trong 60 giây
HTTP/1.1 429 Too Many Requests
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
retry-after: 59

{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
```

**Thuật toán rate limit** (`rate_limiter.py`): sliding window. Mỗi user có một hàng đợi (deque) lưu thời điểm các request. Mỗi lần gọi, code bỏ các timestamp cũ hơn 60 giây, rồi đếm số còn lại. Nếu đã đạt giới hạn thì trả 429 kèm `Retry-After` (tính từ request cũ nhất trong cửa sổ); nếu chưa thì ghi timestamp mới. Giới hạn là 10 req/phút cho user và 100 req/phút cho admin.

**Cost guard** (`cost_guard.py`): tính chi phí từ số token đầu vào và đầu ra theo đơn giá GPT-4o-mini. Mỗi user có budget 1 USD/ngày và cả hệ thống có budget chung 10 USD/ngày. Vượt budget của user trả 402, vượt budget chung trả 503, và cảnh báo khi dùng đến một ngưỡng phần trăm của budget.

**Vì sao cần cả hai:** rate limit bảo vệ tốc độ, tức là chặn spam và tấn công dồn dập. Cost guard bảo vệ tiền. Một user có thể gửi ít request nhưng mỗi request rất dài, vẫn nằm trong rate limit mà tốn nhiều token. Ngược lại, request rẻ nhưng quá nhanh sẽ làm quá tải server dù không tốn nhiều tiền.

Ghi chú: ở bản mẫu này, state của rate limiter và cost guard nằm trong RAM của process, nên mất khi restart và không chia sẻ giữa nhiều instance. Đây là điểm Part 6 sửa bằng Redis. Trường `budget_remaining_usd` trong response thực ra trả `total_cost_usd` (chi phí đã dùng), không phải số tiền còn lại.

---

## Part 5: Scaling & Reliability

### Exercise 5.1: Health check và graceful shutdown

- **`/health` (liveness):** cho biết process còn sống. Trả 200 nếu app chạy; platform dựa vào đây để quyết định có restart container không. Ở bản production mẫu, nếu Redis mất thì `/health` báo `"status":"degraded"` nhưng vẫn trả 200.
- **`/ready` (readiness):** cho biết instance có sẵn sàng nhận traffic không. Ở bản mẫu, nếu ping Redis lỗi thì trả 503 `Redis not available`; load balancer sẽ ngừng gửi request tới instance đó nhưng không giết nó.
- **Graceful shutdown:** khi nhận SIGTERM, uvicorn ngừng nhận kết nối mới, chờ các request đang chạy xong, chạy phần shutdown của `lifespan` (log `Instance ... shutting down`) rồi mới thoát. Nhờ vậy rolling deploy hoặc scale-down không cắt ngang request của người dùng.

### Exercise 5.2: Stateless design

State nằm trong RAM của từng process (dict trong `app.py`) sẽ hỏng khi chạy nhiều instance, vì load balancer chia request cho các instance khác nhau, mà mỗi instance chỉ có phần bộ nhớ của nó. Request đầu tiên tạo session ở instance A; request sau rơi vào instance B thì B không thấy session và mất lịch sử hội thoại. State cũng mất khi instance restart hoặc bị scale-down. Cách sửa là đẩy state ra ngoài, vào Redis dùng chung, để instance nào cũng đọc được.

### Exercise 5.3: Scale 3 instance và test stateless

```
$ docker compose -p k5-day14-scaling up -d --build --scale agent=3
$ docker compose -p k5-day14-scaling ps
k5-day14-scaling-agent-1  Up (healthy)
k5-day14-scaling-agent-2  Up (healthy)
k5-day14-scaling-agent-3  Up (healthy)
k5-day14-scaling-nginx-1  Up
k5-day14-scaling-redis-1  Up (healthy)

$ python test_stateless.py
Session ID: f1f77a13-97cd-45b1-8244-9999c2bbf945
Request 1: [instance-e82d63]  Q: What is Docker?
Request 2: [instance-61b245]  Q: Why do we need containers?
Request 3: [instance-163552]  Q: What is Kubernetes?
Request 4: [instance-e82d63]  Q: How does load balancing work?
Request 5: [instance-61b245]  Q: What is Redis used for?
Total requests: 5
Instances used: {'instance-e82d63', 'instance-163552', 'instance-61b245'}
✅ All requests served despite different instances!
--- Conversation History ---
Total messages: 10
✅ Session history preserved across all instances via Redis!
```

**Giải thích:** 5 request cùng một `session_id` được Nginx chia round-robin cho 3 instance khác nhau (`instance-e82d63`, `instance-61b245`, `instance-163552`). Dù vậy lịch sử cuối cùng có đủ 10 message (5 câu hỏi và 5 câu trả lời). Điều đó chứng minh instance không giữ state cục bộ mà đọc và ghi session qua Redis dùng chung. Agent vì thế stateless và có thể scale ngang, thêm hay bớt instance mà không mất hội thoại. Sau test tôi đã chạy `docker compose -p k5-day14-scaling down`.

---

## Part 6: Final Project (`06-lab-complete/`)

Chạy `python check_production_ready.py` (bản đầy đủ, có Docker, Redis ở `redis://127.0.0.1:6390/0`):

```
================================================================
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 41/41 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
================================================================
```

Image đo được: 238 MB (build 30 s). `docker stop` thoát với exit code 0 trong 0.5 s.

Thiết kế chính:
- **Auth:** `APIKeyHeader(auto_error=False)`, thiếu hoặc sai key trả 401; so sánh bằng `hmac.compare_digest`. Dependency chạy trước khi validate body nên không bao giờ ra 422 thay cho 401.
- **Rate limit:** sliding window bằng Redis ZSET (`ZREMRANGEBYSCORE` → `ZCARD` → `ZADD` → `EXPIRE`), key theo hash của API key, vượt giới hạn trả 429 kèm `Retry-After`.
- **Cost guard:** `INCRBYFLOAT` vào key `cost:<ngày UTC>`; tổng chi phí ≥ `DAILY_BUDGET_USD` trả 402.
- **Thứ tự trong `/ask`:** auth → rate limit → budget → LLM → `record_cost`. Lỗi đầu vào trả JSON gọn (422), lỗi không lường trước trả 500 chung, stack trace chỉ vào log.
- **`/health` và `/ready`:** `/health` luôn 200; `/ready` trả 503 khi không ping được Redis. Redis client được tạo lười (không ping lúc import) nên container vẫn khởi động khi không có Redis.
- **Shutdown:** không tự đăng ký handler SIGTERM; để uvicorn xử lý và chỉ log trong `lifespan`.
- **Dockerfile:** 2 stage `python:3.11-slim`, user `appuser`, `HEALTHCHECK`, `CMD sh -c "exec uvicorn ... --port ${PORT:-8000}"` để uvicorn là PID 1.

Lưu ý: lần chạy đầu không có `REDIS_URL`, script không tự bật được container Redis trong WSL nên đạt 6/12. Sau khi tôi bật sẵn một container `redis:7-alpine` và truyền `REDIS_URL` thì đạt 12/12. Code app không đổi giữa hai lần chạy.

---

## AI log

| Lần | Tôi hỏi | Nhận được | Tôi tự kiểm tra / sửa |
|-----|---------|-----------|-----------------------|
| 1 | Đọc các file .md, lập kế hoạch làm bài | Kế hoạch theo checkpoint và bảng điểm | Đối chiếu với RUBRIC.md, CHECKPOINTS.md |
| 2 | Hướng dẫn cài WSL2, Docker Desktop, môi trường Python | Các bước cài đặt và xử lý lỗi | Tự chạy; kiểm tra `os.name` in `posix` và `hello-world` chạy được |
| 3 | Soạn nháp Part 1 (1.1, 1.3) | Danh sách anti-pattern và bảng so sánh | Đối chiếu từng dòng với `develop/app.py` và `production/app.py`; tự chạy bước 1.2 |
