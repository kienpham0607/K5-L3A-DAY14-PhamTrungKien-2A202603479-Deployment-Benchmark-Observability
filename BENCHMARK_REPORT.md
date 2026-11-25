# Benchmark & Observability Report — Day 14

> Mọi con số trong báo cáo này được trích xuất trực tiếp từ các file kết quả chạy thực tế trong [`reports/`](reports/), [`benchmark-results/`](benchmark-results/) và các ảnh chụp màn hình trong [`screenshots/`](screenshots/).

**Họ tên:** Phạm Trung Kiên (MSSV: 2A202603479)
**Ngày chạy:** 2026-11-25
**Môi trường:** Windows 11 + WSL2 Ubuntu (Linux kernel 6.6.87.2-microsoft-standard-WSL2, Python 3.12 / 3.14), Docker Desktop v29.9.2 & Docker Compose v5.6.1

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | `< 500 ms` | Với ứng dụng hội thoại AI tương tác trực tiếp, 95% người dùng nhận câu trả lời dưới nửa giây mang lại cảm giác phản hồi tức thì; chỉ cho phép tối đa 5% request rơi vào vùng tail latency của upstream LLM |
| Error rate `/ask` | `< 2.0 %` | Upstream LLM API thực tế luôn có tỷ lệ lỗi tạm thời (`429`/`503` ~1%); đặt SLO `< 2%` cho phép error budget `2%` hợp lý trước khi cảnh báo vận hành (`> 5%` kéo dài 1 phút) |
| Accuracy trên golden dataset | `≥ 85 %` (mục tiêu sau tối ưu KB: `100 %`, `0` regression) | Ngưỡng `85%` chặn các bản thay đổi prompt/RAG làm tụt chất lượng nghiêm trọng trên CI, kết hợp điều kiện **không regression** so với baseline để không làm hỏng các câu hỏi vốn đang trả lời đúng |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

*(Cấu hình chạy: 300 requests/lần gọi tới `POST /ask` của Agent `v2`, file gốc lưu tại [`reports/load_v2_c1.json`](reports/load_v2_c1.json) … [`reports/load_v2_c100.json`](reports/load_v2_c100.json)).*

### 2.1 Concurrency vs latency (agent v2)

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---:|---:|---:|---:|---:|---|
| 1 | 3.99 | 190.7 | 223.3 | 1707.7 | 2.00% (`6/300`) | ✅ PASS |
| 10 | 37.00 | 191.8 | 236.8 | 1698.1 | 0.33% (`1/300`) | ✅ PASS |
| 50 | 100.84 | 199.6 | 309.7 | 1702.1 | 1.00% (`3/300`) | ✅ PASS |
| 100 | 80.56 | 444.0 | 2899.6 | 3286.9 | 2.33% (`7/300`) | ❌ FAIL |

**Nhận xét:** RPS **không** tăng tuyến tính mãi theo concurrency:
- Từ `concurrency = 1` lên `10`, RPS tăng gần tuyến tính (`3.99` → `37.00 req/s`, gấp `9.3x`) do event loop `asyncio` tận dụng tốt thời gian chờ I/O của bước retrieval + gọi LLM mà hầu như chưa bị nghẽn (`p95` chỉ nhích nhẹ từ `223.3 ms` lên `236.8 ms`).
- Từ `10` lên `50` (`5x` concurrency), RPS chỉ tăng `2.7x` lên `100.84 req/s` và `p95` bắt đầu tăng lên `309.7 ms` do overhead lập lịch coroutine, xử lý JSON/metrics trên 1 tiến trình Python đơn nhân.
- Ở `concurrency = 100`, hệ thống rơi vào vùng bão hoà hàng đợi (queueing/thrashing): thông lượng giảm ngược xuống `80.56 req/s`, `p50` vọt lên `444.0 ms` và `p95` tăng vọt gần 10 lần lên **`2899.6 ms`**, vi phạm ngưỡng SLO `500 ms`.

### 2.2 Tail latency

