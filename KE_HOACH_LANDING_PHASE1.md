# Kế hoạch Phase 1 — Landing Page phân cấp

> Trạng thái: **Giai đoạn A, B, C đã triển khai xong** (03/08/2026).
> Phần còn lại là Phase 2/3 trong roadmap, xem cuối README.

## 1. Quyết định đã chốt

| Vấn đề | Quyết định |
|---|---|
| "Cơ sở" (Bạch Mai/Linh Đàm/Hà Đông) là gì | **Branch** — không phải Clinic |
| SEO / preview mạng xã hội | **FastAPI render HTML** cho `/book/*`; dashboard giữ nguyên SPA |
| Bật/tắt landing | **Boolean từng entity**, không dùng enum trên cha |

## 2. Mô hình dữ liệu

```
Organization  (chuỗi / tập đoàn — TÙY CHỌN, đa số khách không dùng)
  └── Clinic  (thương hiệu + ĐƠN VỊ TÍNH TIỀN + ranh giới tenant)
        ├── Service   (bảng giá — dùng chung mọi cơ sở)
        ├── Doctor    (gán vào 1 cơ sở qua branch_id)
        └── Branch    (CƠ SỞ VẬT LÝ — địa chỉ, giờ làm việc)
```

Nguyên tắc: **một phòng khám trả một gói cước, dù có bao nhiêu cơ sở.**
CRM bệnh nhân, bảng giá, quota AI, inbox — dùng chung toàn Clinic.

Tin tốt: `Branch` đã được dùng sâu trong hệ thống (52 tham chiếu / 9 file, gồm
`booking_flow.py`, `ai_engine.py`; `Appointment` đã có `branch_id`). Phase 1
**không xây mới khái niệm** — chỉ cấp cho Branch một *danh tính công khai*.

## 3. Thay đổi schema

### Branch (thêm 3 cột)
| Cột | Kiểu | Mặc định | Lý do |
|---|---|---|---|
| `slug` | String, unique, index | sinh tự động | cần cho `/book/<clinic>/<branch>` |
| `landing_enabled` | Boolean | **false** | opt-in, đúng ý "chỉ khi phòng khám muốn" |
| `is_active` | Boolean | true | hiện Branch **chưa có** cờ này → không tạm ngưng được 1 cơ sở |

### Clinic (thêm 1 cột)
| `landing_enabled` | Boolean | **true** | landing chính, 90% khách chỉ cần cái này |

### Organization (thêm 1 cột)
| `landing_enabled` | Boolean | true | chỉ có tác dụng khi khách thực sự dùng chuỗi |

### Ba chế độ của bạn được diễn tả thế nào

| Chế độ | Clinic.landing_enabled | Branch.landing_enabled |
|---|---|---|
| 1. Chỉ landing chuỗi/phòng khám | `true` | tất cả `false` |
| 2. Chỉ landing từng cơ sở | `false` | `true` |
| 3. Cả hai | `true` | `true` (từng cơ sở tự chọn) |

Ưu điểm so với enum `landing_mode` trên cha: diễn tả được **"Hà Đông có landing,
Linh Đàm không"** — đúng nhu cầu chạy Ads theo địa điểm ở Phase 3.

### Migration
- 1 revision Alembic mới (nối sau `e5f6a7b8c9d0`).
- Backfill: sinh `slug` cho **mọi Branch đang có** (DB demo có sẵn 2: Quận 10, Quận 1).
- `is_active = true`, `landing_enabled = false` cho Branch cũ; `Clinic.landing_enabled = true`.

## 4. URL — giải qua Slug Registry

```
/book/<brand>                   → brand = entity giữ slug đó (Organization HOẶC Clinic)
/book/<brand>/<branch>          → landing cơ sở (khi Branch.landing_enabled)
/chat/<brand>                   → chat AI (SPA)
/chat/<brand>/<branch>          → chat AI có sẵn ngữ cảnh cơ sở
```

**`<brand>` LUÔN là Organization.** Clinic không bao giờ xuất hiện trong URL công
khai — đúng đề xuất cuối của chủ dự án.

Điều này khả thi vì **mọi Clinic đều có Organization**: khi admin chọn
"— Không thuộc chuỗi —", [platform.py](backend/app/api/endpoints/platform.py) tự
tạo một Organization *cá nhân* mang tên phòng khám. Không có clinic nào mồ côi.

> Đính chính: bản kế hoạch đầu tiên khẳng định `/book/{org}/{branch}` sẽ gãy với
> phòng khám độc lập vì `organization_id` là `nullable=True`. Kết luận đó rút ra
> từ schema mà chưa đọc code tạo clinic — **sai**. Ràng buộc thực tế do tầng ứng
> dụng bảo đảm, không phải schema.

| Loại khách | URL công khai | Org đứng sau |
|---|---|---|
| Chuỗi thật | `/book/caredesk/bach-mai` | chuỗi nhiều phòng khám |
| Phòng khám độc lập | `/book/an-khang/co-so-chinh` | org cá nhân tự sinh |

Clinic thuần tuý là tầng nghiệp vụ (tính tiền, ranh giới tenant). Nếu sau này
Clinic được tách theo chuyên khoa, URL công khai **không đổi**.

