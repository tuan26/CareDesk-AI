# Sổ tay vận hành trước khi nhận khách thật

Ba việc dưới đây là điều kiện để mở cho phòng khám đầu tiên. Không phải "nên
làm" — là **điều kiện**, vì cả ba đều chỉ hỏng đúng vào lúc bạn không còn đường lùi.

---

## 1. Sao lưu và diễn tập phục hồi

```bash
.venv/Scripts/python -m scripts.backup dump      # sao lưu ngay
.venv/Scripts/python -m scripts.backup list
.venv/Scripts/python -m scripts.backup restore backups/<file>
.venv/Scripts/python -m scripts.backup drill     # ← việc quan trọng nhất
```

`drill` sao lưu, phục hồi lại chính bản đó, rồi **đếm số dòng trước và sau** để
chứng minh dữ liệu còn nguyên. Một bản sao lưu chưa từng được phục hồi thì
không phải bản sao lưu: thiếu `pg_restore`, sai thông tin đăng nhập, file bị cắt
cụt — tất cả đều trông y hệt như thành công cho tới ngày bạn cần đến nó.

Script chạy trên bất kỳ `DATABASE_URL` nào: SQLite ở máy bạn dùng API backup của
sqlite3 (không phải copy file — copy một database đang ghi tạo ra file mở được
nhưng hỏng ngầm), Postgres dùng `pg_dump --format=custom`.

**Đã diễn tập lần đầu trên SQLite: đạt.** Trên Postgres cần cài
`postgresql-client` rồi chạy lại — bắt buộc làm trước khi có bệnh nhân thật.

`drill` cố tình phục hồi đè lên chính database đang trỏ tới. Diễn tập trên một
bản sao chỉ chứng minh bản sao chạy được, không chứng minh đường phục hồi thật
chạy được. Nó tự chặn nếu `ENVIRONMENT=production`.

> `backups/` đã nằm trong `.gitignore` — chứa dữ liệu bệnh nhân thật, tuyệt đối
> không commit.

**Lịch cần thiết lập:** bật snapshot tự động hàng ngày của nhà cung cấp
Postgres, và chạy `drill` trên staging **mỗi lần đổi hạ tầng**.

---

## 2. Staging giống production

14 migration hiện chưa từng chạy trên Postgres — mới chỉ chạy trên SQLite. Sự
khác biệt không nhỏ: `d0e1f2a3b4c5` tạo **partial unique index**, cú pháp
`sqlite_where` và `postgresql_where` khác nhau, và `c9d0e1f2a3b4` so sánh cột
boolean mà SQLite lưu 0/1 còn Postgres lưu true/false.

Dựng staging **cùng nhà cung cấp, cùng phiên bản Postgres** với production:

```bash
ENVIRONMENT=staging
DATABASE_URL=postgresql://...        # instance riêng, KHÔNG dùng chung production
SEED_DEMO_DATA=false
PUBLIC_BASE_URL=https://staging.<domain>
BACKEND_CORS_ORIGINS=https://staging.<domain>
SMS_PROVIDER=                        # để trống: staging không được nhắn cho người thật
```

Thứ tự kiểm tra:

1. Deploy staging → migration tự chạy → `/health` trả `{"status":"ok"}`
2. Nạp một bản sao lưu **có hình dạng dữ liệu thật** rồi chạy lại migration
3. `python -m scripts.backup drill`
4. Đăng ký một phòng khám mới, đi hết wizard, chat thử, chốt một lịch
5. Chỉ khi cả 4 bước xanh mới đụng vào production

> **Để `SMS_PROVIDER` trống trên staging.** Một vòng lặp automation trên staging
> với dữ liệu thật sẽ nhắn cho bệnh nhân thật. Hệ thống giờ báo rõ "chưa gửi
> được" thay vì âm thầm giả vờ, nên bỏ trống là an toàn.

---

## 3. Kênh gửi tin — test được gần hết mà chưa cần tài khoản thật

Nhắc lịch là một nửa lời hứa "giảm no-show". Nhưng **không phải chờ có OA thật
mới test được luồng**.

### Ba môi trường, ba nhà cung cấp

