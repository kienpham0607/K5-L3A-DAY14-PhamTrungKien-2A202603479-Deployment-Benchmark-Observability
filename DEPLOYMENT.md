# Deployment Information — Day 14

## Public URL
`https://k5-day14-production-agent.onrender.com`

## Platform
Render (Blueprint `k5-day14-agent` từ [`render.yaml`](render.yaml)) — triển khai trực tiếp thư mục [`06-lab-complete/`](06-lab-complete/) (Multi-stage Docker `k5-day14-production-agent` + Key Value Redis `k5-day14-redis`, gói Free)

## Test Commands (4 lệnh chuẩn CP6)

Đặt biến `BASE` và `AGENT_API_KEY` trong terminal rồi kiểm tra:

```bash
export BASE="https://k5-day14-production-agent.onrender.com"
export AGENT_API_KEY="<YOUR-SECRET-KEY-SET-ON-RENDER>"

# 1. Liveness probe → 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"

# 2. Readiness probe (kết nối Redis thành công) → 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"

# 3. Gọi /ask không có X-API-Key → 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' \
  -d '{"question":"Hello"}'

# 4. Gọi /ask có X-API-Key hợp lệ → 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' \
  -H "X-API-Key: $AGENT_API_KEY" \
  -d '{"user_id":"test","question":"Hello"}'
```

Hoặc kiểm tra bằng lệnh có nội dung JSON:

```bash
curl -sS "$BASE/health"
# Expected: {"status":"ok","environment":"production","uptime_seconds":...}

curl -sS -X POST "$BASE/ask" \
  -H "X-API-Key: $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "question": "What is Docker?"}'
```

## Environment Variables Set (trên Cloud Dashboard, không lưu secret trong Git)
- `PORT` (tự động cấp bởi nền tảng hoặc `8000`)
- `ENVIRONMENT` (`production`)
- `LOG_LEVEL` (`INFO`)
- `REDIS_URL` (tham chiếu tới Redis service trên nền tảng, ví dụ `${{Redis.REDIS_URL}}`)
- `AGENT_API_KEY` (khóa bí mật tạo ngẫu nhiên trên Dashboard/CLI)
- `RATE_LIMIT_PER_MINUTE` (`10`)
- `DAILY_BUDGET_USD` (`10.0`)

## Screenshots
- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