### Xử lý URL legacy `/book/A/B` (cũ: org/clinic)
Registry tra A và B, rồi phân biệt theo `entity_type`:
- B là **Clinic** → nghĩa cũ → **301** sang URL mới của clinic đó
- B là **Branch** → nghĩa mới → render landing cơ sở (kiểm tra B thuộc A)

Deterministic. Link cũ tự chuyển hướng thay vì gãy.

### Slug Registry (bảng `slug_registry`)
Hiện `unique=True` chỉ trong từng bảng → một Clinic và một Branch có thể trùng
slug, resolver sẽ dẫn bệnh nhân **sai phòng khám**. Với ứng dụng y tế đây là lỗi
an toàn, không phải lỗi thẩm mỹ.

Giải bằng **một bảng registry duy nhất**, thay vì kiểm tra rải rác 3 bảng:

```
slug_registry
  slug         String  PRIMARY KEY      -- unique toàn cục, cấp DB
  entity_type  String                   -- organization | clinic | branch
  entity_id    Integer
  is_active    Boolean                  -- false = slug cũ, chỉ dùng để 301
  created_at   DateTime
```

Ưu điểm:
- Không bao giờ trùng — ràng buộc ở tầng DB, không phụ thuộc code gọi đúng
- Resolve `/book/<slug>` bằng **một truy vấn có index**, không phải 3 lượt tra
- Thêm loại entity mới sau này **không phải sửa logic slug**
- Reserve keyword nằm chung một chỗ: chèn sẵn các slug hệ thống với
  `entity_type='reserved'` → `admin`, `api`, `chat`, `book`, `login`,
  `dashboard`, `assets`, `static`, `robots.txt`, `favicon.ico`, `sitemap.xml`
- **Đổi slug không giết QR code đã in**: giữ bản ghi cũ với `is_active=false`
  → resolver trả 301 sang slug mới

## 5. Backend — SSR

### Router mới `backend/app/api/endpoints/landing.py`
Mount ở **`/book`** (ngoài `/api/v1`), trả `HTMLResponse`:

| Route | Nội dung |
|---|---|
| `GET /book/{slug}` | Clinic landing (hoặc Org landing) |
| `GET /book/{a}/{b}` | Branch landing, hoặc 301 nếu a=Organization |

Mỗi trang render đầy đủ:
- `<title>`, `<meta name="description">` riêng cho từng phòng khám/cơ sở
- **`og:title` / `og:description` / `og:image`** ← thứ sửa lỗi preview Facebook/Zalo
- `<link rel="canonical">`
- JSON-LD `MedicalClinic` / `MedicalBusiness` (địa chỉ, giờ mở cửa, điện thoại) → rich result Google

### Dữ liệu Phase 1 lấy từ đâu (không cần field mới)
| Mục trên landing | Nguồn |
|---|---|
| Tên, logo, địa chỉ, hotline | `Clinic.name/logo_url/address/phone` ✅ |
| Danh sách cơ sở + giờ làm việc | `Branch.name/address/phone/working_hours` ✅ |
| Dịch vụ + giá | `Service` (clinic-scoped) ✅ |
| Đội ngũ bác sĩ | `Doctor` (+ chuyên khoa, theo cơ sở) ✅ |
| Nút Đặt lịch | `BookingRequest` đã có ✅ |
| Nút Chat AI | luồng chat đã có ✅ |

**Phase 1 dựng được landing thật từ dữ liệu đang có.** Banner / Giới thiệu /
Google Maps / SEO tuỳ chỉnh → Phase 2 (mới cần thêm cột).

### Thư viện
Thêm `jinja2` vào [backend/requirements.txt](backend/requirements.txt). Template
để ở `backend/app/templates/`.

### Rate limit & cache
Dùng lại `public_rate_limiter`. Thêm `Cache-Control: public, max-age=300` —
landing là trang công khai, không nên đụng DB mỗi lượt xem khi chạy Ads.

## 6. Định tuyến hạ tầng

| Môi trường | Cấu hình |
|---|---|
| Dev | Thêm `server.proxy` vào [frontend/vite.config.js](frontend/vite.config.js): `/book` → `http://localhost:8000` |
| Prod | Thêm `location /book/ { proxy_pass backend; }` vào [frontend/nginx.conf](frontend/nginx.conf) |

Mọi thứ **không phải `/book/*`** vẫn do SPA phục vụ như cũ → dashboard không đổi.

Cần đặt `PUBLIC_BASE_URL` đúng domain thật, vì `og:image`/`canonical` bắt buộc URL tuyệt đối.

## 7. Frontend

| Việc | File |
|---|---|
| Chat chuyển sang `/chat/:clinicSlug` (+ `/:branchSlug` tuỳ chọn) | [App.jsx](frontend/src/App.jsx) |
| `ClinicLandingPage.jsx` + `ChainPage.jsx` **xoá** (đã do backend render) | `pages/` |
| Nút "Chép" trỏ `/book/<clinic-slug>` | [PlatformPage.jsx](frontend/src/pages/PlatformPage.jsx), [OrgPage.jsx](frontend/src/pages/OrgPage.jsx) |
| UI quản lý cơ sở: slug, bật/tắt landing, tạm ngưng | trang Clinic / Settings |