| Môi trường | Cấu hình | Gọi API thật? | Tới máy khách? |
|---|---|---|---|
| **dev** | `SMS_PROVIDER=mock` | không | không |
| **staging** | `SMS_PROVIDER=esms` + `SMS_SANDBOX=true` | **có** | không |
| **production** | `SMS_PROVIDER=esms` + `SMS_SANDBOX=false` | có | **có** |

`Sandbox=1` của eSMS: request được kiểm tra và trả lời như thật, nhưng tin không
lưu, **không tính phí, không gửi tới máy khách**. Đây là thứ nên dùng cho
staging chứ không phải mock — nó kiểm chứng cả thông tin đăng nhập thật, định
dạng payload thật lẫn đường xử lý lỗi thật, những thứ mock không đụng tới.

> **SpeedSMS không có sandbox.** Không tìm thấy tài liệu xác nhận, nên tôi
> **cố tình không** cài chế độ sandbox cho nó. Tưởng tin đang bị chặn trong khi
> thực tế nó vẫn gửi và vẫn tính tiền thì còn tệ hơn là không có sandbox. Muốn
> test thì dùng `mock` hoặc eSMS sandbox.

### Zalo: kênh thuộc về phòng khám, không thuộc về CareDesk

Đây là điểm quan trọng nhất của cả mục này, và nó xuất phát từ một ràng buộc
thực tế: **CareDesk không có giấy phép doanh nghiệp riêng**, nên không tự xin
được OA.

Nhưng đó không phải vấn đề cần khắc phục — nó là **kiến trúc đúng**:

- OA và brandname phải mang thương hiệu **phòng khám**, không phải "CareDesk".
  Bệnh nhân nhận tin nhắn từ phòng khám họ đã đặt lịch, không phải từ một nhà
  cung cấp phần mềm họ chưa từng nghe tên.
- Giấy phép kinh doanh dùng để xác thực OA là **của phòng khám**.
- Chi phí ZNS tính trên OA của phòng khám.
- Code đã làm đúng như vậy từ đầu: `ChannelIntegration` gắn theo `clinic_id`,
  mỗi phòng khám có token và template riêng.

**Hệ quả về thời gian:** đồng hồ Zalo **bắt đầu chạy từ lúc ký được phòng khám**,
không phải trước đó. Nghĩa là **quy trình bán hàng và demo tuyệt đối không được
phụ thuộc vào ZNS chạy thật** — nếu không bạn sẽ kẹt ở thế không demo được nên
không ký được khách, mà không ký được khách thì không xin được OA.

OA Test dùng chung endpoint với OA thật — chỉ khác `access_token` và
`zns_template_id`, **không cần sửa code**.

> ### 🔴 ZBS là dependency BỊ CHẶN cho tới khi có một OA đã xác thực
>
> Đối chiếu tài liệu chính hành Zalo (bản build 06/08/2026):
>
> - OA có thể **tạo trước**, nhưng phải nộp hồ sơ xác thực trong **14 ngày**;
>   quá hạn **khoá vĩnh viễn**.
> - Chính sách ZBS Template Message (cập nhật 09/07/2026) định nghĩa OA dùng cho
>   dịch vụ này là **"tài khoản xác thực của doanh nghiệp"**, và bước 1 của quy
>   trình là *"Đăng ký và xác thực tài khoản OA"*.
> - **Không có** loại tài khoản riêng nào tên "OA Test" trong tài liệu hiện hành.
>   Cái Zalo cung cấp là **development mode của chính API ZBS** — một chế độ gửi,
>   không phải một loại tài khoản.
>
> **Hệ quả:** không có đường vòng nào cho phép một đơn vị chưa có hồ sơ pháp
> nhân dùng ZBS. Kế hoạch "tạm thời 100% OA Test" **không khả thi**. Coi ZBS là
> bị chặn cho tới khi ký được phòng khám và dùng pháp nhân của họ.

### Development mode: chỉ gửi được cho chính admin

Tài liệu ZBS ghi nguyên văn: *"Chế độ development chỉ hỗ trợ gửi thử tin qua SĐT
đến quản trị viên của ứng dụng hoặc quản trị viên của OA."*

Nghĩa là development mode **kiểm chứng được tích hợp, nhưng không chạy được
pilot** — bệnh nhân thật không nhận được gì. Bật bằng:

```json
{ "zns_template_id": "...", "zns_sandbox": true }
```

