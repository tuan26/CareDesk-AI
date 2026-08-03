# CareDesk AI — AI Revenue Engine cho phòng khám Da liễu & Thẩm mỹ

SaaS multi-tenant vận hành doanh thu tự động: AI trực chat 24/7 đa kênh (web/Zalo/Facebook), tự chốt lịch + thu cọc trong hội thoại, follow-up khách hỏi giá, nhắc tái khám, bán gói liệu trình, xin review/giới thiệu, lấp chỗ trống — và **đo được chính xác AI kiếm được bao nhiêu tiền (attribution + ROI)**.

## Revenue Engine (điểm khác biệt cốt lõi)

- **Event bus + Automation Engine**: mọi hành vi (hỏi giá, đặt lịch, hoàn thành, hủy...) phát sự kiện; kịch bản tự động là **cấu hình, không phải code** — 8 kịch bản mặc định: follow-up hỏi giá 2/5 ngày (tự hủy khi khách đặt), nhắc tái khám 30 ngày, đánh thức khách cũ 6 tháng, xin review sau khám, nhắc gói sắp hết hạn, upsell khi dùng hết gói, lấp chỗ trống từ danh sách chờ
- **Attribution + Revenue Ledger**: mỗi đồng doanh thu gắn nguồn (AI chat / AI follow-up / lễ tân / bán gói / giới thiệu) → dashboard "Doanh thu AI tạo ra" + ROI trên phí gói
- **Đặt cọc online**: AI gửi link cọc khi chốt lịch, thanh toán xong lịch tự XÁC NHẬN (mock gateway, adapter VNPay/MoMo-ready) — kèm CAPI bắn conversion về Meta ads
- **Gói liệu trình trả trước**: bán gói thu tiền sớm, buổi khám hoàn thành tự trừ vào gói, tự nhắc buổi chưa dùng/hết hạn
- **Review + Referral**: 4-5 sao → mời review Google + tặng mã giới thiệu (đo được khách mới do ai giới thiệu); 1-3 sao → **chặn lại, chuyển chủ xử lý trước khi lên mạng**
- **Comment Guard**: tự trả lời + ẩn comment quảng cáo Facebook, kéo khách vào inbox
- **Copilot nội bộ**: chủ/lễ tân hỏi "Doanh thu hôm nay?", "Bao nhiêu lịch hẹn?" ngay trên dashboard (function-calling, RBAC, không bịa số) + bản tin vận hành 8h/20h qua SMS/email

## Tính năng chính

**Kênh khách hàng**
- Web chat widget (form consent trước khi chat)
- Webhook Zalo OA & Facebook Messenger (`/api/v1/webhooks/{zalo|facebook}/{clinic_id}`), tự động chạy mock khi chưa cấu hình token
- AI đặt lịch end-to-end trong chat: thu thập thông tin → đề xuất khung giờ trống thật → tạo lịch hẹn `pending`

**An toàn y tế**
- Safety filter (khẩn cấp / kê đơn / ảnh chẩn đoán / nhóm nhạy cảm) → từ chối tư vấn chuyên môn + handoff cho người thật
- Golden Dataset 7 kịch bản đánh giá chất lượng AI (chạy từ trang Cài đặt)

**Vận hành**
- Nhắc lịch tự động 24h/2h trước hẹn qua Email + ZNS/SMS, kèm link xác nhận/hủy 1 chạm (token HMAC, không cần đăng nhập)
- Inbox realtime (WebSocket) — lễ tân tiếp quản chat, trả lời cả khách Zalo/FB từ một màn hình
- Lịch hẹn dạng danh sách + lịch tuần (calendar), tra khung giờ trống theo bác sĩ
- Mini-CRM: hồ sơ khách, tags, ghi chú, lịch sử hẹn & liệu trình

**SaaS**
- Multi-tenant: mỗi phòng khám một không gian dữ liệu riêng, đăng ký self-service (`/register`)
- Gói cước Free (200 hội thoại AI/tháng) / Pro (5.000) — vượt quota tự chuyển lễ tân
- RBAC: admin / owner / receptionist; audit log mọi thao tác quan trọng; rate-limit endpoint công khai

## Chạy dev

```bash
# Backend (Python 3.11+)
python -m venv .venv
.venv/Scripts/pip install -r backend/requirements.txt
.venv/Scripts/python -m uvicorn backend.app.main:app --port 8000
# Swagger: http://localhost:8000/docs   Health: http://localhost:8000/health

# Frontend
cd frontend && npm install && npm run dev
# http://localhost:5173

# Widget demo: mở widget/index.html (cấu hình window.CareDeskConfig trong file)
```

Backend tự chạy `alembic upgrade head` rồi seed khi khởi động — không cần lệnh migration thủ công ở dev.

Tài khoản seed (chỉ tạo khi `SEED_DEMO_DATA` bật, mặc định bật ở dev):

