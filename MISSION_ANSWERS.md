# Day 14 Lab — Mission Answers

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns phát hiện trong `01-localhost-vs-production/develop/app.py`

1. **Hardcode secrets trực tiếp trong source code (dòng 17–18):**
   - `OPENAI_API_KEY = "sk-hardcoded-fake-key-never-do-this"` và `DATABASE_URL = "postgresql://admin:password123@localhost:5432/mydb"`.
   - Khi push code lên GitHub, toàn bộ API key và mật khẩu database bị lộ ngay lập tức trong lịch sử Git. Bản `production/config.py` (dòng 27, 32) đã sửa bằng cách đọc qua `os.getenv("OPENAI_API_KEY", "")` và `os.getenv("AGENT_API_KEY", "")`.
2. **Không có quản lý cấu hình theo môi trường & bật cứng `DEBUG = True` (dòng 21–22):**
   - `DEBUG = True` và `MAX_TOKENS = 500` bị gắn cứng trong code, không thể thay đổi giữa `development`, `staging`, `production` mà không sửa code. Bản `production/config.py` gom toàn bộ vào dataclass `Settings` đọc từ biến môi trường và có hàm `validate()` fail-fast.
3. **Dùng `print()` thay cho structured logging và in cả secret ra stdout (dòng 33–34, 38):**
   - `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")` vừa làm lộ secret trong hệ thống thu thập log, vừa thiếu timestamp, log level và cấu trúc JSON khiến các hệ thống log tập trung (Loki, Datadog, CloudWatch) rất khó parse/truy vấn. Bản `production/app.py` (dòng 28–31, 111–122) dùng `logging` định dạng JSON và chỉ ghi metadata an toàn (`question_length`, `client_ip`).
4. **Thiếu Health Check (`/health`) và Readiness Check (`/ready`) (dòng 42–43):**
   - Cloud platform (Railway, Render, Kubernetes) và Load Balancer không biết process còn sống hay đã sẵn sàng nhận tải chưa để tự động restart hoặc ngắt route traffic. Bản `production/app.py` đã bổ sung `GET /health` (dòng 135) và `GET /ready` (dòng 152).
5. **Bind cứng `host="localhost"`, cứng `port=8000` và bật `reload=True` (dòng 50–54):**
   - `host="localhost"` chỉ nhận kết nối loopback bên trong container nên truy cập từ ngoài Docker/Cloud sẽ thất bại (phải dùng `0.0.0.0`).
   - `port=8000` cố định sẽ lỗi trên Railway/Render/Cloud Run vốn cấp cổng động qua biến môi trường `PORT`.
   - `reload=True` tiêu tốn CPU/RAM theo dõi file và không an toàn cho production.
6. **Không có Lifecycle Management / Graceful Shutdown và thiếu kiểm soát CORS/Validation:**
   - Không có `lifespan` hay xử lý tín hiệu `SIGTERM` để hoàn tất các request đang chạy dở trước khi tắt container; đầu vào `question` nhận qua query parameter thay vì JSON body có kiểm tra hợp lệ.

### Exercise 1.2: Kết quả chạy thử bản `develop`

Khởi chạy server `01-localhost-vs-production/develop/app.py` và gọi `POST /ask?question=Hello`:

```http
$ curl -sS -i -X POST "http://127.0.0.1:8000/ask?question=Hello"
HTTP/1.1 200 OK
date: Wed, 25 Nov 2026 07:38:33 GMT
server: uvicorn
content-length: 103
content-type: application/json

{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```

Kết quả chạy thử bản `production` (`GET /health` và `POST /ask` với JSON body):

```http
$ curl -sS -i "http://127.0.0.1:8000/health"
HTTP/1.1 200 OK
date: Wed, 25 Nov 2026 07:38:36 GMT
server: uvicorn
content-length: 129
content-type: application/json

{"status":"ok","uptime_seconds":1.6,"version":"1.0.0","environment":"development","timestamp":"2026-11-25T07:38:36.841935+00:00"}

$ curl -sS -i -X POST "http://127.0.0.1:8000/ask" -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 200 OK
date: Wed, 25 Nov 2026 07:38:36 GMT
server: uvicorn
content-length: 167
content-type: application/json

{"question":"Hello","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic.","model":"gpt-4o-mini"}
```

### Exercise 1.3: Bảng so sánh Develop vs Production

