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

## 3. Kênh gửi tin — việc duy nhất bạn không kiểm soát được thời gian

Nhắc lịch là một nửa lời hứa "giảm no-show". Không có kênh thì không có nhắc lịch.

| Kênh | Cần gì | Mất bao lâu |
|---|---|---|
| Zalo ZNS | OA đã duyệt + `zns_template_id` được Zalo phê duyệt | vài ngày → vài tuần |
| SMS | Tài khoản eSMS/SpeedSMS + brandname đăng ký | vài ngày |
| Email | SMTP | ngay |

Tích hợp đã viết xong cả ba. Khi có tài khoản, chỉ cần điền:

```bash
SMS_PROVIDER=esms          # hoặc speedsms
SMS_API_KEY=...
SMS_SECRET_KEY=...         # chỉ eSMS cần
SMS_BRANDNAME=CAREDESK
```

Zalo ZNS cấu hình theo từng phòng khám trong **Cài đặt → Kênh kết nối**, cần cả
`access_token` **và** `zns_template_id`. Chỉ có OA thôi là chưa đủ — đây là lý do
phổ biến nhất khiến nhắc lịch im lặng ngừng chạy.

**Trong lúc chờ:** hệ thống nói thật. Dashboard hiện cảnh báo đỏ "Chưa kết nối
Zalo ZNS hoặc SMS — tin nhắn nhắc lịch KHÔNG được gửi đi", và **không ghi nhận
là đã gửi**. Nghĩa là mọi lịch hẹn chưa nhắc được sẽ **tự động nhắc bù** ngay khi
bạn cắm kênh vào — không mất lịch nào.

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