## 8. Dữ liệu hiện có — "CareDesk 2" là bản ghi thử nghiệm

Kiểm tra DB (02/08/2026):

| | Clinic #1 CareDesk | Clinic #2 CareDesk 2 |
|---|---|---|
| PatientLead | 1 | **0** |
| Appointment | 0 | **0** |
| Conversation | 1 | **0** |
| Branch / Service / Doctor | 2 / 3 / 3 | 1 / 1 / 1 |
| Owner | owner@caredesk.ai | maiquoctuan1994@gmail.com |

CareDesk 2 có **0 bệnh nhân, 0 lịch hẹn, 0 hội thoại**; con số 1/1/1 đúng bằng
phần khung do checkbox *"Tạo sẵn cơ sở/dịch vụ/bác sĩ mẫu"* sinh ra; owner là
email cá nhân của chủ dự án.

→ Đề xuất ban đầu của tôi: xoá. **Chủ dự án quyết định: GIỮ và chuyển thành
Branch**, đổi tên thành một cơ sở thực tế hơn (vd. "CareDesk Hà Đông").

Lý do (thuyết phục hơn đề xuất của tôi): CareDesk bán cho **chuỗi phòng khám**,
nên môi trường demo phải có sẵn một chuỗi 2–3 cơ sở để demo được landing chuỗi,
danh sách chi nhánh, chat và booking theo từng cơ sở.

Việc chuyển thuộc **Giai đoạn C**, không làm trong A/B.

## 9. Thứ tự triển khai — **tách schema và dữ liệu nghiệp vụ**

Nguyên tắc: migration schema **dễ rollback**, merge dữ liệu nghiệp vụ **khó hoàn
tác**. Không trộn hai loại vào cùng một bước.

### Giai đoạn A — Schema (rollback được bằng `alembic downgrade`)
1. Backup DB
2. Migration: `slug_registry` + 3 cột Branch + `landing_enabled` cho Clinic/Organization
3. Backfill: sinh slug cho mọi Branch/Clinic/Organization đang có, nạp vào registry;
   chèn sẵn các slug hệ thống (`reserved`)
4. `slug.py` chuyển sang cấp/kiểm tra slug qua registry
5. **Verify**: mọi entity có slug, registry không trùng, link cũ vẫn resolve được

### Giai đoạn B — Landing (thuần tính năng, không đụng dữ liệu cũ)
6. Resolver + router `landing.py` + template Jinja2 → Clinic/Org landing trước
7. Branch landing + 301 cho URL legacy
8. Proxy dev (vite) + prod (nginx)
9. Chuyển chat sang `/chat/*`, dọn 2 page SPA cũ
10. UI bật/tắt landing cho từng cơ sở
11. Kiểm thử: preview Facebook/Zalo thật, Google Rich Results Test, link cũ còn sống

### Giai đoạn C — Dữ liệu nghiệp vụ (**tách riêng, chạy sau, có cổng kiểm tra**)
12. Xoá bản ghi thử nghiệm CareDesk 2 (xem mục 8)
13. Viết script `clinic_to_branch.py` cho khách thật sau này, theo đúng trình tự:
    `backup → tạo Branch → map dữ liệu sang branch_id → VERIFY → merge → archive Clinic cũ`
14. Clinic cũ **đánh dấu archived trước**, chỉ xoá hẳn sau khi vận hành ổn định

### Kết quả Giai đoạn C (đã chạy 03/08/2026)
`scripts/clinic_to_branch.py --source 2 --target 1 --branch-name "Cơ sở Bạch Mai" --apply`

- Clinic #2 -> Branch #3 của Clinic #1; clinic cũ archived (is_active=False, fee=0)
- **8 automation rule trùng bị xoá thay vì chuyển** — nếu chuyển thì mỗi bệnh nhân
  nhận follow-up 2 lần
- MRR 2.500.000đ -> 1.500.000đ (hết tính phí trùng)
- Slug clinic cũ trỏ sang chính cơ sở nó trở thành (301), không link nào chết
- Slug thương hiệu rút gọn: `chuoi-tham-my-caredesk-group-bcaf8a` -> `caredesk`

## 10. Rủi ro / điểm cần theo dõi

- **Link đã phát cho khách**: mọi URL `/book/*` cũ phải 301, không được 404. Kiểm thử riêng mục này.
- **Phòng khám không thuộc chuỗi** hiện *không có* landing (chỉ `/c/<slug>` vào thẳng chat) → Phase 1 sửa đúng lỗ hổng này.
- **`ClinicChatPage` đang đọc `orgSlug`** từ URL — đổi route phải rà lại chỗ này.
- **Cache 5 phút**: sửa thông tin phòng khám sẽ chậm hiện. Cân nhắc xoá cache khi lưu.
- Landing công khai lộ giá dịch vụ + danh sách bác sĩ → nên có cờ ẩn giá cho phòng khám không muốn (Phase 2).