| Feature | Develop (`develop/app.py`) | Production (`production/app.py` + `config.py`) | Tại sao quan trọng? |
|---|---|---|---|
| **Config & Secrets** | Hardcode `OPENAI_API_KEY`, `DATABASE_URL`, `DEBUG=True`, `port=8000` ngay trong code | Đọc toàn bộ từ biến môi trường qua `Settings` (`os.getenv`), có `validate()` kiểm tra khi `ENVIRONMENT=production` | Tuân thủ 12-Factor App: tách biệt hoàn toàn cấu hình khỏi mã nguồn, đổi môi trường không cần build lại code và chống lộ lọt secret lên Git |
| **Network Binding & Port** | `host="localhost"`, `port=8000`, `reload=True` | `host=settings.host` (`0.0.0.0`), `port=settings.port` (`$PORT`), `reload` chỉ bật khi `DEBUG=true` | Container trong Docker/Cloud cần lắng nghe trên `0.0.0.0` và cổng động do nền tảng cấp phát (`PORT`), tắt file-watcher giúp ổn định hiệu năng |
| **Health & Readiness Checks** | Không có (`/health` và `/ready` đều vắng mặt) | Có `GET /health` (liveness + uptime) và `GET /ready` (readiness trả `503` khi chưa khởi tạo xong hoặc đang tắt) | Giúp orchestrator tự động khởi động lại container bị treo (`/health`) và giúp Load Balancer chỉ điều phối traffic vào instance đã sẵn sàng (`/ready`) |
| **Logging** | Dùng `print()`, thậm chí in thẳng `OPENAI_API_KEY` ra terminal | Dùng module `logging` xuất chuỗi JSON có cấu trúc (`time`, `level`, `msg`, `event`), tuyệt đối không ghi secret | Log JSON dễ dàng được index, lọc, cảnh báo trên hệ thống tập trung (Grafana Loki, ELK, Datadog) và đảm bảo an toàn bảo mật |
| **Lifecycle & Shutdown** | Tắt đột ngột khi nhận tín hiệu dừng, cắt ngang kết nối đang xử lý | Quản lý vòng đời qua `lifespan` (`startup` / `shutdown`) và lắng nghe `SIGTERM` để hạ cờ `is_ready = False` trước khi dừng | Tránh lỗi `502/504` cho người dùng cuối khi rolling update hoặc scale-in container đang xử lý request dở dang |
| **CORS & Input Validation** | Nhận query string thô, không cấu hình CORS | Có `CORSMiddleware` giới hạn `ALLOWED_ORIGINS` và kiểm tra JSON body (`422` khi thiếu `question`) | Ngăn truy cập trái phép từ trình duyệt khác domain và trả mã lỗi chuẩn HTTP khi client gửi sai định dạng |

---

## Part 2: Docker

### Exercise 2.1: Phân tích `02-docker/develop/Dockerfile`

1. **Base image là gì?**
   - `python:3.11` — bản phân phối Python 3.11 đầy đủ trên nền Debian (bao gồm cả trình biên dịch C/C++, header hệ thống, công cụ build...), có kích thước gốc rất lớn (> 1 GB).
2. **Working directory là gì?**
   - `/app` (đặt bằng chỉ thị `WORKDIR /app`). Mọi lệnh `COPY`, `RUN`, `CMD` phía sau đều thực thi tương đối từ thư mục `/app` bên trong container.
3. **Tại sao `COPY requirements.txt` đứng trước `COPY` source code?**
   - Để tận dụng cơ chế **Docker Layer Caching**: mỗi chỉ thị tạo một layer bất biến. Khi sửa code (`app.py`) mà không đổi `requirements.txt`, Docker tái sử dụng lại layer `RUN pip install -r requirements.txt` từ cache thay vì phải tải và cài lại toàn bộ thư viện từ đầu, rút ngắn thời gian build từ hàng chục giây xuống dưới 1 giây.
4. **`CMD` và `ENTRYPOINT` khác nhau thế nào?**
   - `ENTRYPOINT` định nghĩa chương trình thực thi chính của container (cố định; các đối số truyền thêm ở cuối lệnh `docker run <image> <args>` sẽ được nối vào sau `ENTRYPOINT`).
   - `CMD` cung cấp lệnh mặc định hoặc tham số mặc định cho `ENTRYPOINT`, và dễ dàng bị **ghi đè hoàn toàn** khi truyền lệnh khác vào `docker run <image> <new_command>` (ví dụ `docker run -it my-agent:develop /bin/bash`).

### Exercise 2.2: Build và chạy `my-agent:develop`

Build từ gốc repository và gọi thử container:

```http
$ docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
$ docker run -d --rm --name test-dev-agent -p 8000:8000 my-agent:develop
$ curl -sS -i -X POST "http://127.0.0.1:8000/ask?question=What%20is%20Docker%3F"
HTTP/1.1 200 OK
date: Wed, 25 Nov 2026 07:50:17 GMT
server: uvicorn
content-length: 103
content-type: application/json

{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}
```

