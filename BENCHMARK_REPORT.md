# Benchmark & Observability Report — Day 14

**Họ tên:** Phùng Văn Thanh Cao
**Ngày chạy:** 2026-11-26
**Môi trường:** Windows 10 22H2, WSL2 Ubuntu, Python 3.11, máy 7.3 GB RAM. Agent chạy bằng `python app.py` (1 process uvicorn, 1 event loop) cho mỗi phiên bản; load test và agent chạy cùng một máy.

> Mọi số trong mục 2 và 3 lấy từ các file JSON trong thư mục `reports/`.

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | < 500 ms | Một lần gọi mock LLM mất khoảng 150–220 ms (p50 đo được 187–200 ms ở tải thấp). Ngưỡng 500 ms cho phép dư khoảng 2.5 lần so với p50 nhưng vẫn đủ chặt để lộ vấn đề khi hàng đợi bắt đầu hình thành. Đặt theo p95, không đặt theo average. |
| Error rate `/ask` | < 2 % | Mock LLM cố ý trả lỗi 503 một phần nhỏ request; error rate đo được trong 7 lần load test nằm trong khoảng 0.67–1.67 %. Mức 2 % chừa chút dư để không báo động giả, nhưng vẫn là ngưỡng người dùng cảm nhận được. |
| Accuracy trên golden dataset | ≥ 80 % | Là ngưỡng mặc định của quality gate trong `run_eval.py`, và thấp hơn mức v2 đạt được ban đầu (91.3 %). Với 23 câu, mỗi câu sai làm accuracy giảm khoảng 4.3 điểm %, nên 80 % tương ứng chỉ được sai tối đa 4 câu. Khi sửa xong KB, tôi nâng gate lên 100 % và kèm điều kiện không regression. |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

Mỗi dòng là một lần chạy `python load_test.py --url http://localhost:8002 --requests 300 --concurrency N`, agent v2, `MOCK_SLOW_RATE` mặc định (0.03). Mỗi mức chỉ chạy **một lần**.

### 2.1 Concurrency vs latency (agent v2)

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 4.4 | 187.4 | 218.7 | 1708.5 | 1.67 % | PASS |
| 10 | 33.93 | 189.8 | 224.7 | 1708.9 | 0.67 % | PASS |
| 50 | 105.58 | 200.5 | 290.5 | 1702.1 | 1.33 % | PASS |
| 100 | 58.73 | 426.3 | 3475.1 | 3681.9 | 1.33 % | **FAIL** (p95 > 500 ms) |

(File: `reports/load_v2_c1.json`, `c10`, `c50`, `c100`.)

**Nhận xét:** RPS không tăng tuyến tính mà chia làm hai giai đoạn.
- **Từ 1 lên 50 tăng mạnh nhưng chưa tuyến tính (1 → 50 chỉ gấp khoảng 24 lần, không phải 50 lần):** ở concurrency 1, mỗi request tuần tự mất khoảng 227 ms (300 request trong 68.19 s) nên RPS chỉ 4.4. Khi tăng lên 10 rồi 50, nhiều request chạy chồng nhau trong khi mỗi request vẫn chủ yếu *chờ* (mock LLM là `sleep`, không tốn CPU), nên RPS tăng lên 33.93 rồi 105.58 còn p50 gần như giữ nguyên (khoảng 190–200 ms). Tăng concurrency 1 → 10 làm RPS gấp 7.7 lần, chưa đủ 10 lần.
- **Tại 100 thì sụp:** RPS giảm xuống 58.73 và p95 vọt lên 3475 ms, vi phạm SLO. Đây là dấu hiệu bão hòa: quá nhiều request đồng thời tranh nhau một process nên hàng đợi hình thành và latency tăng, throughput không tăng thêm. Cần lưu ý là mỗi mức chỉ có 300 request (lần chạy c=100 chỉ kéo dài 5.11 s) và chỉ chạy một lần, nên con số có nhiễu. Tôi chưa chạy lại nhiều lần và chưa đo CPU, nên "tranh tài nguyên của một process" là giải thích hợp lý nhưng tôi chưa kiểm chứng riêng.
- Cột p99 ≈ 1700 ms ở c=1, 10, 50 đến từ một số ít request chậm do `MOCK_SLOW_RATE=0.03`; xem mục 2.2.

### 2.2 Tail latency

Mỗi dòng: `--requests 300 --concurrency 20`, agent v2 khởi động lại với `MOCK_SLOW_RATE` tương ứng.

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 192.1 | 220.0 | 230.1 |
| 0.03 (mặc định) | 267.2 | 461.0 | 1702.2 |
| 0.1 | 302.2 | 1679.1 | 1714.2 |

(File: `reports/load_v2_slow_0.json`, `load_v2_slow_0.03.json`, `load_v2_slow_0.1.json`.)