Cờ này không chỉ là nhãn nội bộ: nó thêm `"mode": "development"` vào payload gửi
Zalo, đồng thời giữ `can_reach_phone = false` để Dashboard không báo sẵn sàng.

> Lưu ý cả ở production: ZBS **không phải API broadcast**. Chính sách 09/07/2026
> quy định người nhận phải là người *"đã giao dịch trước đó với Đối Tác"*, số
> điện thoại phải gắn với tài khoản Zalo, và Zalo có quyền yêu cầu bằng chứng về
> quan hệ giao dịch. Với phòng khám thì bệnh nhân đã đặt lịch là hợp lệ — nhưng
> đừng bán tính năng "gửi hàng loạt cho danh sách số bất kỳ".

### Payload ZBS (đã đối chiếu tài liệu, đã sửa trong code)

```
POST https://business.openapi.zalo.me/message/template
access_token: <token>
```

| Field | Bắt buộc | Ghi chú |
|---|---|---|
| `phone` | ✓ | dạng `84987654321` — **không** dùng `0987654321` |
| `template_id` | ✓ | id template đã duyệt |
| `template_data` | ✓ | object biến của template; schema khác nhau theo từng template |
| `tracking_id` | ✓ | id do hệ thống bạn sinh, dùng để đối soát |
| `sending_mode` | | `1` mặc định; `3` chỉ cho OA được whitelist |
| `mode` | | `"development"` khi test |

**Ba lỗi trong code đã được sửa nhờ đối chiếu này:** thiếu `tracking_id` (bắt
buộc), `phone` chưa chuẩn hoá về mã quốc gia, và `template_data` bị hardcode
thành `{"content": <câu văn>}` — trong khi ZBS **không có trường văn bản tự do**.

### Template có biến riêng, không nhận văn bản tự do

Mỗi template được duyệt có bộ biến riêng (`customer`, `thoi_gian`, ...), nên câu
nhắc lịch phải được **tách thành từng phần**. Khai ánh xạ trong `extra_config`:

```json
{
  "zns_template_id": "7895417a7d3f9461cd2e",
  "zns_template_data": {
    "customer":  "{patient_name}",
    "thoi_gian": "{time} ngày {date}",
    "dia_chi":   "{branch_address}"
  }
}
```

Các biến dùng được: `patient_name`, `clinic_name`, `branch_name`,
`branch_address`, `service_name`, `doctor_name`, `date`, `time`, `confirm_url`,
`cancel_url`.

Không khai ánh xạ thì hệ thống gửi thẳng các biến trên theo đúng tên của chúng —
chỉ đúng nếu template được viết theo bộ tên này. Gõ sai một biến thì chỉ biến đó
rỗng và có log cảnh báo, **không làm hỏng cả lượt gửi**.

`tracking_id` sinh theo dạng `caredesk-<appointment_id>-<kind>` — ổn định theo
từng lời nhắc, nên một lần gửi lại nhận diện được là **cùng một tin**, không phải
tin mới.

### Thuật ngữ: "ZNS" trong code là tên gọi cũ

ZNS đã hợp nhất vào **ZBS Template Message** từ 01/01/2026; tài liệu ZNS cũ được
chính Zalo đánh dấu không còn cập nhật. Các tên `zns_template_id`, `zns_sandbox`,
`zns_is_configured()` **giữ nguyên** vì là khoá lưu trong
`ChannelIntegration.extra_config` — đổi tên sẽ làm hỏng cấu hình của phòng khám
đã kết nối. Đọc "ZNS" ở đây là ZBS Template Message.

**Endpoint đã xác minh là vẫn đúng** tính tới 10/08/2026. Phần cần kiểm tra khi
kết nối OA thật đầu tiên không phải URL, mà là: quyền của App, OA đã xác thực
chưa, template có thuộc ZBS không, và `template_data` có khớp biến của template
không.

### Vậy demo cho phòng khám bằng gì khi chưa có OA?

Trước khi ký được khách đầu tiên, bạn có **email** — và chỉ cần một tài khoản
Gmail với app password, không cần giấy tờ gì:

```bash
SMTP_USER=ban@gmail.com
SMTP_PASSWORD=<app password 16 ký tự>
```