*(Chạy ở `concurrency = 20`, `300 requests`, đối chiếu [`reports/load_v2_slow_0.json`](reports/load_v2_slow_0.json), [`reports/load_v2_slow_0.03.json`](reports/load_v2_slow_0.03.json), [`reports/load_v2_slow_0.1.json`](reports/load_v2_slow_0.1.json)).*

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---:|---:|---:|
| 0 | 192.4 | 223.4 | 247.7 |
| 0.03 (mặc định) | 217.9 | 223.2 | 1698.5 |
| 0.1 | 332.4 | 1685.2 | 1713.2 |

**Nhận xét:**
- **`p99` (và tiếp theo là `p95` khi tỷ lệ chậm vượt 5%) là chỉ số nhạy nhất với request chậm.** Khi `MOCK_SLOW_RATE` tăng từ `0` lên `0.03` (3% request chậm thêm ~1.5s), `avg` chỉ tăng rất nhẹ `+25.5 ms` (`192.4` → `217.9 ms`) và `p95` giữ nguyên `223.2 ms`, nhưng **`p99` nhảy vọt gấp ~6.9 lần lên `1698.5 ms`**. Khi tăng lên `0.1` (10% request chậm > ngưỡng 5% của p95), cả **`p95` cũng vọt lên `1685.2 ms`** làm trượt SLO, trong khi `avg` vẫn chỉ là `332.4 ms` (`< 500 ms`!).
- **Vì sao SLO không bao giờ nên đặt theo `average`?** Trung bình cộng bị pha loãng bởi 90–97% request nhanh nên che giấu hoàn toàn nhóm khách hàng gặp trải nghiệm tệ nhất (chờ gần 2 giây). Đặt SLO theo percentile (`p95`/`p99`) bảo vệ trực tiếp trải nghiệm thực tế của phần đuôi phân phối (tail latency).

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

*(Đối chiếu [`reports/eval_v1.json`](reports/eval_v1.json), [`reports/eval_v2.json`](reports/eval_v2.json), [`reports/eval_v2_fixed.json`](reports/eval_v2_fixed.json) trên bộ 23 câu hỏi `golden_dataset.jsonl`).*

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---:|---:|---:|
| Accuracy | 4.35% (`1/23`) | 91.30% (`21/23`) | **100.00% (`23/23`)** |
| Avg tokens / câu | 56.5 | 109.1 | 113.7 |
| Tổng cost (USD) | \$0.000396 | \$0.000762 | \$0.000790 |
| Cost / câu đúng (USD) | \$0.00039615 | \$0.00003627 | **\$0.00003436** |
| Quality gate | ❌ FAIL | ✅ PASS (vs v1, min 80%) | ✅ PASS (vs v2, min 100%, 0 regression) |

**Những câu v2 trả lời sai ban đầu và cách bạn sửa:**

| ID | Keyword bị thiếu | Bạn đã sửa gì |
|---|---|---|
| `security-02` | `token`, `hết hạn`, `chữ ký` (score `0.0`) | Bổ sung tài liệu về phân biệt API Key và JWT (`["jwt"]` — nêu rõ JWT là token có chữ ký số, chứa thông tin user và thời điểm hết hạn) vào `KNOWLEDGE_BASE` trong `utils/mock_llm.py` |
| `scaling-03` | `cpu`, `memory`, `custom metrics` (score `0.0`) | Bổ sung tài liệu về Kubernetes HPA (`["hpa", "kubernetes", "autoscal"]` — nêu rõ cơ chế scale pod dựa trên CPU, memory và custom metrics) vào `KNOWLEDGE_BASE` trong `utils/mock_llm.py` |