### Exercise 2.3: Multi-stage build và so sánh kích thước image

- **Stage 1 (`builder` — `FROM python:3.11-slim AS builder`):** Cài đặt các gói hệ thống phục vụ biên dịch (`gcc`, `libpq-dev`) và cài đặt các thư viện Python vào `/root/.local` (`pip install --no-cache-dir --user -r requirements.txt`). Toàn bộ compiler và build tools nằm lại ở stage này, không đi vào image cuối.
- **Stage 2 (`runtime` — `FROM python:3.11-slim AS runtime`):** Xuất phát từ `python:3.11-slim` sạch, tạo tài khoản non-root `appuser`, chỉ `COPY --from=builder /root/.local /home/appuser/.local` cùng mã nguồn cần chạy (`main.py`, `utils/mock_llm.py`), khai báo `HEALTHCHECK` và khởi chạy bằng `uvicorn` với 2 workers.
- **Tại sao image nhỏ hơn và an toàn hơn?** Vì dùng nền `slim` thay vì bản Debian đầy đủ, đồng thời loại bỏ hoàn toàn `gcc`, `libpq-dev`, apt cache và pip cache khỏi runtime image (vừa giảm dung lượng vừa thu hẹp bề mặt tấn công).

Kết quả đo thực tế bằng `docker images` và `docker image inspect`:

```text
$ docker images --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}" my-agent
REPOSITORY   TAG        SIZE
my-agent     advanced   240MB
my-agent     develop    1.67GB
```

- **Develop (`my-agent:develop`):** `1.67 GB` (`1,590.5 MiB` / `1,667.8 MB`)
- **Production (`my-agent:advanced`):** `240 MB` (`228.7 MiB` / `239.8 MB`)
- **Chênh lệch (mức giảm dung lượng):** giảm **`85.6%`** (nhỏ hơn gần 7 lần).

### Exercise 2.4: Docker Compose Stack (`02-docker/production/docker-compose.yml`)

**Sơ đồ kiến trúc các service và luồng giao tiếp:**

```text
                        Mạng ngoài (Host port 80 / 443)
                                      │
                                      ▼
                    ┌───────────────────────────────────┐
                    │  nginx (nginx:alpine)             │
                    │  Reverse Proxy + Rate Limit 10r/s │
                    └─────────────────┬─────────────────┘
                                      │ HTTP proxy_pass (internal network)
                                      ▼
                    ┌───────────────────────────────────┐
                    │  agent (FastAPI, port 8000/tcp)   │
                    │  2 uvicorn workers, non-root      │
                    └────────┬─────────────────┬────────┘
          REDIS_URL (:6379)  │                 │ QDRANT_URL (:6333)
                             ▼                 ▼
               ┌──────────────────┐     ┌───────────────────────┐
               │ redis:7-alpine   │     │ qdrant/qdrant:v1.9.0  │
               │ Session & Cache  │     │ Vector DB cho RAG     │
               └──────────────────┘     └───────────────────────┘
                         (Mạng nội bộ bridge: internal)
```

- **4 services khởi chạy:** `nginx` (cổng vào duy nhất mở port `80`/`443` ra host), `agent` (ứng dụng FastAPI không mở port trực tiếp ra ngoài, chờ `redis` và `qdrant` đạt trạng thái `service_healthy` mới chạy), `redis` (lưu cache/rate-limit kèm volume `redis_data`), và `qdrant` (vector database kèm volume `qdrant_data`).

**Kết quả kiểm thử thực tế qua Nginx (`port 80`):**

```http
$ curl -sS -i "http://127.0.0.1/health"
HTTP/1.1 200 OK
Server: nginx
Date: Wed, 25 Nov 2026 07:50:50 GMT
Content-Type: application/json
Content-Length: 95
Connection: keep-alive
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block

{"status":"ok","uptime_seconds":1.6,"version":"2.0.0","timestamp":"2026-11-25T07:50:50.801029"}

$ curl -sS -i -X POST "http://127.0.0.1/ask" -H "Content-Type: application/json" -d '{"question": "Explain microservices"}'
HTTP/1.1 200 OK
Server: nginx
Date: Wed, 25 Nov 2026 07:53:47 GMT
Content-Type: application/json
Content-Length: 103
Connection: keep-alive
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block

{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```

---

## Part 3: Cloud Deployment

### Exercise 3.1: Triển khai Agent Part 6 lên Cloud

