# Từ bản chạy được → sản phẩm có khách trả tiền

Định vị đã chốt: **không bán "AI cho phòng khám", bán "tăng booking và giảm no-show"**
cho **phòng khám da liễu / thẩm mỹ độc lập hoặc chuỗi nhỏ**, qua **hai luồng lõi**:

```
Luồng A (kiếm khách mới)   hỏi giá → tư vấn → đặt lịch → thu cọc → đến khám
Luồng B (giữ khách cũ)     khám xong → xin đánh giá → nhắc tái khám → quay lại
```

Mọi thứ không nằm trên hai đường này đều bị tắt cho tới khi có khách trả tiền.

---

## 1. Khoảng cách thật tới sản phẩm

Sau khi soát code: **6/8 hạng mục must-have đã xong**. Cái thiếu không phải tính năng,
mà là 6 việc dưới đây. Xếp theo **thứ tự bạn ít kiểm soát được thời gian nhất** — không
phải theo độ khó.

### 🔴 Chặn cửa 1 — Chưa có kênh gửi tin thật (bắt đầu NGAY hôm nay)

Đây là rủi ro lớn nhất và là thứ duy nhất **không phụ thuộc vào tốc độ code của bạn**.

[channel_gateway.py:68](backend/app/services/channel_gateway.py#L68) gửi theo thứ tự
Zalo ZNS → SMS → in ra console:

| Kênh | Tình trạng |
|---|---|
| Zalo ZNS | Code thật, gọi đúng API Zalo — **nhưng cần OA đã duyệt + `zns_template_id` đã được phê duyệt** |
| SMS | **Chưa cài** — chỉ là một dòng `print()`, ghi rõ "plug your SMS provider here" |
| Email | Thật (aiosmtplib), nhưng bệnh nhân Việt Nam không đọc email nhắc lịch |

Nghĩa là: **nếu phòng khám chưa có Zalo OA với template ZNS được duyệt, tin nhắn nhắc
lịch không đi đâu cả** — chỉ in ra log server. Mà "giảm no-show" chính là một nửa lời
hứa bạn đang bán.

Thủ tục Zalo OA + duyệt template ZNS mất **từ vài ngày tới vài tuần**, cần giấy phép
kinh doanh và nội dung mẫu đúng quy định. Việc phải làm:

1. **Hôm nay**: mở hồ sơ Zalo OA cho CareDesk (tài khoản của bạn, dùng chung để demo)
2. Soạn và nộp duyệt **3 template ZNS**: nhắc lịch 24h, nhắc lịch 2h, xác nhận đặt lịch
3. **Song song**: cài một nhà cung cấp SMS Việt Nam (eSMS / SpeedSMS) làm đường lùi —
   chỗ cắm đã có sẵn, chỉ cần điền, khoảng nửa ngày
4. Khi ký khách pilot: hướng dẫn họ tự mở OA riêng, hoặc gửi dưới OA của bạn giai đoạn đầu

> Nếu bỏ qua bước này, tới ngày demo cho phòng khám bạn sẽ phải nói "tin nhắn thật thì
> chưa gửi được" — và mất khách ngay tại chỗ.

### 🔴 Chặn cửa 2 — Slot đang chờ thanh toán vẫn bị bán cho người khác

[ai_engine.py:66](backend/app/services/ai_engine.py#L66) chỉ loại các lịch ở trạng thái
`pending` và `confirmed`, trong khi trạng thái hợp lệ có 6 giá trị:

```python
Appointment.status.in_(["pending", "confirmed"])   # thiếu awaiting_deposit
```

Khách A chốt 10:00 → chuyển `awaiting_deposit` → đang mở app ngân hàng → khách B chat
→ **AI báo 10:00 còn trống**. Hai người cùng một khung giờ.

Phải làm:
- Thêm `awaiting_deposit` vào danh sách loại trừ
- **Hết hạn giữ chỗ 15 phút** — không thì một khách bỏ ngang sẽ khoá chết khung giờ đó
- **Unique index trên `(doctor_id, start_time)`** cho các trạng thái còn sống. Toàn bộ
  luồng hiện là đọc-rồi-ghi không khoá; để database từ chối là cách chặn rẻ nhất

### 🔴 Chặn cửa 3 — AI không chắc nhưng không chuyển người thật

Đúng nguyên tắc #3 bạn đặt ra. Hiện có hai đường handoff:

1. **Từ khoá cấp cứu** (`AISafetyRule.force_handoff`) — chạy tốt
2. **AI tự nhận không trả lời được** — [ai_engine.py:543](backend/app/services/ai_engine.py#L543):

```python
if any(trigger in lower_res for trigger in handoff_triggers) and "cần cấp cứu" in lower_res:
```

Điều kiện `and` này gần như chắc chắn sai. Nó bắt buộc câu trả lời phải **vừa** xin
chuyển tiếp **vừa** chứa chữ "cần cấp cứu". Nên khi AI nói *"em không chắc, để lễ tân
liên hệ lại bạn nhé"* → **không có handoff nào xảy ra**. Khách ngồi chờ một người
không bao giờ tới.

Thêm một vấn đề nặng hơn: khi gọi OpenAI lỗi,
[ai_engine.py:532](backend/app/services/ai_engine.py#L532) **âm thầm rơi về bộ trả lời
mock**. Mock lấy dữ liệu thật của phòng khám nên không bịa giá, nhưng nó chỉ là bộ dò
từ khoá. Hết hạn API key hay OpenAI sập → khách vẫn được trả lời, phòng khám không hề
biết chất lượng đã tụt.

Phải làm:
- Đổi `and` → điều kiện riêng cho "AI không chắc", tách khỏi luồng cấp cứu
- Rơi về mock thì **ghi log cảnh báo + hiện cờ trên Dashboard**; quá 3 lần liên tiếp
  thì chuyển thẳng người thật thay vì tiếp tục giả vờ
- Ngoài giờ làm việc mà không có ai trực: nói rõ "lễ tân sẽ liên hệ trong giờ hành
  chính" thay vì im lặng

### 🟠 Chặn cửa 4 — Không có cơ chế bật/tắt

Không có feature flag nào trong [config.py](backend/app/core/config.py). Mà toàn bộ kế
hoạch dựa trên việc **tắt bớt tính năng**. Tắt bằng cách xoá code hay comment route thì
3 tháng sau bật lại phải viết lại và test lại — trả tiền hai lần.

Làm trước mọi việc tắt: một bảng cờ theo `clinic_id` + vài dòng đọc cờ. Khoảng 1 ngày.

### 🟠 Chặn cửa 5 — Không có cửa vào (onboarding)

Khoảng trống tính năng thật sự **duy nhất**. Hiện đăng ký xong bị thả vào dashboard
trống, phải tự mò qua 5 màn hình mới chat thử được. Đây là chỗ mất khách.

Wizard 15 phút, 5 bước, mỗi bước một màn hình:

| Bước | Hỏi gì | Vì sao bắt buộc |
|---|---|---|
| 1 | Tên phòng khám, địa chỉ, điện thoại | Landing + AI cần để trả lời "ở đâu" |
| 2 | Giờ mở cửa | Không có thì không sinh được khung giờ trống |
| 3 | 3–5 dịch vụ chính + giá | Đây là thứ 80% khách hỏi |
| 4 | Ít nhất 1 bác sĩ + lịch làm việc | **Không có lịch làm việc thì AI không chốt được lịch nào** |
| 5 | **Số liệu hiện tại** (xem mục 3) | Không có thì sau này không chứng minh được giá trị |

Kết thúc wizard phải đưa thẳng tới **một cửa sổ chat thử nghiệm** với chính dữ liệu vừa
nhập. Khoảnh khắc chủ phòng khám thấy AI đọc đúng bảng giá của mình là khoảnh khắc bán
được hàng.

Chốt chặn kỹ thuật: **không cho bật link công khai khi chưa qua bước 4.** Một phòng khám
publish landing mà chưa có lịch làm việc sẽ nhận khách rồi trả lời "hiện chưa có khung
giờ trống" — hỏng ngay ấn tượng đầu.

### 🟠 Chặn cửa 6 — Chưa từng diễn tập restore

Sắp chạm vào **dữ liệu bệnh nhân thật**, và 14 migration chưa từng chạy trên Postgres.
Trước khi mở cho khách đầu tiên:

1. Dựng staging trùng cấu hình production (cùng nhà cung cấp, cùng Postgres)
2. Chạy toàn bộ migration trên staging với dữ liệu có hình dạng thật
3. **Xoá staging và phục hồi từ backup** — nếu chưa làm một lần thì coi như chưa có backup
4. Bật snapshot tự động hàng ngày

---

## 2. Tắt cái gì

| Tính năng | Quyết định | Lý do |
|---|---|---|
| Console chuỗi `/org` | **Ẩn khỏi menu**, giữ code | Hạ tầng Organization→Clinic→Branch đã xong và có test. Ẩn là đủ — gỡ ra tốn hơn giữ lại |
| Tiếng Anh / Nhật | **Tắt mặc định**, bật theo từng phòng khám | Chưa dịch nội dung dịch vụ thì trang EN hiện khung tiếng Anh + chữ tiếng Việt, trông như lỗi |
| Copilot (trợ lý AI trong Dashboard) | **Tắt** | Không nằm trên hai luồng lõi, tốn token và tăng mặt trận hỗ trợ |
| Facebook CAPI | **Tắt** | Chỉ có ý nghĩa khi khách chạy quảng cáo |
| Automation *đánh thức khách cũ 180 ngày* và *ưu đãi 5 ngày* | **Mặc định tắt** | Ngày đầu mà hệ thống tự nhắn hàng loạt khách cũ là rủi ro bị báo cáo spam. Bật sau khi phòng khám đã tin hệ thống |
| Gói liệu trình, danh sách chờ, 6 automation còn lại | **Giữ** | Gói liệu trình là dòng tiền chính của thẩm mỹ; lấp chỗ trống từ waitlist là khoảnh khắc demo thuyết phục nhất |
| Console `/platform` | **Giữ** | Của bạn, không phải của khách |

Nguyên tắc chung: **giữ code, tắt bằng cờ.** Không xoá thứ đã có test.

---

## 3. Đo lường — phần quyết định việc gia hạn

Bạn bán "tăng booking, giảm no-show". Cả hai đều là **so sánh**, mà so sánh thì cần một
con số **trước**. Đây là chỗ hầu hết mọi người bỏ sót, rồi tới lúc khách hỏi "dùng 2
tháng rồi, được gì?" thì không trả lời được.

**Bước 5 của onboarding phải hỏi cho bằng được:**

- Trung bình một tháng nhận bao nhiêu lịch hẹn?
- Khoảng bao nhiêu phần trăm khách đặt rồi không đến?
- Mỗi ngày khoảng bao nhiêu người nhắn hỏi giá mà không đặt lịch?

Con số họ đưa ra sẽ ước chừng và không chính xác. Không sao — **cái bạn cần là mốc để
so, và cần chính họ nói ra con số đó**, để 60 ngày sau không ai cãi được.

Sau đó hệ thống tự đo, dữ liệu đã có sẵn:

| Chỉ số | Lấy từ |
|---|---|
| Lead mới | `PatientLead` theo ngày tạo |
| Lịch hẹn do AI chốt | `Appointment.booking_source` bắt đầu bằng `ai_` |
| Tiền cọc thu được | `Payment` trạng thái đã thanh toán |
| Tỷ lệ không đến | `no_show_rate_percent` — [reports.py:155](backend/app/api/endpoints/reports.py#L155) |
| Khách quay lại | `returning_patients` — [reports.py:125](backend/app/api/endpoints/reports.py#L125) |
| Doanh thu do AI tạo ra | `RevenueRecord.source` bắt đầu bằng `ai_` |

**Một điều phải thành thật với chính mình:** *"khách quay lại"* không thể đo trong 30
ngày. Kịch bản nhắc tái khám đặt ở mốc 30 ngày sau khi khám, nên vòng đo đầy đủ cần
**60–90 ngày**. Trong tháng đầu chỉ hứa và đo được **lead, booking, cọc, no-show**. Đừng
bán con số giữ khách trước khi có nó — hứa sớm rồi không chứng minh được là cách nhanh
nhất để mất khách pilot.

Dashboard phải để **hai con số này lên trên cùng, to nhất**: *lịch hẹn AI chốt tháng
này* và *tỷ lệ không đến*. Đúng hai thứ bạn bán, không phải 12 ô thống kê ngang nhau.

---

## 4. Lịch 30 ngày

| Tuần | Việc | Xong là gì |
|---|---|---|
| **1** | Nộp hồ sơ Zalo OA + 3 template ZNS *(chạy nền cả tháng)*<br>Cài nhà cung cấp SMS<br>Feature flags<br>Vá giữ chỗ slot + unique index<br>Sửa handoff + cảnh báo khi rơi về mock | Ba chặn cửa đỏ đã đóng. Tin nhắn gửi được thật qua SMS kể cả khi ZNS chưa duyệt xong |
| **2** | Onboarding wizard 5 bước<br>Tắt tính năng theo bảng mục 2<br>Đưa 2 chỉ số lõi lên đầu Dashboard | Người lạ tự đăng ký và chat thử được trong 15 phút, không cần bạn hướng dẫn |
| **3** | Staging + chạy migration trên Postgres<br>**Diễn tập restore**<br>Deploy production<br>**Tự dùng như một phòng khám thật trong 3 ngày** | Bạn là người đầu tiên phát hiện lỗi, không phải khách hàng |
| **4** | Ký **1** khách pilot (không phải 3)<br>Onboard trực tiếp, ngồi cạnh<br>Bật ZNS thật<br>Theo dõi Inbox hàng ngày | Có lead thật, booking thật, cọc thật |

**Vì sao 1 khách chứ không phải 3:** khách đầu tiên sẽ lộ ra 20 thứ bạn chưa nghĩ tới.
Sửa cho một chỗ thì nhanh; sửa đồng thời cho ba chỗ đang cùng kêu thì bạn thành đội hỗ
trợ chứ không còn là người xây sản phẩm. Ký khách thứ 2 và 3 khi khách thứ nhất đã chạy
êm hai tuần liền.

**Thu tiền ngay từ khách pilot**, kể cả chỉ 30–50% giá dự kiến. Pilot miễn phí cho phản
hồi lịch sự và vô dụng — người không trả tiền sẽ không phàn nàn, mà cũng không dùng.

---

## 5. Pilot thành công hay thất bại — định trước

Đặt ngưỡng **trước khi bắt đầu**, nếu không sẽ tự thuyết phục mình rằng kết quả nào cũng ổn.

**Đạt** (đủ để ký tiếp và tìm khách thứ 2–3):
- AI tự chốt ≥ 30% tổng số lịch hẹn, không cần lễ tân can thiệp
- Tỷ lệ không đến giảm rõ so với con số họ khai lúc onboard
- Lễ tân **tự nguyện** mở Inbox hàng ngày mà không cần bạn nhắc
- Phòng khám đồng ý trả đủ giá sau pilot

**Không đạt** (dừng lại, đọc log hội thoại, sửa trước khi tìm khách mới):
- Lễ tân tắt AI hoặc trả lời tay tất cả → AI đang cản trở chứ không giúp
- Khách phàn nàn AI trả lời sai giá hoặc sai giờ → lỗi dữ liệu hoặc lỗi onboarding
- Cọc thu được gần bằng không → luồng thanh toán có ma sát, hoặc khách Việt chưa quen
  trả cọc cho phòng khám (khả năng có thật, phải kiểm chứng sớm)

Chỉ số quan trọng nhất, và cũng khó chịu nhất, là **cái thứ ba**: lễ tân có tự mở Inbox
không. Phần mềm mà người dùng hàng ngày phải bị nhắc mới mở thì không có gia hạn, dù
báo cáo đẹp đến mấy.

---

## 6. Không hứa gì

Chốt lại đúng nguyên tắc #4:

| Không nói | Nói thay bằng |
|---|---|
| "AI thay thế lễ tân" | "AI trực giúp phần ngoài giờ, lễ tân vẫn là người chốt" |
| "AI tư vấn y khoa" | "AI tư vấn dịch vụ và giá, chuyện chuyên môn chuyển bác sĩ" |
| "Tự động hoá toàn bộ phòng khám" | "Tăng booking và giảm khách không đến" |
| "Hỗ trợ mọi ngành y tế" | "Làm cho da liễu và thẩm mỹ" |

Lời hứa hẹp thì giữ được. Và lời hứa hẹp mà giữ được sẽ bán được nhiều hơn lời hứa rộng
mà không chứng minh nổi.