**Cơ chế Quality Gate trong CI ([`.github/workflows/eval.yml`](.github/workflows/eval.yml)):**
- Script `eval/run_eval.py` kết thúc bằng `raise SystemExit(0 if gate_ok else 1)` với điều kiện `gate_ok = (accuracy >= min_accuracy) and (not regressions)`. Trong GitHub Actions trên sự kiện `pull_request`, bước chạy `python eval/run_eval.py --min-accuracy 0.85` (hoặc kèm `--baseline`) sẽ trả **exit code `1`** ngay khi độ chính xác tụt dưới ngưỡng hoặc phát sinh bất kỳ câu nào bị regression, làm job CI fail đỏ và chặn nút Merge PR.

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:**
- Agent `v2` (có RAG retrieval) tăng lượng token trung bình mỗi câu lên khoảng **2 lần** (`56.5` → `113.7 tokens`) do nhúng thêm ngữ cảnh tài liệu vào prompt, khiến tổng chi phí cho 23 câu tăng từ `\$0.000396` lên `\$0.000790` và `p95 latency` tăng nhẹ khoảng `~20–30 ms` (bước `search_knowledge_base`).
- Đổi lại, độ chính xác tăng vọt từ `4.35%` lên **`100.0%`**, giúp chỉ số **chi phí trên mỗi câu trả lời đúng (`cost / câu đúng`) rẻ hơn tới `11.5 lần`** (`\$0.00039615` xuống còn `\$0.00003436`). Đây là khoản đánh đổi cực kỳ xứng đáng.

---

## 4. Observability stack (production)

### 4.1 Screenshot & Phân tích Dashboard (Exercise 7.1 & 7.4)

- [x] Dashboard Grafana khi đang có tải: [`screenshots/grafana-dashboard.png`](screenshots/grafana-dashboard.png)
- [x] Một trace chậm trong Jaeger: [`screenshots/jaeger-slow-trace.png`](screenshots/jaeger-slow-trace.png)
- [x] Một trace lỗi trong Jaeger: [`screenshots/jaeger-error-trace.png`](screenshots/jaeger-error-trace.png)
- [x] Trang Alerts của Prometheus với 4 alert đang **FIRING**: [`screenshots/prometheus-alert-firing.png`](screenshots/prometheus-alert-firing.png)

**Trả lời các câu hỏi quan sát Metrics & Grafana (Exercise 7.1 & 7.4):**
1. **Ví dụ 3 loại metric của Agent:**
   - *Counter:* `http_requests_total`, `llm_tokens_total`, `llm_cost_usd_total` (chỉ tăng đơn điệu, dùng kèm `rate()`).
   - *Gauge:* `agent_in_flight_requests`, `agent_info` (tăng/giảm tức thời theo trạng thái hiện tại).
   - *Histogram:* `http_request_duration_seconds`, `llm_request_duration_seconds`, `agent_question_length_chars` (chia mẫu vào các `_bucket` để tính phân vị bằng `histogram_quantile()`).
   - *Về label `route.path` vs `request.url.path`:* Nếu gán thẳng URL thật vào label `route`, khi bot quét hàng vạn đường dẫn ngẫu nhiên (`/wp-admin`, `/.env`, `/abc123`...), mỗi URL tạo ra một time series mới làm **bùng nổ cardinality** và tràn bộ nhớ RAM của Prometheus. Gán template route (`/ask`) và gom toàn bộ URL lạ vào `"unmatched"` giữ số lượng series cố định và an toàn.
2. **Khoảng cách `p95` vs `avg` trên Grafana khi chạy tải 30 users:** Trên dashboard lúc ổn định (`18.7 req/s`, error rate `0.78%`), `avg` ở mức `~238.3 ms`, `p95` ở mức `293.33 ms`, trong khi đường `p99` vọt lên vùng đỏ `~1.7s`. Khoảng cách giữa `avg` và `p95`/`p99` cho thấy đa số request hoàn tất quanh `200 ms`, nhưng nhánh đuôi 3% request chậm từ LLM kéo phân vị cao vọt lên rõ rệt.
3. **Phân phối tải qua Nginx ("Requests/s theo instance"):** Nginx chia tải **rất đều** theo cơ chế round-robin giữa 2 container (`172.20.0.7:8000` nhận `~2.33 req/s` và `172.20.0.8:8000` nhận `~2.24 req/s` tại cùng thời điểm đo; trên biểu đồ lúc tải 18.7 req/s hai đường chồng khít nhau ở ~9.3 req/s mỗi instance).
4. **Vì sao `input tokens/s` luôn lớn hơn `output tokens/s`?** Ở Agent `v2`, mỗi prompt đầu vào bao gồm `SYSTEM_PROMPT` + đoạn tài liệu truy xuất từ `KNOWLEDGE_BASE` + câu hỏi của user (~73–85 input tokens), trong khi câu trả lời ngắn gọn đầu ra chỉ khoảng ~35–46 output tokens (trên Prometheus đo được `348.3 input tokens/s` so với `181.5 output tokens/s`, gần gấp đôi).
5. **Kết quả `curl http://localhost:8080/metrics`:** Trả về **`HTTP 404 Not Found`**. Lý do: trong `production/nginx/nginx.conf`, khối `location = /metrics { return 404; }` chủ động chặn truy cập từ mạng ngoài để không làm lộ thông tin nội bộ (lưu lượng, cấu trúc route, phiên bản model, tốc độ chi tiêu); chỉ Prometheus nằm trong mạng nội bộ Docker `obs_net` mới scrape trực tiếp `agent:8000/metrics` qua DNS service discovery.