- **Nền tảng chính:** Render (Blueprint `k5-day14-agent` từ [`render.yaml`](render.yaml), gồm Web Service `k5-day14-production-agent` chạy multi-stage Docker và Key Value Redis `k5-day14-redis`).
- **Public URL:** `https://k5-day14-production-agent.onrender.com`
- **Kết quả tự kiểm tra 4 lệnh CP6:** `GET /health` → **200**, `GET /ready` → **200** (`redis: connected`), `POST /ask` (không gửi `X-API-Key`) → **401**, `POST /ask` (có `X-API-Key` hợp lệ) → **200**.
- Chi tiết lệnh test, biến môi trường và ảnh bằng chứng (`dashboard.png`, `running.png`, `test.png`) xem trong [DEPLOYMENT.md](DEPLOYMENT.md).

### Exercise 3.2: So sánh `railway.toml` và `render.yaml`

| Tiêu chí | `railway.toml` (Railway) | `render.yaml` (Render Blueprint) | Vì sao có sự khác biệt? |
|---|---|---|---|
| **Định dạng & Phạm vi** | File TOML ngắn gọn, cấu hình **một service đơn lẻ** (`[build]`, `[deploy]`) trong thư mục hiện tại | File YAML theo mô hình **Infrastructure as Code (Blueprint)**, khai báo đồng thời **nhiều tài nguyên** (`type: web`, `type: redis`, persistent `disk`) trong cùng một file | Railway quản lý đa dịch vụ (App, Redis, Postgres) trực quan ở cấp Project/Canvas và nối biến tham chiếu động; Render thiết kế Blueprint để đồng bộ toàn bộ kiến trúc hệ thống từ Git |
| **Cách Build** | Đặt `builder = "DOCKERFILE"` (hoặc `"NIXPACKS"` tự nhận diện ngôn ngữ) | Đặt `runtime: docker` (dùng `Dockerfile`) hoặc `runtime: python` kèm `buildCommand` và `startCommand` tường minh | Railway ưu tiên zero-config auto-detection qua Nixpacks/Dockerfile, trong khi Render tách bạch rõ loại runtime, region (`singapore`) và gói tài nguyên (`plan: free`) |
| **Quản lý biến môi trường & Secrets** | Không khai báo danh sách biến trong `railway.toml`; mọi biến và secret đặt qua Railway Dashboard hoặc CLI (`railway variables set ...`) | Khai báo trực tiếp danh sách `envVars` ngay trong `render.yaml`; với secret dùng `generateValue: true` (tự sinh ngẫu nhiên) hoặc `sync: false` (nhập tay trên Dashboard, không lưu giá trị vào Git) | Giúp Render tái lập môi trường mới từ repo mà vẫn đảm bảo nguyên tắc không lưu plaintext secret trong Git |
| **Health Check & Restart** | `healthcheckPath = "/health"`, `healthcheckTimeout = 30`, hỗ trợ cấu hình `restartPolicyType = "ON_FAILURE"` và `restartPolicyMaxRetries` | `healthCheckPath: /health` kết hợp `autoDeploy: true` khi có commit mới trên nhánh Git | Railway cho phép tinh chỉnh chính sách thử lại khi container crash ngay trong file cấu hình deploy |

### Exercise 3.3: Phân tích CI/CD Pipeline trên GCP Cloud Run (`cloudbuild.yaml` & `service.yaml`)

Pipeline CI/CD trong `03-cloud-deployment/production-cloud-run/` tự động hoá quy trình đưa code từ Git lên môi trường serverless managed qua 4 bước tuần tự (`waitFor`):
1. **Test (`id: test`):** Dùng container `python:3.11-slim` cài dependencies và chạy `pytest tests/ -v`; nếu bất kỳ unit test nào lỗi, pipeline dừng ngay và không build image hỏng.
2. **Build (`id: build`):** Dùng `gcr.io/cloud-builders/docker` build image gắn kép 2 tag (`:$COMMIT_SHA` để truy vết chính xác phiên bản commit và `:latest`), tận dụng `--cache-from` để tăng tốc build.
3. **Push (`id: push`):** Đẩy toàn bộ image tags vừa build lên Google Container Registry (`gcr.io/$PROJECT_ID/ai-agent`).
4. **Deploy (`id: deploy` + `service.yaml`):** Dùng `gcloud run deploy` cập nhật revision mới trên Cloud Run (`asia-southeast1`) với cấu hình production chuẩn Knative (`service.yaml`): giữ `minScale: 1` chống cold start, giới hạn `maxScale: 10` và `containerConcurrency: 80`, cấp phát `1 CPU / 512Mi RAM`, nạp secret an toàn từ **Google Secret Manager** (`secretKeyRef` cho `OPENAI_API_KEY`, `AGENT_API_KEY`), và giám sát bằng `startupProbe` (`/ready`) + `livenessProbe` (`/health`).

---

## Part 4: API Security

