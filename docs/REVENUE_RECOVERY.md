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

---

# Attribution v1

Chuỗi: `Opportunity → Action → Response → Appointment → RevenueRecord`.

`GET /revenue/opportunities/{id}/chain` trả về đúng chuỗi đó. Chủ phòng khám
không tin một con số thì phải lần ngược được tới buổi khám và phiếu thu — không
có nó thì dashboard chỉ còn hai lựa chọn: tin hoặc bỏ qua.

## 3.1. Một lần đặt lịch = một lần thu hồi

Đây là lỗi đã từng ship và là lý do lớp này tồn tại.

Một khách có thể mang **nhiều cơ hội mở cùng lúc**: vừa quá hạn tái khám, vừa có
yêu cầu đặt lịch bị bỏ quên, vừa từng no-show. Bản đầu đóng cả ba khi khách đặt
một lịch → **một buổi ₫2.000.000 hiện thành ₫6.000.000 thu hồi**.

Giờ: đúng **một** cơ hội được ghi công (`_match_strength` — ưu tiên trùng dịch
vụ, rồi đã liên hệ, rồi liên hệ gần nhất; hoàn toàn tất định). Các cơ hội còn
lại chuyển `superseded`: vẫn là miss thật nên không xóa, nhưng **bị loại khỏi cả
doanh thu lẫn tỷ lệ chuyển đổi** — chúng không phải bằng chứng cho bên nào.

## 3.2. Đặt lịch chưa phải là tiền

`booked` và `recovered` là hai trạng thái khác nhau:

| Trạng thái | Nghĩa | `recovered_amount` |
|---|---|---|
| `booked` | Đã có lịch hẹn | `NULL` |
| `recovered` | Đã khám xong **và** có `RevenueRecord` | Số tiền **thật** trong phiếu thu |
| `lost` (`no_show`) | Đặt rồi không đến | — |

Tháng khách đặt lịch thường không phải tháng khách đến. Lấy `estimated_value`
điền vào cột đã thu là cách dashboard bắt đầu lệch với sổ ngân hàng.

Buổi khám trừ vào gói đã mua → `recovered` với số tiền **0**: buổi khám có thật,
nhưng tiền đã thu từ trước, không được tính hai lần.

## 3.3. Bốn mức quy kết

| Loại | Khi nào | Được tính cho CareDesk? |
|---|---|---|
| `direct` | Đặt lịch trong `DIRECT_WINDOW_DAYS = 3` ngày sau lần liên hệ đầu | ✅ |
| `assisted` | Đặt muộn hơn, trong `ATTRIBUTION_WINDOW_DAYS = 30` ngày | ✅ (yếu hơn, để riêng) |
| `organic` | **Chưa hề liên hệ**, khách tự quay lại | ❌ — đây là baseline |
| `unknown` | Ngoài cửa sổ quy kết, hoặc dữ liệu có từ trước lớp này | ❌ |

Không có trần thời gian thì mọi khách từng quay lại cuối cùng đều ghi công cho
một cơ hội cũ nào đó, và doanh thu thu hồi **tự lớn lên**.

Lần nhắc sau **không** reset đồng hồ quy kết. Nếu không, một lead liên hệ tháng
1 nhắc lại tháng 3 sẽ trông như vừa thắng trong tháng 3.

## 3.4. Funnel đếm từ dữ liệu riêng của từng bước

`Contacted → Responded → Booked → Completed → Revenue`, mỗi bước có nguồn riêng:
`RevenueAction` cho lần liên hệ, **tin nhắn của chính khách** cho phản hồi,
`Appointment` cho đặt lịch, `RevenueRecord` cho tiền. Không bước nào suy ra từ
bước trước, nên khoảng rơi giữa hai bước là thật và đáng đọc.

Funnel chỉ đếm người **đã thực sự được liên hệ**. Khách tự quay lại không nằm
trong funnel outreach — cho vào sẽ khiến tỷ lệ liên hệ→đặt lịch trông như tin
nhắn có tác dụng trong khi chưa gửi gì.

---

# Controlled Pilot

Mục tiêu 2–4 tuần đầu **không phải kiếm nhiều tiền**, mà chứng minh 5 điều:
detect đúng → owner thấy cơ hội có thật → contact tạo booking → booking tạo
doanh thu → doanh thu **tăng thêm** so với nhóm đối chứng.

## P1. Trước khi bật pilot

Chạy `bash scripts/check_migrations.sh` — dựng DB trắng, so schema với model,
**diễn tập rollback**, chạy lại upgrade. Bước rollback là bước đáng giá nhất:
nó đã bắt được một `downgrade()` gãy giữa chừng trên SQLite (drop cột khi index
còn trỏ vào), đúng trạng thái không ai muốn phát hiện lúc đang cố hoàn tác một
bản deploy hỏng.

Sau đó kiểm `GET /revenue/readiness`. `needs_attention = true` nghĩa là detector
lớn nhất đang tắt.

## P2. `detection_precision` — tìm nhiều ≠ tìm đúng

Khi lễ tân xử lý một ca, hỏi thêm một câu: **"Cơ hội này có thực sự đáng thu hồi
không?"** → `yes` / `no` / `unsure`.

```
Engine tìm 50 → lễ tân nói có thật 41 → precision ≈ 82%
```