Email là kênh **thật, chạy được ngay hôm nay**: bệnh nhân nhận thư có link xác
nhận/huỷ hoạt động đầy đủ. Đủ để demo trọn vòng cho chủ phòng khám xem — gửi vào
chính email của họ trong buổi demo là thuyết phục nhất.

Hệ thống nói đúng về giới hạn này: khi chỉ có email, Dashboard hiện *"Mới chỉ
nhắc lịch được qua email — phần lớn bệnh nhân không đọc email nhắc lịch"* chứ
không báo là nhắc lịch đã sẵn sàng.

Và khi đang chạy kênh thử nghiệm (OA Test hoặc SMS sandbox/mock), cảnh báo đổi
thành *"Đang chạy kênh THỬ NGHIỆM — tích hợp hoạt động, nhưng tin nhắn KHÔNG tới
bệnh nhân thật"*. Đây là cảnh báo giữ cho một pilot không vô tình khởi động ở
trạng thái đó.

### Chốt chặn: production không được dùng đồ giả

App **từ chối khởi động** nếu `ENVIRONMENT=production` mà còn `SMS_PROVIDER=mock`
hoặc `SMS_SANDBOX=true`. Một sender giả trên production là trường hợp tệ nhất:
phòng khám thấy lời nhắc được đánh dấu đã xử lý, không bệnh nhân nào nhận được
gì, và trên màn hình không có gì trông sai cả.

Vì cùng lý do đó, **chọn nhà cung cấp là cấu hình môi trường, không phải feature
flag theo phòng khám** — một phòng khám không bao giờ được tự chuyển mình vào
sandbox rồi ngừng liên lạc với chính khách của họ.

### Trong lúc chờ tài khoản: hệ thống nói thật

Dashboard hiện cảnh báo đỏ *"Chưa kết nối Zalo ZNS hoặc SMS — tin nhắn nhắc lịch
KHÔNG được gửi đi"*. Mock và sandbox **không** làm tắt cảnh báo này
(`can_reach_phone` loại trừ cả hai) — đèn xanh trong khi mọi tin bị sandbox nuốt
chính là kiểu tự tin sai lầm mà toàn bộ phần này sinh ra để chặn.

### Outbox: xem được từng lời nhắc hỏng vì sao

Bảng `reminder_logs` ghi **mọi lần thử**, không chỉ lần thành công:

| Cột | Ý nghĩa |
|---|---|
| `medium` | `phone` / `email` — hỏng SMS thì email vẫn gửi, và ngược lại |
| `status` | `sent` / `failed` |
| `attempts` | trần 3 lần |
| `last_error` | lý do cụ thể |

Quy tắc quan trọng nhất ở đây: **chưa cấu hình kênh thì không tính là một lần
thử**. Nghĩa là ba tuần chờ Zalo duyệt OA, mọi lời nhắc dồn lại vẫn nguyên vẹn và
**tự động gửi hết ngay lượt quét đầu tiên** sau khi bạn điền thông tin — không
mất lịch nào.

Ngược lại, nhà cung cấp **nhìn vào tin rồi từ chối** (sai số điện thoại, brandname
bị khoá, hết tiền) thì dừng ngay, không thử lại: thử lại chỉ mua đúng câu trả lời
cũ với đúng cái giá cũ.

```sql
-- các lời nhắc chưa gửi được và lý do
SELECT kind, medium, attempts, last_error FROM reminder_logs WHERE status='failed';
```

---

## Kiểm tra nhanh trước ngày mở

```bash
.venv/Scripts/python -m pytest tests/            # phải xanh toàn bộ
.venv/Scripts/python -m scripts.backup drill     # phải "DIỄN TẬP ĐẠT"
curl -s $DOMAIN/health                           # {"status":"ok"}
```

Trên giao diện, đăng nhập bằng tài khoản chủ phòng khám:

- Dashboard **không còn cảnh báo đỏ nào**
- Hai thẻ "Lịch hẹn / tháng" và "Tỷ lệ khách không đến" hiện số liệu ban đầu
- Chat thử: hỏi giá một dịch vụ → AI trả đúng giá trong bảng
- Chat thử: hỏi một câu ngoài dữ liệu → phải **chuyển lễ tân**, không bịa
- Đặt thử một lịch → nếu có thu cọc, khung giờ đó phải biến mất khỏi danh sách
  trống ngay lập tức