### Exercise 4.1: API Key Authentication (`04-api-gateway/develop/app.py`)

- **API key được kiểm tra ở đâu?** Trong dependency `verify_api_key(api_key: str = Security(api_key_header))` (dòng 39–54), đọc header `X-API-Key` với `auto_error=False` và được gắn vào endpoint `POST /ask` qua `Depends(verify_api_key)` (dòng 70), trong khi `/health` và `/` vẫn để public cho nền tảng giám sát.
- **Điều gì xảy ra nếu thiếu hoặc sai key?** Nếu thiếu header `X-API-Key`, hàm trả `HTTP 401 Unauthorized`; nếu gửi sai giá trị so với `AGENT_API_KEY`, bản mẫu trả `HTTP 403 Forbidden` (lưu ý ở hợp đồng Part 6 thì cả thiếu lẫn sai đều chuẩn hoá về `401`).
- **Làm sao để xoay vòng (rotate) API key không gây gián đoạn?** Đọc danh sách key hợp lệ từ biến môi trường (ví dụ `AGENT_API_KEYS=new_key,old_key`), triển khai để server chấp nhận đồng thời cả key mới và key cũ trong thời gian chuyển giao, cập nhật các client sang `new_key`, sau đó gỡ bỏ `old_key` khỏi biến môi trường và dùng `secrets.compare_digest` để chống timing attack.

**Kết quả test thực tế (`curl -i`):**

```http
# 1. Không gửi X-API-Key → 401 Unauthorized
$ curl -sS -i -X POST http://127.0.0.1:8000/ask -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 401 Unauthorized
date: Wed, 25 Nov 2026 07:51:19 GMT
server: uvicorn
content-length: 67
content-type: application/json

{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

# 2. Có X-API-Key đúng → 200 OK
$ curl -sS -i -X POST http://127.0.0.1:8000/ask -H "X-API-Key: secret-key-123" -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 200 OK
date: Wed, 25 Nov 2026 07:51:19 GMT
server: uvicorn
content-length: 114
content-type: application/json

{"question":"Hello","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
```

### Exercise 4.2 & 4.3: JWT Authentication & Rate Limiting (`04-api-gateway/production/`)

- **Luồng JWT (`auth.py`):** Client gửi `username`/`password` tới `POST /auth/token` → server xác thực và ký token HS256 chứa `sub` (username), `role` (`user`/`admin`), `iat` và `exp` (60 phút). Ở các request sau, `verify_token` kiểm tra chữ ký số và hạn dùng của Bearer token hoàn toàn stateless mà không cần truy vấn DB mỗi lần.
- **Thuật toán Rate Limiting (`rate_limiter.py`):** Sử dụng **Sliding Window Log/Counter** lưu danh sách mốc thời gian request trong cửa sổ trượt 60 giây (`now - 60s`), loại bỏ các timestamp cũ trước khi kiểm tra số lượng hiện tại.
- **Giới hạn mặc định & phân quyền Admin:** Tài khoản thường (`role == "user"`, ví dụ `student`) dùng `rate_limiter_user` giới hạn **10 requests/phút**; tài khoản quản trị (`role == "admin"`, ví dụ `teacher`) được route sang `rate_limiter_admin` với ngưỡng **100 requests/phút** (hoặc trong hệ thống thực tế có thể bỏ qua kiểm tra cho role internal/admin).
- **Vì sao cần cả Rate Limit lẫn Cost Guard?** Rate limit chặn tốc độ gọi bất thường trong thời gian ngắn (chống spam/DDoS làm nghẽn hệ thống), nhưng kẻ tấn công hoặc người dùng vẫn có thể gửi các prompt cực dài ở tốc độ chậm dưới ngưỡng 10 req/phút suốt cả ngày gây tốn hàng trăm USD tiền LLM — Cost Guard theo dõi tổng chi phí cộng dồn theo token để khóa trần ngân sách.

**Kết quả test thực tế 401 / 200 / 429 (`curl -i`, đã che JWT token):**