### 4.2 Thí nghiệm "phá hệ thống"

*(Thực hiện trên cụm `k5-day14-observability` có tải nền liên tục, theo dõi chuyển trạng thái `inactive → pending → firing` qua `/api/v1/alerts` và giao diện `http://localhost:9090/alerts`).*

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` (`for: 1m`, giá trị đo `20.32%` > ngưỡng `5%`) | `30.1s` vào `PENDING` → **`90.2s`** vào `FIRING` | **Error rate** (Golden Signals đỏ rực ~20%) & **Requests/s theo status code** (nhánh `503` tăng mạnh) |
| B | `MOCK_SLOW_RATE=0.3` | `AgentHighLatencyP95` (`for: 2m`, giá trị đo `1.92s` > ngưỡng `1s`) | `25.1s` vào `PENDING` → **`140.4s`** vào `FIRING` | **Latency p95** & **Latency `/ask` — p50 / p95 / p99** (đường `p95` vượt hẳn vùng ngưỡng đỏ `1s`) |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` (`for: 2m`, tốc độ đốt tiền nhảy lên **`$13.25/giờ`** > ngưỡng `$2/giờ`) | Khoảng **`~130–140s`** (`~15–20s` để `rate()[5m]*3600` vượt `$2/h` + `120s` thời gian `for: 2m`) | **Cost burn rate (USD/giờ)**, **LLM cost (1h)** và **LLM latency p95 theo model** (tăng gấp ~2.5x) |
| D | `docker pause k5-day14-observability-agent-2` | `AgentInstanceDown` (`up{job="agent"} == 0` cho `172.20.0.7:8000`, `for: 30s`) | `15.1s` vào `PENDING` → **`45.1s`** vào `FIRING` | **Instances up** (tụt từ `2` xuống `1`) & **Requests/s theo instance** (1 đường rơi về 0; lưu ý lỗi 504 timeout ở Nginx không tính vào error metric của bản thân agent) |
| E | `AGENT_VERSION=v1` | **Không có alert mới nào firing** (mọi Golden Signals hạ tầng đều xanh) | Không firing (`∞`) | **Retrieval hit ratio** biến mất, **Tokens/s** giảm gần một nửa, bảng **Phiên bản đang chạy** đổi sang `v1` |

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**
- Sự cố tụt phiên bản/hỏng RAG (`v2` → `v1`) là **suy giảm chất lượng ngữ nghĩa (silent quality degradation)** chứ không gây lỗi HTTP 5xx hay tăng latency nên các cảnh báo hạ tầng không thể bắt được.
- Để phát hiện trong production cần kết hợp 3 lớp:
  1. **Trước khi lên production (CI/CD Quality Gate):** Chạy bộ `eval/run_eval.py` trên golden dataset tự động ở mọi PR/build để chặn ngay cấu hình làm tụt accuracy trước khi deploy.
  2. **Giám sát chỉ số nghiệp vụ / hành vi RAG (Domain Metrics):** Đặt alert cho sự sụt giảm bất thường của `retrieval_requests_total{result="hit"}` (ví dụ hit ratio rơi về 0% khi lẽ ra đang chạy RAG) hoặc sự thay đổi ngoài ý muốn trên `agent_info{version="v1"}` và tỷ lệ phản hồi tiêu cực của user (thumbs-down).
  3. **Online Evaluation / Synthetic Canary:** Định kỳ mỗi 5–15 phút chạy câu hỏi kiểm chuẩn (canary probes) hoặc lấy mẫu (sample 1–5%) log hội thoại thật chấm điểm bằng **LLM-as-a-Judge** rồi đẩy metric điểm chất lượng về Prometheus để cảnh báo khi điểm trung bình giảm.

