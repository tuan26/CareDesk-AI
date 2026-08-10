# 📖 Hướng dẫn sử dụng CareDesk AI

## 1. Khởi động & Đăng nhập

| Thành phần | Địa chỉ |
|---|---|
| **Dashboard quản trị** | http://localhost:5173 |
| **Trang demo widget chat** (vai khách hàng) | http://localhost:5500 |
| **API + Swagger docs** | http://localhost:8000/docs |

**Tài khoản có sẵn** (dữ liệu mẫu tự tạo khi chạy lần đầu):

| Vai trò | Email | Mật khẩu | Quyền |
|---|---|---|---|
| Chủ phòng khám | `owner@caredesk.ai` | `owner123` | Toàn quyền + xem doanh thu/ROI |
| Lễ tân | `receptionist@caredesk.ai` | `receptionist123` | Vận hành (không xem doanh thu, không sửa cấu hình) |

> Trong một phòng khám chỉ có **hai** vai trò: chủ phòng khám và lễ tân. (Vai trò
> `admin` cũ đã được gộp vào `owner` — nó có quyền y hệt owner nhưng lại không
> nhận được bản tin vận hành 8h/20h, nên là nguồn nhầm lẫn.)

> Muốn tạo phòng khám riêng của bạn: bấm **"Đăng ký phòng khám miễn phí"** ở màn đăng nhập — tự có gói Free (200 hội thoại AI/tháng) + 8 kịch bản automation kích hoạt sẵn.

---

## 2. Trải nghiệm nhanh 10 phút (đóng 2 vai)

### Bước 1 — Vai CHỦ PHÒNG KHÁM: bật máy kiếm tiền
1. Đăng nhập `owner@caredesk.ai / owner123`
2. Vào **⚙️ Cài đặt & AI Eval → 💰 Cấu hình Revenue Engine**:
   - Nhập **Tiền cọc giữ chỗ**: `200000` → Lưu (AI sẽ thu cọc khi chốt lịch)
   - (Tùy chọn) Dán **Link Google Review** của phòng khám
3. Vào **⚡ Automation** xem 8 kịch bản đang chạy: follow-up khách hỏi giá, nhắc tái khám, xin review, đánh thức khách cũ, lấp chỗ trống... Bấm **"Sửa tin"** để đổi lời thoại theo giọng của bạn.

### Bước 2 — Vai KHÁCH HÀNG: chat với AI
1. Mở http://localhost:5500 → bấm nút chat tròn góc phải dưới
2. Điền tên + SĐT + tick đồng ý → **Bắt đầu trò chuyện**
3. Thử lần lượt:
   - `Trị mụn giá bao nhiêu?` → AI báo giá (đồng thời hệ thống ghi nhận "khách hỏi giá" để tự follow-up sau 2 ngày nếu khách im lặng)
   - `Tôi muốn đặt lịch trị mụn` → AI xác nhận tên/SĐT, hỏi ngày
   - `ngày mai` → AI đề xuất 3 khung giờ trống **thật** theo lịch bác sĩ
   - `1` → AI chốt lịch + gửi **link đặt cọc 200k**
4. Mở link cọc → bấm **"Tôi đã thanh toán"** → lịch tự chuyển **ĐÃ XÁC NHẬN**
5. Thử câu nguy hiểm: `Mặt tôi sưng và chảy máu nhiều` → AI từ chối tư vấn y khoa, chuyển ngay cho người thật (safety filter)

### Bước 3 — Quay lại vai PHÒNG KHÁM: xem tiền chảy về
1. **📊 Tổng quan doanh thu**: thấy lịch vừa đặt gắn nhãn **🤖 AI chốt**; hỏi Copilot ở panel phải: `Hôm nay có bao nhiêu lịch hẹn?`
2. **📅 Lịch hẹn**: chuyển tab **Lịch tuần** xem dạng calendar; bấm vào ca → Xác nhận / Đổi lịch / Hủy
3. Bấm **Hoàn thành** ca khám → hệ thống: ghi nhận doanh thu (gắn nguồn AI) + 2 giờ sau tự nhắn xin đánh giá + 30 ngày sau tự nhắc tái khám
4. Ở widget, khách trả lời `5` → nhận link Google Review + **mã giới thiệu** tặng bạn bè; trả lời `2` → bị chặn lại, chuyển bạn xử lý riêng (xem tab **⭐ Đánh giá** trong Automation)
5. **📈 Báo cáo ROI**: Doanh thu AI tạo ra, attribution theo nguồn, no-show, giờ cao điểm

---

## 3. Hướng dẫn theo từng màn hình