```http
# 1. Không gửi Bearer token → 401 Unauthorized
$ curl -sS -i -X POST http://127.0.0.1:8000/ask -H "Content-Type: application/json" -d '{"question": "Explain JWT"}'
HTTP/1.1 401 Unauthorized
date: Wed, 25 Nov 2026 07:51:21 GMT
server: uvicorn
www-authenticate: Bearer
content-length: 76
content-type: application/json
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin

{"detail":"Authentication required. Include: Authorization: Bearer <token>"}

# 2. Đăng nhập lấy JWT với tài khoản student / demo123 (token đã được che)
$ curl -sS -X POST http://127.0.0.1:8000/auth/token -H "Content-Type: application/json" -d '{"username": "student", "password": "demo123"}'
{"access_token":"<REDACTED_JWT_TOKEN>","token_type":"bearer","expires_in_minutes":60,"hint":"Include in header: Authorization: Bearer <REDACTED_PREFIX>..."}

# 3. Gọi /ask hợp lệ với Bearer token (Request 1 → 200 OK; Request 2..10 → 200 OK)
$ curl -sS -i -X POST http://127.0.0.1:8000/ask -H "Authorization: Bearer <REDACTED_JWT_TOKEN>" -H "Content-Type: application/json" -d '{"question": "Explain JWT"}'
HTTP/1.1 200 OK
date: Wed, 25 Nov 2026 07:51:21 GMT
server: uvicorn
content-length: 215
content-type: application/json
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin

{"question":"Explain JWT","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic.","usage":{"requests_remaining":9,"budget_remaining_usd":2.1e-05}}

# 4. Vòng lặp vượt ngưỡng 10 req/phút: ở Request thứ 11 → 429 Too Many Requests
$ curl -sS -i -X POST http://127.0.0.1:8000/ask -H "Authorization: Bearer <REDACTED_JWT_TOKEN>" -H "Content-Type: application/json" -d '{"question": "Test 11"}'
HTTP/1.1 429 Too Many Requests
date: Wed, 25 Nov 2026 07:51:22 GMT
server: uvicorn
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
x-ratelimit-reset: 1795593143
retry-after: 59
content-length: 98
content-type: application/json
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin

{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
```

### Exercise 4.4: Thiết kế & Cài đặt Cost Guard với Redis

Trong `04-api-gateway/production/cost_guard.py`, bản demo lưu chi phí trong dictionary `_records` (in-memory). Khi đưa lên production đa worker / đa instance (như ở Part 6), cách tiếp cận chuẩn với Redis là:
1. **Phân tách key theo chu kỳ thời gian:** Dùng key `cost:daily:{YYYY-MM-DD}` (cho ngân sách ngày `DAILY_BUDGET_USD`) hoặc `budget:{user_id}:{YYYY-MM}` (cho ngân sách tháng `MONTHLY_BUDGET_USD`).
2. **Kiểm tra trước khi gọi LLM (`check_budget`):** Đọc tổng tiền hiện tại từ Redis (`float(r.get(key) or 0.0)`). Nếu `spent >= budget_usd` thì từ chối ngay bằng `HTTPException(status_code=402, detail="Budget exceeded")` trước khi phát sinh thêm chi phí gọi API LLM.
3. **Cộng dồn nguyên tử sau khi gọi LLM (`record_cost`):** Tính `cost = (input_tokens / 1000) * PRICE_INPUT_PER_1K + (output_tokens / 1000) * PRICE_OUTPUT_PER_1K`, dùng lệnh nguyên tử `INCRBYFLOAT` của Redis để không bị race condition khi nhiều request hoàn thành cùng lúc, và đặt `EXPIRE` (ví dụ 48 giờ cho key theo ngày hoặc 32 ngày cho key theo tháng) để Redis tự dọn bộ nhớ.

---

## Part 5: Scaling & Reliability

### Exercise 5.1 & 5.2: Health Check vs Readiness Check và Graceful Shutdown

- **Phân biệt Liveness (`GET /health`) và Readiness (`GET /ready`):**
  - `GET /health` (**Liveness probe**) chỉ kiểm tra bản thân tiến trình Python/FastAPI có còn phản hồi hay đã bị treo/deadlock. Nó **phải trả `200`** ngay cả khi Redis tạm thời mất kết nối; nếu `/health` trả lỗi khi Redis sập, orchestrator sẽ liên tục restart toàn bộ dàn container agent một cách vô ích (cascading restart loop) dù lỗi nằm ở Redis.
  - `GET /ready` (**Readiness probe**) kiểm tra instance đã sẵn sàng phục vụ request thật chưa (bao gồm `redis.ping()`). Khi mất kết nối Redis hoặc đang trong quá trình tắt, `/ready` trả **`503 Service Unavailable`** để Load Balancer tạm ngưng gửi request mới vào instance đó mà không giết container.
- **Graceful Shutdown (`SIGTERM`):** Khi scale-in hoặc deploy bản mới, Docker/Kubernetes gửi tín hiệu `SIGTERM` trước (sau thời gian chờ mặc định 10s mới gửi `SIGKILL`). Tiến trình uvicorn (chạy dưới dạng **PID 1** nhờ `exec`) sẽ đóng socket nhận kết nối mới, chờ các request in-flight xử lý xong và trả `200 OK`, chạy khối dọn dẹp sau `yield` trong `lifespan`, rồi thoát êm với exit code `0`. Nếu tự đăng ký `signal.signal(signal.SIGTERM, ...)` mà không gọi lại handler gốc của uvicorn thì tiến trình sẽ phớt lờ tín hiệu tắt và bị `SIGKILL` (exit code `137`).