| Tài khoản | Mật khẩu | Vai trò | Vào được |
|---|---|---|---|
| `owner@caredesk.ai` | `owner123` | owner | Dashboard phòng khám |
| `receptionist@caredesk.ai` | `receptionist123` | receptionist | Inbox, lịch hẹn |
| `admin@caredesk.ai` | `admin123` | admin | Toàn bộ phòng khám |
| `chain@caredesk.ai` | `chain123` | org_owner | `/org` — console chuỗi |
| `platform@caredesk.ai` | `platform123` | platform admin | `/platform` — console nhà phát hành |

## Test

```bash
.venv/Scripts/python -m pytest tests/            # unit tests
.venv/Scripts/python -m backend.app.services.evaluator  # đánh giá AI theo Golden Dataset
```

## Production

### Cách nhanh nhất: Docker Compose

```bash
cp .env.example .env       # điền POSTGRES_PASSWORD, SECRET_KEY, BACKEND_CORS_ORIGINS
docker compose up -d --build
docker compose logs backend | grep -i "generated a random password"   # lấy mật khẩu admin lần đầu
```

Compose dựng PostgreSQL + backend (`:8000`) + frontend nginx (`:80`), chạy sẵn `ENVIRONMENT=production`.

### Thủ công

1. Copy `backend/.env.example` → `.env`, đặt **`ENVIRONMENT=production`**, `SECRET_KEY`, `DATABASE_URL` (PostgreSQL), `BACKEND_CORS_ORIGINS`, SMTP/SMS.
2. Chạy backend — migration `alembic upgrade head` tự chạy lúc khởi động.
3. Frontend: đặt `VITE_API_URL` trỏ về backend rồi `npm run build`, serve thư mục `dist/`.
4. Cấu hình kênh Zalo/FB per-clinic trong Dashboard → Cài đặt → Kết nối kênh.

### Chốt chặn an toàn khi `ENVIRONMENT=production`

App **từ chối khởi động** nếu `SECRET_KEY` còn giá trị mặc định, hoặc `BACKEND_CORS_ORIGINS` để `*`.
`SEED_DEMO_DATA` mặc định **tắt** — không tạo tài khoản/dữ liệu demo trên DB thật. Tài khoản
platform admin vẫn được tạo; nếu không đặt `PLATFORM_ADMIN_PASSWORD`, hệ thống sinh mật khẩu
ngẫu nhiên và **log ra một lần duy nhất** lúc khởi động đầu tiên.

Scheduler nhắc lịch và rate limiter đang lưu state **in-memory, single-process**: chạy nhiều
uvicorn worker sẽ nhân bản reminder và rate limit theo số worker (app sẽ log cảnh báo).
Muốn scale ngang cần chuyển rate limit sang Redis và chỉ bật scheduler ở 1 process.

Kết nối DB cấu hình qua `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` / `DB_POOL_TIMEOUT` (mặc định 20/20/30).

## Cấu trúc

```
backend/app/
  main.py          khởi động: safety checks -> migration -> seed -> scheduler; / , /health
  api/endpoints/   auth, clinic, appointment, chat, webhooks, reports, public, ws,
                   packages, automations, copilot, platform, org, booking_requests
  services/        ai_engine, booking_flow, events (automation engine), reminder,
                   channel_gateway, payment_gateway, evaluator, public_chat_session,
                   i18n, rate_limit, audit, ws_manager, tenant_stats, capi
  core/            config, database, migrate, seed, security, logging_config, slug
  models|schemas   SQLAlchemy models / Pydantic schemas
  alembic/         migration (tự chạy khi khởi động)
frontend/src/
  pages/           Dashboard, Clinic, Services, Doctors, Appointments, BookingRequests,
                   Inbox, Patients, Packages, Automation, Reports, Settings,
                   Platform, Org, Chain, ClinicLanding, ClinicChat, Login, Register
  api.js           API_BASE / WS_BASE + auth headers      i18n.jsx  đa ngôn ngữ vi/ja/en
widget/            chat widget nhúng website
tests/             pytest + golden dataset
docker-compose.yml + backend/Dockerfile + frontend/Dockerfile
```

### Bản đồ URL

| URL | Cần đăng nhập | Dùng cho |
|---|---|---|
| `/` | ✅ | Dashboard phòng khám (sidebar: lịch hẹn, inbox, CRM, gói, báo cáo…) |
| `/org`, `/org/:slug` | ✅ | Console chuỗi — roll-up nhiều phòng khám |
| `/platform` | ✅ | Console nhà phát hành — quản lý tenant, gói cước |
| `/book/:org/:clinic` | ❌ | **Trang phòng khám** — link chuẩn gửi cho khách (tên, địa chỉ, SĐT + nút vào chat) |
| `/book/:org/:clinic/chat` | ❌ | Chat AI đặt lịch — khách vào từ nút trên trang phòng khám |
| `/book/:org` | ❌ | Trang chuỗi, khách chọn chi nhánh |

Link "Chép" ở console Nhà phát hành / Chuỗi trỏ về **trang phòng khám**, không nhảy thẳng vào chat —
khách thấy thông tin phòng khám trước rồi mới quyết định trò chuyện.