### 📊 Tổng quan doanh thu (Dashboard)
- 4 thẻ đầu (chỉ owner/admin): **Doanh thu AI tạo ra · Lịch AI chốt · ROI · No-show**
- **Copilot**: gõ câu hỏi tự nhiên — "Doanh thu tháng này?", "Tỷ lệ no-show?", "Tình hình gói liệu trình?" (lễ tân hỏi doanh thu sẽ bị từ chối đúng phân quyền)

### 💬 Hộp thư AI (Inbox)
- Danh sách hội thoại mọi kênh (web/Zalo/FB), realtime qua WebSocket
- Tab **⚠️ Handoff** = các ca AI đã chuyển cho người thật (khẩn cấp y tế, quota, review xấu)
- Bấm **🤝 Tiếp quản Chat** → AI im lặng, bạn chat trực tiếp; khách thấy tin của bạn ngay trên widget/Zalo/FB. Xong bấm **🤖 Trả về cho Bot**

### 📅 Lịch hẹn
- 2 chế độ: **Danh sách** (lọc trạng thái/bác sĩ/ngày) và **Lịch tuần** (calendar màu theo trạng thái)
- Nút theo vòng đời: Chờ cọc → Xác nhận → Hoàn thành / Vắng mặt / Hủy; **Nhắc lịch** gửi email+ZNS thủ công
- **+ Tạo lịch hẹn**: chọn khách cũ hoặc nhập khách mới, hệ thống tra khung giờ trống thật

### 👥 Khách hàng (CRM)
- Tìm theo tên/SĐT; mở **Hồ sơ**: lịch sử hẹn đánh số **Buổi thứ N** theo liệu trình, tags (VIP...), ghi chú nội bộ, mã giới thiệu

### 🎁 Gói liệu trình
- **Tạo gói** (VD: "Trị mụn 5 buổi — 1.800.000đ, hạn 180 ngày") → **Bán gói cho khách** (doanh thu ghi nhận ngay)
- Buổi khám hoàn thành **tự trừ** vào gói; hoặc bấm **"Trừ 1 buổi"** cho khách walk-in
- Sắp hết hạn còn buổi → AI tự nhắc; dùng hết → AI tự mời gia hạn giảm giá

### ⚡ Automation
- **Kịch bản**: bật/tắt từng automation, sửa lời thoại (biến `{name}`, `{service}`, `{clinic}`)
- **Nhật ký gửi**: xem AI đã nhắn ai, khi nào; "Đã hủy (khách đã đặt)" = follow-up dừng đúng lúc
- **Đánh giá**: rating khách; dòng đỏ 🚨 = khách chấm thấp cần gọi ngay
- **DS chờ**: khách chờ giờ đẹp — có ca hủy hệ thống tự báo họ

### 📈 Báo cáo ROI (owner/admin)
- Chọn khoảng ngày → Doanh thu AI, ROI trên phí gói, khách quay lại, giá trị gói chưa dùng, doanh thu theo nguồn/dịch vụ/bác sĩ, giờ cao điểm, trạng thái lịch hẹn

### ⚙️ Cài đặt
- **Revenue Engine**: tiền cọc, link Google Review, bản tin 8h/20h
- **Kênh CSKH**: dán Access Token Zalo OA / Facebook Page + webhook URL hiển thị sẵn để dán vào Meta/Zalo; bật **Comment Guard** + Pixel/CAPI. *Chưa có token vẫn demo được (chế độ mock in log)*
- **Chạy Đánh giá AI**: chấm điểm bot theo 7 kịch bản chuẩn
- **Nhật ký hệ thống**: audit ai làm gì, khi nào

---

## 4. Mẹo demo cho khách mua hàng

1. Bật cọc 200k trước → demo chat đặt lịch có thu tiền là "wow moment"
2. Sau khi bấm Hoàn thành 1 ca, mở tab **Automation → Nhật ký** cho thấy máy tự xin review + hẹn tái khám
3. Kết thúc bằng **Báo cáo ROI**: "AI kiếm được X đồng — gấp N lần phí phần mềm"

## 5. Sự cố thường gặp

| Hiện tượng | Cách xử lý |
|---|---|
| Trang trắng / lỗi kết nối | Kiểm tra backend đang chạy: mở http://localhost:8000/docs |
| Widget không gửi được tin | Backend chưa chạy, hoặc F5 lại trang widget |
| AI báo "không có khung giờ trống" | Ngày đó bác sĩ không có ca — vào **Bác sĩ & Lịch làm** thêm ca, hoặc chọn ngày khác (BS A làm T2-T6, BS B làm T7-CN) |
| Muốn làm lại dữ liệu từ đầu | Tắt backend, xóa file `caredesk.db`, chạy lại — dữ liệu mẫu tự tạo mới |