### Exercise 5.3: Tại sao thiết kế Stateless (lưu state ở Redis) là bắt buộc khi Scale?

Nếu lưu lịch sử hội thoại, bộ đếm rate limit hoặc chi phí trong biến toàn cục trên RAM (`conversation_history = {}`), mỗi container instance (và thậm chí mỗi `--workers` bên trong cùng 1 container) sở hữu không gian bộ nhớ tách biệt. Khi Nginx phân phối theo cơ chế round-robin:
- Request 1 của người dùng vào `agent-1` → lưu ngữ cảnh trên RAM của `agent-1`.
- Request 2 của cùng người dùng vào `agent-2` → RAM của `agent-2` trống rỗng, agent "quên" toàn bộ hội thoại trước đó (hoặc cho phép người dùng vượt gấp `N` lần ngưỡng rate limit khi có `N` instance).
- Nếu 1 container restart hoặc scale-down, toàn bộ dữ liệu trong RAM mất sạch. Chuyển toàn bộ state sang **Redis** biến mọi instance agent thành các worker thuần không trạng thái (stateless), có thể thêm/bớt số lượng bản sao tức thì.

### Exercise 5.4 & 5.5: Kết quả chạy Load Balancing 3 Replicas & `test_stateless.py`

Khởi chạy cụm `docker compose -p k5-day14-scaling up -d --build --scale agent=3` trong `05-scaling-reliability/production/` (Nginx lắng nghe cổng `8080`, cân bằng tải sang 3 container `agent-1`, `agent-2`, `agent-3` cùng dùng chung `redis:7-alpine`):

```text
NAME                       IMAGE                    SERVICE   STATUS                    PORTS
k5-day14-scaling-agent-1   k5-day14-scaling-agent   agent     Up 10 seconds (healthy)   8000/tcp
k5-day14-scaling-agent-2   k5-day14-scaling-agent   agent     Up 10 seconds (healthy)   8000/tcp
k5-day14-scaling-agent-3   k5-day14-scaling-agent   agent     Up 10 seconds (healthy)   8000/tcp
k5-day14-scaling-nginx-1   nginx:alpine             nginx     Up 10 seconds             0.0.0.0:8080->80/tcp
k5-day14-scaling-redis-1   redis:7-alpine           redis     Up 21 seconds (healthy)   6379/tcp
```

Kết quả chạy `python test_stateless.py`:

```text
============================================================
Stateless Scaling Demo
============================================================

Session ID: 630172c9-8fd2-4f31-9378-0ec1d4ee5c33

Request 1: [instance-45071c]
  Q: What is Docker?
  A: Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!...

Request 2: [instance-8d4c3c]
  Q: Why do we need containers?
  A: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé....

Request 3: [instance-45071c]
  Q: What is Kubernetes?
  A: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé....

Request 4: [instance-b0ffbe]
  Q: How does load balancing work?
  A: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé....

Request 5: [instance-8d4c3c]
  Q: What is Redis used for?
  A: Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ O...

------------------------------------------------------------
Total requests: 5
Instances used: {'instance-b0ffbe', 'instance-8d4c3c', 'instance-45071c'}
✅ All requests served despite different instances!

--- Conversation History ---
Total messages: 10
  [user]: What is Docker?...
  [assistant]: Container là cách đóng gói app để chạy ở mọi nơi. Build once...
  [user]: Why do we need containers?...
  [assistant]: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đ...
  [user]: What is Kubernetes?...
  [assistant]: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đ...
  [user]: How does load balancing work?...
  [assistant]: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đ...
  [user]: What is Redis used for?...
  [assistant]: Đây là câu trả lời từ AI agent (mock). Trong production, đây...

✅ Session history preserved across all instances via Redis!
```

**Giải thích kết quả:** 5 câu hỏi liên tiếp trong cùng `session_id` được Nginx điều phối sang cả **3 container khác nhau** (`instance-45071c`, `instance-8d4c3c`, `instance-b0ffbe`). Khi gọi `GET /chat/{session_id}/history`, hệ thống vẫn trả về đầy đủ **10 tin nhắn** (5 cặp hỏi–đáp theo đúng thứ tự thời gian) do trạng thái phiên được đọc/ghi tập trung tại Redis (`session:{session_id}`).

---

## Part 6: Final Project — Kết Quả `check_production_ready.py`

Chạy kiểm tra đầy đủ trong môi trường WSL2 (`os.name == "posix"`) kết hợp Docker Desktop (`v29.9.2`):