### 4.3 Debug bằng trace

Chọn trace chậm nhất tìm được trên Jaeger ([`screenshots/jaeger-slow-trace.png`](screenshots/jaeger-slow-trace.png)):

- `trace_id`: `39b125963a6e33d2e2bb0b1f5e10f2d7`
- Tổng thời gian: **`1715.36 ms`** (`POST /ask`: `1715.36 ms` → `agent.run`: `1713.58 ms` → `agent.retrieve_context`: `20.71 ms`)
- Span chiếm nhiều thời gian nhất: **`chat mock-llm-small`** (**`1692.72 ms`**, chiếm **`98.68%`** tổng thời gian request — khẳng định nguyên nhân chậm nằm ở bước chờ phản hồi từ LLM provider chứ không phải do xử lý HTTP hay truy xuất knowledge base)
- Dòng log JSON tương ứng trích xuất từ `docker compose -p k5-day14-observability logs agent` (grep theo `trace_id`):

```json
{"ts": "2026-11-25T08:30:08.882308+00:00", "level": "INFO", "service": "observable-agent", "instance": "71a9b347935c", "event": "llm_call", "trace_id": "39b125963a6e33d2e2bb0b1f5e10f2d7", "span_id": "804a4a7301a3d85b", "request_id": "ecccd1ffec30", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 81, "output_tokens": 46, "cost_usd": 4e-05, "llm_ms": 1691.8}
{"ts": "2026-11-25T08:30:08.882595+00:00", "level": "INFO", "service": "observable-agent", "instance": "71a9b347935c", "event": "http_request", "trace_id": "39b125963a6e33d2e2bb0b1f5e10f2d7", "span_id": "804a4a7301a3d85b", "request_id": "ecccd1ffec30", "method": "POST", "route": "/ask", "status": 200, "ms": 1714.9}
```

*(Ngoài ra, với trace lỗi [`screenshots/jaeger-error-trace.png`](screenshots/jaeger-error-trace.png) có `trace_id = 836374e60b69644723dc4b9eba1767a9`, tổng thời gian `118.5 ms`, span `chat mock-llm-small` ghi nhận event `exception` khớp hoàn toàn với dòng log JSON:*
`{"ts": "2026-11-25T08:32:46.362211+00:00", "level": "INFO", "service": "observable-agent", "instance": "71a9b347935c", "event": "llm_error", "trace_id": "836374e60b69644723dc4b9eba1767a9", "span_id": "07a90feb21aed706", "request_id": "c12e5c4d103e", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}` *).*

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

*(Số liệu trích xuất trực tiếp từ [`benchmark-results/scale_1_stats.csv`](benchmark-results/scale_1_stats.csv) và [`benchmark-results/scale_3_stats.csv`](benchmark-results/scale_3_stats.csv) — hiển thị cả dòng riêng `POST /ask` và dòng `Aggregated` gồm `/ask` + `/health`).*

| Số instance | RPS (`POST /ask` / `Aggregated`) | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---:|---:|---:|---|
| 1 | `60.09` / `66.09` | 190 | 220 | 1700 | `79 / 7904` (`1.00%` tổng · `1.10%` trên `/ask`) |
| 3 | `59.78` / `66.08` | 190 | 220 | 1700 | `77 / 7853` (`0.98%` tổng · `1.08%` trên `/ask`) |

