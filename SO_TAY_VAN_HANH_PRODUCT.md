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

> ### ⚠️ Ba điều PHẢI xác nhận với Zalo trước khi lập kế hoạch dựa vào chúng
>
> Những mục dưới đây **chưa được kiểm chứng bằng tài liệu chính thức**. Đừng đưa
> vào cam kết với khách hàng cho tới khi tự xác nhận tại
> [developers.zalo.me](https://developers.zalo.me/).
>
> **1. Điều kiện tạo OA Test / sandbox.** Có nguồn cho rằng OA Test chỉ dùng được
> sau khi OA đã xác thực và admin nhận email phản hồi từ Zalo. Nếu đúng thì OA
> Test **không** bỏ qua được bước xác thực (vốn cần giấy phép doanh nghiệp), và
> toàn bộ kế hoạch "tạm thời dùng OA Test" sẽ không mở được. **Đây là câu hỏi
> quan trọng nhất — hỏi trước tiên.**
>
> **2. OA Test có gửi được tới số bất kỳ không?** Giả thuyết: chỉ gửi tới các số
> đã đăng ký làm tester. Nếu đúng thì không dùng OA Test để chạy pilot với bệnh
> nhân thật được. Chưa có nguồn xác nhận.
>
> **3. Tên gọi dịch vụ.** Theo thông tin hiện có, nhiều trang tài liệu ZNS đã
> **ngừng cập nhật**, và **từ 01/01/2026 ZNS được hợp nhất vào ZBS Template
> Message**. Tài liệu này và code vẫn dùng chữ "ZNS" như **tên gọi cũ (legacy)** —
> xem mục thuật ngữ bên dưới.

**Khi dùng OA Test, khai thêm `"zns_sandbox": true`:**

```json
{ "zns_template_id": "...", "zns_sandbox": true }
```

Vì sao cần cờ này: hệ thống xác định "tin đã tới bệnh nhân thật hay chưa" **dựa
trên cờ khai báo, không dựa vào phản hồi của Zalo**. Nếu một OA Test trả về
thành công giống OA thật (giả thuyết #2 ở trên — chưa xác nhận), thì thiếu cờ
này CareDesk sẽ tính đó là một lần gửi tới bệnh nhân và tắt cảnh báo trên
Dashboard. Khai cờ là cách an toàn bất kể Zalo hành xử thế nào — có test khoá
hành vi này (`tests/test_delivery_honesty.py`).

Cần cả `access_token` **và** `zns_template_id`. Chỉ có OA thôi là chưa đủ — đây
là lý do phổ biến nhất khiến nhắc lịch im lặng ngừng chạy.

### Thuật ngữ: "ZNS" trong code là tên gọi cũ

Theo thông tin hiện có, ZNS đã được hợp nhất vào **ZBS Template Message** từ
01/01/2026. Trong CareDesk, các tên sau **giữ nguyên** vì chúng là khoá lưu trong
`ChannelIntegration.extra_config` — đổi tên sẽ làm hỏng cấu hình của các phòng
khám đã kết nối:

| Tên trong code | Nghĩa |
|---|---|
| `zns_template_id` | id template đã được Zalo duyệt |
| `zns_sandbox` | đang trỏ vào OA Test |
| `zns_is_configured()` | đã đủ điều kiện gửi chưa |

Khi đọc tài liệu Zalo hiện hành, hiểu "ZNS" ở đây là **ZBS Template Message**.
Nếu Zalo đổi endpoint hoặc định dạng payload, chỗ cần sửa là
`ZNS_SEND_URL` và `_send` trong
[channel_gateway.py](backend/app/services/channel_gateway.py) — **cần kiểm tra
lại endpoint hiện hành trước khi kết nối OA thật đầu tiên.**

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