```text
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
  Result: 12/12 tiêu chí đạt · 43/43 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
================================================================
```

*(Chi tiết nổi bật từ bộ kiểm tra: Docker image đạt **238 MB**, rate limit chặn `429` chính xác sau 5 request và giữ nguyên trạng thái trong Redis sau khi restart process, cost guard trả `402` ngay khi vượt ngân sách, toàn bộ log xuất chuẩn JSON 1 dòng, và `docker stop` thoát mã `0` trong `0.8s`).*

---

## AI Log (Khai báo sử dụng AI theo `RULES.md`)

1. **Tổng hợp yêu cầu & lập lộ trình thực hiện lab:**
   - **Nội dung hỏi/yêu cầu:** Đọc tài liệu dự án (`README.md` lưu ý riêng lớp K5, `RULES.md`, `CHECKPOINTS.md`, `RUBRIC.md`, `SUBMISSION.md`, `CODE_LAB.md`) để lập danh sách công việc theo đúng thứ tự Checkpoint CP0 → CP8.
   - **Nội dung nhận được:** Bản checklist chi tiết cho từng Part và các lưu ý kỹ thuật quan trọng trên Windows (chạy `check_production_ready.py` trong WSL2 `posix`, dùng `-p` riêng cho từng stack Docker Compose, dùng `--no-deps` khi chạy Locust headless để không ghi đè số replica).
   - **Tự kiểm tra & xác minh:** Đối chiếu từng mục với `RUBRIC.md` và `SUBMISSION.md`, kiểm tra trực tiếp trên máy thật.

2. **Hỗ trợ hoàn thiện mã nguồn Part 6 (`06-lab-complete/`):**
   - **Nội dung hỏi/yêu cầu:** Gợi ý triển khai các module khung TODO: đọc cấu hình 12-Factor (`app/config.py`), kết nối Redis có timeout ngắn (`app/redis_client.py`), xác thực `X-API-Key` bằng `secrets.compare_digest` (`app/auth.py`), sliding-window rate limiter nguyên tử bằng Lua script trên Redis Sorted Set (`app/rate_limiter.py`), kiểm soát ngân sách `INCRBYFLOAT` (`app/cost_guard.py`), `JsonFormatter` + `lifespan` graceful shutdown (`app/main.py`), và multi-stage `Dockerfile` (`python:3.11-slim`, user non-root `appuser`, `exec uvicorn` làm PID 1).
   - **Nội dung nhận được:** Mã nguồn hoàn chỉnh cho các file trong `06-lab-complete/` mà không chạm tới `check_production_ready.py`.
   - **Tự kiểm tra & xác minh:** Chạy trực tiếp `python check_production_ready.py` chế độ đầy đủ trong WSL2 kết nối Docker Desktop; kiểm tra toàn bộ **43/43 checks** và xác nhận đạt **`PASS 12/12`** (image `238 MB`, rate limit giữ state sau restart, cost guard trả `402`, `docker stop` thoát mã `0` trong `0.8s`).

3. **Hỗ trợ gỡ lỗi môi trường Part 7 (`production/Dockerfile`) & tổng hợp cấu trúc báo cáo:**
   - **Nội dung hỏi/yêu cầu:** Phân tích lỗi container `agent` trong `06-lab-complete/benchmark-observability/production/` bị `ModuleNotFoundError: No module named 'uvicorn'` khi chạy dưới quyền non-root `agent` (home đặt tại `/app`), bổ sung 2 mục kiến thức thiếu (`Kubernetes HPA`, `JWT`) vào `KNOWLEDGE_BASE`, và trình bày bảng biểu cho `MISSION_ANSWERS.md` / `BENCHMARK_REPORT.md`.
   - **Nội dung nhận được:** Phát hiện thiếu biến `ENV PYTHONUSERBASE=/home/agent/.local` trong `production/Dockerfile`; sửa lại để container chạy `healthy` (`HTTP 200`), bổ sung 2 entry vào `mock_llm.py` và tạo workflow `.github/workflows/eval.yml`.
   - **Tự kiểm tra & xác minh:** Toàn bộ con số trong `MISSION_ANSWERS.md` và `BENCHMARK_REPORT.md` (dung lượng image `1.67 GB` vs `240 MB`, các bảng RPS/p50/p95/p99, accuracy `4.35%` → `91.30%` → `100.0%`, số liệu Locust `scale_1`/`scale_3`, `trace_id` và thời gian alert firing `45.1s` / `90.2s` / `140.4s`) đều được đo trực tiếp từ lệnh chạy trên máy và kiểm tra khớp 100% với các file trong `reports/`, `benchmark-results/` và `screenshots/`.
