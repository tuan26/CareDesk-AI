# Triển khai — Frontend Vercel + Backend Render/Railway/Fly

Kiến trúc đã chọn: **frontend lên Vercel, backend chạy container riêng**. Backend
giữ nguyên scheduler nhắc lịch, WebSocket realtime và rate limiter in-memory —
những thứ serverless không chạy được.

```
        Khách / Google / Facebook
                   │
                   ▼
        ┌──────────────────────┐
        │  Vercel (domain chính) │
        │  • SPA: /, /chat/*    │
        │  • rewrite ──────────┼──► Backend  /book/*, /sitemap.xml, /robots.txt
        └──────────┬───────────┘
                   │ gọi trực tiếp (CORS + WSS)
                   ▼
        ┌──────────────────────┐      ┌────────────┐
        │ Render/Railway/Fly   │─────►│ PostgreSQL │
        │ FastAPI + scheduler  │      └────────────┘
        └──────────────────────┘
```

## Vì sao `/book/*` phải đi qua Vercel

Landing page do backend render, nhưng **phải xuất hiện trên domain chính**. Nếu để
khách vào `api.onrender.com/book/caredesk`, thì `canonical`, `og:url` và toàn bộ
sitemap sẽ trỏ về domain backend — Google index nhầm domain, link chia sẻ lên
Facebook hiện tên miền kỹ thuật, và sau này đổi nhà cung cấp backend là mất sạch
thứ hạng. `rewrites` trong [frontend/vercel.json](frontend/vercel.json) giữ mọi thứ trên một domain.

API và WebSocket thì **gọi thẳng** backend (không qua rewrite), vì Vercel rewrite
không giữ được kết nối WebSocket lâu dài cho Inbox realtime.

---

## Bước 1 — Backend

### Render (khuyến nghị: có sẵn blueprint)

1. Push repo lên GitHub (đã xong).
2. Render → **New → Blueprint** → chọn repo. Nó đọc [render.yaml](render.yaml),
   tạo web service + Postgres.
3. Điền các biến `sync: false` (Render sẽ hỏi):

| Biến | Giá trị | Ghi chú |
|---|---|---|
| `PUBLIC_BASE_URL` | `https://<domain-vercel>` | **Domain Vercel**, KHÔNG phải domain Render |
| `BACKEND_CORS_ORIGINS` | `https://<domain-vercel>` | phân tách bằng dấu phẩy; `*` sẽ làm app **từ chối khởi động** |
| `OPENAI_API_KEY` | khoá của bạn | để trống = AI chạy chế độ mock |
| `PLATFORM_ADMIN_EMAIL` | email của bạn | |
| `PLATFORM_ADMIN_PASSWORD` | mật khẩu mạnh | để trống = tự sinh, in ra log **một lần duy nhất** |

4. Deploy. Migration `alembic upgrade head` tự chạy lúc khởi động.
5. Kiểm tra `https://<domain-render>/health` → `{"status":"ok"}`.

> **Gói free của Render ngủ sau 15 phút không có traffic.** Scheduler nhắc lịch
> sẽ *ngừng chạy* khi ngủ, nên lịch hẹn 24h/2h không được gửi. Muốn nhắc lịch
> hoạt động thật thì phải dùng gói trả phí (`starter` trở lên). Fly.io với
> `min_machines_running = 1` cũng giải quyết được điều này.

### Railway
Không cần file cấu hình: trỏ vào repo, đặt Dockerfile path = `backend/Dockerfile`,
build context = thư mục gốc, rồi copy y hệt bảng biến ở trên + thêm Postgres plugin.

### Fly.io
Dùng [fly.toml](fly.toml), làm theo các lệnh ghi ở đầu file.

---

## Bước 2 — Frontend lên Vercel

1. Sửa [frontend/vercel.json](frontend/vercel.json): thay **cả 3 chỗ**
   `REPLACE-WITH-BACKEND-HOST` bằng host backend thật (vd. `caredesk-api.onrender.com`).
2. Vercel → **Add New → Project** → chọn repo → **Root Directory = `frontend`**.
3. Thêm biến môi trường:

| Biến | Giá trị |
|---|---|
| `VITE_API_URL` | `https://<domain-backend>` |

> Vite nhúng biến này **lúc build**, không phải lúc chạy. Đổi giá trị thì phải
> **redeploy**, không chỉ restart.

4. Deploy.

## Bước 3 — Nối hai bên lại

Sau khi có domain Vercel thật, quay lại backend và cập nhật:
- `PUBLIC_BASE_URL` = domain Vercel
- `BACKEND_CORS_ORIGINS` = domain Vercel

Vercel tạo **preview domain riêng cho mỗi lần deploy**. Nếu muốn test bản preview
thì phải thêm domain đó vào `BACKEND_CORS_ORIGINS`, nếu không trình duyệt sẽ chặn
mọi lệnh gọi API.

---

## Kiểm tra sau khi deploy

```bash
D=https://<domain-vercel>
curl -s $D/robots.txt                          # phải thấy Sitemap: trỏ đúng domain này
curl -s $D/sitemap.xml | head                  # <loc> phải là domain này
curl -s $D/book/<brand> | grep -o '<title>[^<]*'   # tiêu đề riêng của phòng khám
curl -s -o /dev/null -w '%{http_code}\n' $D/   # SPA
```

- Mở `$D/book/<brand>` → đổi ngôn ngữ VI/EN/JA phải chạy.
- Dán link vào Facebook/Zalo → preview phải hiện đúng tên + ảnh phòng khám.
- Đăng nhập dashboard → Inbox phải kết nối được WebSocket (nếu lỗi: kiểm tra
  `BACKEND_CORS_ORIGINS` và backend có chạy HTTPS không).

## Việc phải làm thủ công sau lần deploy đầu

1. Lấy mật khẩu platform admin trong log backend (nếu không tự đặt), **đăng nhập
   và đổi ngay**.
2. Tạo phòng khám thật trong `/platform` — production **không seed dữ liệu demo**
   (`SEED_DEMO_DATA=false`).
3. Nhập **ảnh og:image 1200×630** cho từng phòng khám, nếu không preview mạng xã
   hội sẽ dùng logo và thường bị Facebook bỏ qua vì quá nhỏ.
4. Gửi `sitemap.xml` cho Google Search Console.

## Giới hạn đã biết

- **Một tiến trình duy nhất** (`WEB_CONCURRENCY=1`). Scheduler và rate limiter
  lưu state trong RAM: chạy 2 worker là mỗi bệnh nhân nhận nhắc lịch 2 lần.
  Muốn scale ngang phải chuyển rate limit sang Redis và tách scheduler ra riêng.
- **Landing cache 5 phút** — sửa thông tin phòng khám xong phải chờ mới thấy.
- Chưa có backup tự động: bật snapshot của nhà cung cấp Postgres và **thử restore
  ít nhất một lần** trước khi có dữ liệu bệnh nhân thật.