**Giải thích kết quả:**
- **Scale từ 1 lên 3 instance gần như KHÔNG làm giảm `p95` (`220 ms`) hay tăng RPS (`~66.09 req/s`).**
- **Hai nguyên nhân gốc rễ (nút thắt cổ chai thực sự):**
  1. **Nút thắt nằm ở I/O chờ Upstream LLM chứ không phải CPU của container Agent:** Agent được viết bất đồng bộ (`async def`), trong đó ~98% thời gian request là chờ phản hồi từ LLM (`~180 ms` thông thường, `~1700 ms` khi rơi vào tail latency) và `~20 ms` cho retrieval. Ở mức tải `~66 req/s`, ngay cả 1 container đơn lẻ vẫn chưa chạm ngưỡng nghẽn CPU (`0.5 vCPU`), nên nhân thêm 3 bản sao không thể rút ngắn thời gian suy luận của dịch vụ LLM bên ngoài.
  2. **Giới hạn phía tải sinh ra từ Locust (`wait_time`):** Trong `locustfile.py`, mỗi user ảo có thời gian nghỉ giữa hai lần hỏi (`between(0.5, 2.0)` trung bình `1.25s`). Theo Định luật Little ($RPS = \frac{N}{W + R} \approx \frac{100}{1.25 + 0.23} \approx 67\text{ req/s}$), 100 user ảo chỉ tạo ra tối đa ~66–67 req/s nên cả `scale=1` lẫn `scale=3` đều xử lý trọn vẹn lưu lượng đầu vào này. Việc chạy 3 instance ở đây mang lại giá trị chính về **High Availability (chịu lỗi khi 1 container sập/restart)** và sẵn sàng gánh các tác vụ nặng CPU hơn (embedding/reranking/parsing).

---

## 6. Kết luận

- **3 điều rút ra về Benchmark & Observability:**
  1. **Đừng bao giờ tin vào Latency Trung Bình (`avg`):** Chỉ cần 3%–10% request bị tail latency từ LLM đã khiến người dùng thực tế phải chờ gần 2 giây dù `avg` trông vẫn dưới 350 ms; mọi SLO và Alert độ trễ bắt buộc phải định nghĩa trên phân vị `p95`/`p99`.
  2. **Observability hạ tầng "xanh" không đồng nghĩa AI trả lời đúng:** Metrics/Alerts truyền thống chỉ phát hiện lỗi 5xx, nghẽn latency, sập instance hoặc đội chi phí, nhưng hoàn toàn "mù" trước lỗi suy giảm chất lượng câu trả lời (như tụt từ `v2` về `v1`) — bắt buộc phải song hành với **Golden Dataset Eval + Quality Gate trong CI/CD**.
  3. **Liên kết 3 trụ cột (Metrics → Traces → Logs qua `trace_id`) giúp khoanh vùng gốc rễ tức thì:** Dashboard Grafana cho biết *khi nào* `p95`/error tăng, Jaeger chỉ ra chính xác *span nào* (`chat mock-llm-small` chiếm `98.7%` thời gian) gây chậm thay vì tối ưu nhầm tầng code FastAPI, và `trace_id` nối thẳng sang dòng JSON log chi tiết của request đó.
- **Nếu đưa agent này lên production thật, cần bổ sung thêm các metric & alert sau:**
  - **Metrics & Alerts ở tầng Load Balancer / Ingress (Nginx / Cloud Load Balancer):** Theo dõi tỷ lệ `502`/`504 Gateway Timeout` từ góc nhìn người dùng ngoài cùng (vì khi container bị treo/pause như Thí nghiệm D, lỗi 504 phát sinh tại Nginx và không được đếm trong metric nội bộ của agent).
  - **Metrics chất lượng AI trực tuyến & Guardrails:** Tỷ lệ cache/retrieval hit (`retrieval_hit_ratio < ngưỡng`), thời gian đến token đầu tiên (**TTFT — Time To First Token**) khi bật streaming, tỷ lệ câu trả lời bị từ chối/hallucination chấm qua LLM-as-a-Judge mẫu ngẫu nhiên, và tỷ lệ đánh giá hài lòng của người dùng cuối.
  - **Metrics sức khoẻ phụ thuộc ngoại vi (Redis & Rate Limit):** Độ trễ lệnh Redis, tỷ lệ kết nối lỗi tới Redis, và tốc độ request bị từ chối bởi `429 Rate Limit` / `402 Budget Exceeded` để phát hiện sớm bot tấn công hoặc khách hàng chạm trần hạn mức.