**Nhận xét:**
- Từ rate 0 lên 0.1, **avg chỉ tăng khoảng 57 %** (192.1 → 302.2 ms) trong khi **p95 tăng khoảng 7.6 lần** (220.0 → 1679.1 ms) và **p99 tăng khoảng 7.5 lần** (230.1 → 1714.2 ms).
- Ở rate 0.03, p95 là 461.0 ms, chỉ cách ngưỡng SLO 500 ms một đoạn ngắn, còn p99 đã là 1702.2 ms. Nghĩa là p99 phản ứng với request chậm sớm nhất; p95 chỉ "nhảy" khi tỉ lệ request chậm đủ lớn để chiếm hơn 5 % mẫu (như ở rate 0.1).
- Chỉ số nhạy nhất với request chậm là **p99** (rồi tới p95 khi tỉ lệ chậm vượt 5 %).
- **Vì sao SLO không nên đặt theo average:** average trộn các request chậm vào đa số request nhanh nên bị "pha loãng". Ở rate 0.1, avg là 302 ms (trông ổn, dưới 500 ms) trong khi cứ 10 người thì có hơn 1 người chờ gần 1.7 giây. SLO theo percentile phản ánh đúng trải nghiệm của nhóm người dùng bị ảnh hưởng.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.3 % (1/23) | 91.3 % (21/23) | 100.0 % (23/23) |
| Avg tokens / câu | 57.6 | 109.1 | 114.7 |
| Tổng cost (USD) | 0.000411 | 0.000762 | 0.000799 |
| Cost / câu đúng (USD) | 0.00041055 | 0.00003627 | 0.00003475 |
| Quality gate | FAIL | PASS | PASS |

(File: `reports/eval_v1.json`, `eval_v2.json`, `eval_v2_fixed.json`. Quality gate của v1 và v2 dùng ngưỡng mặc định 80 %; lần chạy sau khi sửa dùng `--min-accuracy 1.0 --baseline reports/eval_v2.json` và in `✅ PASS`, 23/23, 0 regression.)

**Những câu v2 trả lời sai ban đầu và cách bạn sửa:**

| ID | Keyword bị thiếu | Bạn đã sửa gì |
|---|---|---|
| `security-02` ("JWT khác gì API key trong xác thực?") | `token`, `hết hạn`, `chữ ký` | Thêm vào `KNOWLEDGE_BASE` trong `develop/utils/mock_llm.py` một entry kích hoạt bởi từ khóa `jwt` / `api key`, nội dung nêu rõ JWT là token có chữ ký số và thời gian hết hạn, còn API key là chuỗi tĩnh không tự hết hạn. |
| `scaling-03` ("Kubernetes HPA scale dựa trên những chỉ số nào?") | `cpu`, `memory`, `custom metrics` | Thêm entry kích hoạt bởi `hpa` / `autoscal`, nội dung nêu HPA scale theo CPU, memory và custom metrics. |

Trước khi sửa, retrieval không tìm được tài liệu cho hai câu này nên agent trả câu trả lời chung chung (`score=0.0`). Tôi chỉ sửa `KNOWLEDGE_BASE`, không đụng tới `golden_dataset.jsonl` hay `run_eval.py`.

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:**
- **Chất lượng:** v2 tăng accuracy từ 4.3 % lên 91.3 % (20 câu được cải thiện, 0 regression) nhờ bước retrieval.
- **Chi phí:** v2 dùng nhiều token hơn khoảng 89 % mỗi câu (57.6 → 109.1) vì prompt có thêm context, nên tổng cost cao hơn (0.000411 → 0.000762 USD). Nhưng tính theo **cost / câu đúng** thì v2 rẻ hơn khoảng 11 lần (0.00041055 → 0.00003627 USD), vì v1 gần như không trả lời đúng câu nào. Cost / câu đúng là chỉ số công bằng hơn tổng cost.
- **Latency:** p50 trong eval tăng từ 160.1 ms (v1) lên 204.3 ms (v2), do thêm bước retrieval. Cột p95 của v2 trong lần eval đầu là 1515.0 ms nhưng chỉ do **một** request chậm (`cloud-01`, 1658.7 ms) trên mẫu 23 câu; mẫu quá nhỏ để kết luận về latency (đúng như cảnh báo của README), nên latency phải đo bằng load test như mục 2.
- Sửa KB làm avg token tăng nhẹ (109.1 → 114.7) và cost tăng 0.000037 USD vì hai câu vốn trả lời ngắn nay có context đầy đủ.

### Quality gate trong CI

Lệnh `run_eval.py` trả **exit code 0 khi qua gate** và **1 khi không qua** (accuracy dưới `--min-accuracy` hoặc có câu regression so với `--baseline`). Tôi đã kiểm tra thực tế: chạy eval agent v1 với `--baseline reports/eval_v2.json` thì exit code là `1`, gate `❌ FAIL` và có 20 câu regression. Vì CI coi exit code khác 0 là bước thất bại, đặt bước này trong workflow `.github/workflows/eval.yml` và bật *branch protection* (bắt buộc check này pass) sẽ chặn merge khi chất lượng giảm. Xem file `.github/workflows/eval.yml`.

---

## 4. Observability stack (production)

_(Làm ở Giai đoạn E, sau khi chạy stack Docker. Chưa có số liệu.)_

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

_(Làm ở Giai đoạn E. Chưa có số liệu.)_

---

## 6. Kết luận

_(Viết sau khi xong mục 4 và 5.)_