Tỷ lệ chuyển đổi **không** trả lời được câu này: một cơ hội hoàn toàn có thật
vẫn có thể không chốt được, và một cơ hội tồi tình cờ chốt được cũng không nói
lên điều gì tốt về bộ phát hiện. `unsure` là câu trả lời thật và bị **loại khỏi**
phép tính precision chứ không bị ép về một phía.

Chưa ai đánh giá → `detection_precision: null`. Hệ thống không tự chấm điểm mình.

## P3. `recovery_rate` — cẩn thận cái mẫu

```
Giá trị cơ hội   ₫42M
Thực thu         ₫27.4M
Recovery rate    65.2%
```

Mẫu **chỉ gồm**: cơ hội sinh tiền mới (`NEW_REVENUE`), giá trị > 0, ngoài nhóm
đối chứng, đã có kết quả (`recovered` hoặc `lost`).

Nằm ngoài mẫu: gói khách đã trả tiền (không thể "thu hồi" thứ đã thu), cơ hội
`superseded`, cơ hội còn mở (chưa phải câu trả lời — tính là thua thì mọi tỷ lệ
đều bắt đầu từ 0 rồi bò lên theo tốc độ đóng tồn).

Tỷ lệ **không bị chặn ở 100%**. Vượt 100% là một phát hiện — ước lượng đang thấp
— và chặn lại là giấu đúng thứ đáng biết.

## P4. `revenue_per_opportunity` — con số để định giá

Chia cho **toàn bộ** cơ hội trong mẫu, kể cả ca hỏng. Chia cho riêng ca thắng sẽ
trả lời "một ca thắng đáng bao nhiêu", câu chẳng ai cần.

Sau vài phòng khám, đây là cơ sở thực tế để nói *"một opportunity của CareDesk
đáng khoảng X đồng"* — và từ đó mới bàn được giá.

## P4b. `₫0` không tự nó có nghĩa gì

`monthly_fee = 0` có ba nghĩa hoàn toàn khác nhau: **chưa cấu hình giá**, **pilot
miễn phí**, **được tài trợ**. Để logic nghiệp vụ đoán ý nghĩa của số 0 là cách
tạo ra một con số ROI không ai kiểm chứng được.

Nên nghĩa được **lưu**, không suy ra:

| `pricing_mode` | `roi_status` | Màn hình hiện |
|---|---|---|
| `pilot_free` | `pilot_free` | "Pilot miễn phí — chưa tính ROI" |
| `sponsored` | `sponsored` | "Chi phí do bên khác tài trợ" |
| `unconfigured` | `unconfigured_pricing` | "Chưa cấu hình phí thuê bao" |
| `paid`, đủ đối chứng | `ok` | `8.4x` |
| `paid`, thiếu đối chứng | `insufficient_holdout` | "Cần ≥30 ca đối chứng" |

`roi: null` kèm `roi_status` — vì một ô trống không lời giải thích đọc như lỗi,
còn pilot miễn phí không phải lỗi.

**Miễn phí không làm giá trị mất đo được.** `net_attributable` vẫn báo cáo bình
thường trong pilot miễn phí; chỉ có *tỷ suất trên một mức giá không ai trả* là
không tồn tại.

Đặt qua `PUT /platform/clinics/{id}/pilot-terms` — phía nhà cung cấp, không phải
phía phòng khám: để chủ phòng khám tự khai mình đang dùng miễn phí là để họ tự
ký hoá đơn của mình. Chuyển sang `paid` mà `monthly_fee = 0` bị **từ chối**: đó
đúng là tổ hợp sẽ lặng lẽ chia cho số 0 rồi gọi kết quả là lợi nhuận.

Backfill khi nâng cấp cố ý dè dặt: chỉ phòng khám **đã có phí > 0** thành
`paid`, còn lại thành `unconfigured` — đoán rằng một số 0 nghĩa là pilot miễn
phí chính là kiểu suy diễn mà cột này sinh ra để loại bỏ.

## P5. Ba tầng dữ liệu, ba ngưỡng khác nhau

| Tầng | Cần | Mở khoá |
|---|---|---|
| A — Detection | 30–50 ca **có kết quả** | `detection_precision` |
| B — Conversion | funnel chạy đủ 5 bước | benchmark liên hệ → tiền |
| C — Incrementality | **30 ca đối chứng** | `net_attributable`, `roi` |

Không cần mỗi nhóm cơ hội đủ 30. Tầng A chỉ hỏi: engine có tìm đúng những ca mà
owner coi là đáng cứu không.

## P6. Pilot đầu KHÔNG có AI Sales Agent

```
Phase 1 (bây giờ)  Detect → Queue → người liên hệ → ghi kết quả → booking → tiền
Phase 2 (sau 30–50 ca)  AI soạn nháp → người duyệt → gửi
Phase 3 (khi đủ dữ liệu)  Tự động liên hệ
```

Làm Agent trước thì sẽ có nhiều booking mà không biết Agent có thực sự tạo thêm
doanh thu hay không. Mỗi phase như trên đều tự chứng minh được ROI của chính nó.

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
  Chỉ người. Cố ý đứng sau attribution: làm Agent trước thì sẽ có nhiều booking
  mà không biết Agent có thực sự tạo thêm doanh thu hay không.
* Xếp hạng Hot / Warm / Cold, và CPL / CAC / ROAS theo chi phí quảng cáo.
* Học xác suất theo từng đặc trưng khách. Hiện chỉ là tỷ lệ theo nhóm — đủ dùng
  cho MVP và giải thích được, đó là điểm mạnh chứ không phải hạn chế tạm thời.
