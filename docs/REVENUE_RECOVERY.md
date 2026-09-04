# Revenue Recovery Engine

Vòng lặp: **Detect → Act → Recover → Prove → Learn**.

Phần này trả lời một câu hỏi mà phần còn lại của sản phẩm không trả lời: *phòng
khám đang để rơi bao nhiêu tiền, và CareDesk kéo lại được bao nhiêu trong số đó.*

Tài liệu này chỉ ghi những quyết định **dễ bị làm sai về sau**. Chi tiết kỹ thuật
nằm trong docstring của [`backend/app/services/revenue_recovery.py`](../backend/app/services/revenue_recovery.py).

---

## 1. Sáu nhóm cơ hội

| Nhóm | Phát hiện khi | Giá trị lấy từ | Loại tiền |
|---|---|---|---|
| `overdue_revisit` | Đã khám xong dịch vụ có chu kỳ, quá hạn, chưa có lịch mới | `services.price` | Tiền mới |
| `lost_booking` | `BookingRequest` quá 2 ngày chưa thành lịch hẹn | Giá dịch vụ | Tiền mới |
| `no_show_recovery` | Hủy / không đến, quá 14 ngày chưa đặt lại | Giá dịch vụ | Tiền mới |
| `high_intent_lost_lead` | Có event `price_asked`, im trên 7 ngày, chưa từng đặt | Giá trị trung bình một lượt khám | Tiền mới |
| `package_expiring` | Gói còn buổi, hết hạn trong 30 ngày | Số buổi còn × đơn giá đã trả | **Đã thu** |
| `stalled_package` | Gói còn buổi, trên 45 ngày không đến | Số buổi còn × đơn giá đã trả | **Đã thu** |

## 2. Ba ràng buộc trung thực (đừng gỡ)

### 2.1. Tiền khách đã trả không phải doanh thu thu hồi

Gói liệu trình còn 4 buổi chưa dùng **không** phải 8 triệu chờ thu — phòng khám
đã cầm tiền rồi. Rủi ro ở đó là hoàn tiền và mất khách, không phải doanh số.

Hai nhóm `package_*` mang `value_kind = AT_RISK_DELIVERED` và được báo cáo ở ô
riêng, **không bao giờ cộng vào `recoverable_gross`**. Cộng chung là cách nhanh
nhất để thổi phồng dashboard, nên nó có test riêng
(`test_money_already_paid_is_never_counted_as_recoverable`).

### 2.2. Xác suất là giả định cho tới khi đo được

Dưới `MIN_RESOLVED_FOR_OWN_RATE = 20` ca đã kết thúc, hệ thống dùng `BASE_RATES`
— con số cố ý đặt thấp — và API trả `probability_is_measured = false` để màn hình
hiển thị nhãn **"Giả định"**. Vượt ngưỡng đó thì dùng tỷ lệ thật của chính phòng
khám. Không có mô hình học máy nào, và không chỗ nào giả vờ là có.

Mỗi cơ hội kèm `reasons` — vì sao ra con số đó. Một con số không giải thích được
sẽ bị lễ tân bỏ qua ngay lần đầu thấy nó sai, và luôn có một dòng trông sai.

### 2.3. Nhóm đối chứng là thứ khiến "doanh thu thu hồi" thành một khẳng định

`HOLDOUT_RATE = 10%` cơ hội **cố ý không liên hệ**.

Khách vốn dĩ sẽ quay lại thì quay lại ở cả hai nhóm. Chỉ phần **chênh lệch** mới
là công của sản phẩm. Không có nhóm này thì "CareDesk mang về 186 triệu" là một
lời khoe không kiểm chứng được — đúng loại lỗi mà toàn bộ thiết kế này sinh ra để
tránh.

Vì vậy:

* Gán nhóm bằng **hash ổn định**, không phải random. Quét chạy hàng giờ; nếu
  random thì mỗi lần quét lại đảo người giữa hai nhóm và phép đo mất sạch ý nghĩa.
* Hàng đợi **không hiển thị** cơ hội trong nhóm đối chứng. Lễ tân nhìn thấy là sẽ
  gọi.
* `POST /contacted` trên cơ hội đối chứng trả **409**, kể cả khi gọi thẳng API.
* Dưới `MIN_HOLDOUT_FOR_MEASUREMENT = 30`, `recovery_performance` trả
  `measurable: false`, `net_attributable: null`, `roi: null` — **không** đưa ra
  ước lượng thay thế.

> Ai đó sẽ đề nghị "liên hệ nốt nhóm đối chứng cho hết việc". Đồng ý là mất khả
> năng chứng minh sản phẩm có tác dụng — cũng là mất luôn lý do phòng khám tiếp
> tục trả tiền.

## 3. Hai con số, đừng nhầm

| Trường | Nghĩa |
|---|---|
| `gross_recovered` | Tổng tiền quay lại sau khi liên hệ. **Bao gồm cả khách vốn dĩ sẽ quay lại.** Không phải khẳng định nhân quả. |
| `net_attributable` | Phần chênh so với nhóm đối chứng. Con số duy nhất được phép nói là "nhờ CareDesk". |

## 4. Chu kỳ tái khám phải do phòng khám khai

`services.revisit_interval_days` mặc định **NULL = làm một lần, không bao giờ
nhắc**. Hệ thống không suy đoán chu kỳ từ dữ liệu, và với phòng khám mới thì cũng
không có gì để suy.

Đoán sai ở đây không phải lỗi thống kê mà là nhắn tin cho người chưa đến hạn —
với đúng nhóm khách phòng khám muốn giữ nhất. Màn hình có ô cảnh báo khi chưa
dịch vụ nào khai báo, vì nếu không thì dashboard chỉ trông như bị hỏng.

## 5. Không tự động gửi

`POST /contacted` **ghi nhận** việc đã liên hệ, không gửi gì cả. Tin nhắn là bản
nháp để nhân viên đọc, sửa rồi tự gửi.

Lý do: nội dung mời chào gửi qua template ZNS là nội dung giao dịch — vi phạm
chính sách Zalo OA. Một engine tự gửi ở phiên bản đầu là phiên bản làm phòng khám
mất kênh Zalo. Bản nháp cũng **không bao giờ chứa khuyến mãi**: biên lợi nhuận là
của phòng khám, không phải thứ sản phẩm được quyền đem cho.

## 6. Vận hành

* Quét tự động mỗi giờ trong `reminder_loop` (`_detect_revenue_opportunities`),
  bọc try/except theo từng phòng khám để một tenant dữ liệu lạ không chặn cả hệ.
* Quét **idempotent**: chạy lại không sinh bản ghi mới, không mở lại ca đã xử lý.
* `POST /api/v1/revenue/detect` để quét ngay, không phải chờ.

## 7. Chưa làm

Nằm ngoài phạm vi lần này, ghi lại để không ai tưởng đã có:

* Campaign tự sinh từ cơ hội, và AI Sales Agent có chính sách Auto / Cần duyệt /
  Chỉ người.
* Chuỗi attribution ở mức từng cơ hội (hiện `RevenueRecord.source` vẫn ở mức lượt).
* Xếp hạng Hot / Warm / Cold, và CPL / CAC / ROAS theo chi phí quảng cáo.
* Học xác suất theo từng đặc trưng khách. Hiện chỉ là tỷ lệ theo nhóm — đủ dùng
  cho MVP và giải thích được, đó là điểm mạnh chứ không phải hạn chế tạm thời.
