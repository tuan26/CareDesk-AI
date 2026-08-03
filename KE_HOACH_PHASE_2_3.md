# Kế hoạch Phase 2 & 3 — Landing thành Website

> Trạng thái: **bản kế hoạch, chưa code**. Phase 1 (A/B/C) đã xong — xem
> [KE_HOACH_LANDING_PHASE1.md](KE_HOACH_LANDING_PHASE1.md).

## Bối cảnh: Phase 1 để lại gì

Landing hiện dựng **hoàn toàn từ dữ liệu vận hành** (cơ sở, giờ làm, dịch vụ,
giá, bác sĩ). Điểm mạnh: khách bật lên là có trang ngay, không phải nhập lại gì.
Điểm yếu: **không có phần kể chuyện thương hiệu** — không banner, không giới
thiệu, không ảnh thực tế, không câu trả lời cho "vì sao chọn chỗ này".

Phase 2 lấp đúng khoảng đó. Phase 3 để AI làm hộ phần soạn nội dung.

---

# Phase 2 — Landing thành trang bán hàng thật

## 2.1. Nội dung thương hiệu (ưu tiên cao nhất)

Thêm cột vào `Clinic` (nội dung dùng chung) và `Branch` (ghi đè theo cơ sở khi cần):

| Cột | Bảng | Ghi chú |
|---|---|---|
| `tagline` | Clinic | 1 câu dưới tên, hiện ở hero |
| `about_md` | Clinic | Giới thiệu, Markdown ngắn |
| `banner_url` | Clinic, Branch | Ảnh nền hero |
| `gallery_json` | Clinic, Branch | Mảng URL ảnh cơ sở/kết quả |
| `map_embed` | Branch | Nhúng Google Maps (hoặc lat/lng) |
| `faq_json` | Clinic | Hỏi đáp — **Service đã có `faq_data`, tái dùng cấu trúc đó** |
| `highlights_json` | Clinic | 3-5 gạch đầu dòng "vì sao chọn chúng tôi" |

**Cảnh báo pháp lý — cần xử lý trước khi mở gallery:** phòng khám da liễu sẽ
muốn đăng ảnh **trước/sau của bệnh nhân**. Đây là dữ liệu sức khoẻ. Cần:
- ô xác nhận "đã có văn bản đồng ý của bệnh nhân" bắt buộc khi upload
- lưu ngày đồng ý + người upload vào audit log
- không cho đăng ảnh có mặt nhận diện được nếu chưa tick

Bỏ qua bước này là rủi ro thật cho khách hàng của bạn, không chỉ cho bạn.

## 2.2. SEO tuỳ chỉnh

| Cột | Bảng |
|---|---|
| `seo_title`, `seo_description` | Clinic, Branch |
| `noindex` | Branch | cơ sở nội bộ/chưa khai trương |

Hiện `<title>`/`description` sinh tự động. Giữ nguyên làm mặc định, chỉ ghi đè
khi khách nhập — đừng bắt nhập mới có SEO.

Thêm: `<link rel="alternate" hreflang>` nếu Phase 2 mở đa ngôn ngữ cho landing
(hiện `i18n.jsx` mới phục vụ SPA chat, landing vẫn thuần tiếng Việt).

## 2.3. Chuyển đổi (thứ thực sự ra tiền)

- **Form liên hệ / gọi lại** → tạo `BookingRequest` (bảng **đã có**), không cần model mới
- **Nút gọi + Zalo nổi** trên mobile — phần lớn traffic quảng cáo là mobile
- **Cờ ẩn giá** `show_prices` trên Clinic: nhiều phòng khám không muốn công khai bảng giá
- **Tracking**: chèn Meta Pixel / Google Tag theo từng phòng khám (`pixel_id`,
  `ga_measurement_id` trên Clinic) — `capi.py` **đã có** sẵn phần CAPI, nối vào là đo được
  chuyển đổi từ quảng cáo tới lịch hẹn

## 2.4. Nợ kỹ thuật phải trả trong Phase 2

Ba việc đã biết, càng để lâu càng đắt:

1. **Cache 5 phút không xoá được** — sửa thông tin xong phải chờ. Cần xoá cache
   theo phòng khám khi lưu (`Cache-Control` hiện đặt cứng trong `landing.py`).
2. **Rate limit + scheduler in-memory** — chặn chạy nhiều worker. Chuyển rate
   limit sang Redis; scheduler chỉ chạy ở một process (hoặc tách hẳn ra worker riêng).
3. **Ảnh do khách nhập là URL ngoài** — chưa có upload. Phase 2 mở gallery thì
   phải có chỗ lưu ảnh (S3/R2) + giới hạn dung lượng, nếu không khách sẽ dán link
   ảnh Facebook rồi vài tháng sau chết link.

## 2.5. Thứ tự đề xuất

1. Nợ kỹ thuật (2.4.1 + 2.4.3) — làm trước vì phần sau phụ thuộc
2. Nội dung thương hiệu + form UI cho khách nhập
3. SEO tuỳ chỉnh
4. Chuyển đổi + tracking
5. Gallery (kèm luồng đồng ý bệnh nhân)

---

# Phase 3 — AI soạn nội dung

## Nguyên tắc: **không xây page builder**

Drag-drop builder là một sản phẩm riêng, tốn nhiều tháng và phải bảo trì mãi.
Giá trị thật nằm ở chỗ **khách không phải nghĩ ra chữ để viết** — không phải ở
chỗ họ kéo thả được khối.

Giữ template cố định (đã có), cho tuỳ biến **màu + font + thứ tự khối**, còn AI
lo phần chữ.

## 3.1. AI sinh nội dung

Điền vào đúng các cột Phase 2 đã tạo:

```
Input:  tên phòng khám, chuyên khoa, dịch vụ + giá đã có, địa chỉ, đối tượng khách
Output: tagline, about_md, highlights_json, faq_json, seo_title, seo_description
```

Hạ tầng **đã sẵn**: `ai_engine.py` đang gọi LLM, `evaluator.py` có sẵn khung chấm
chất lượng. Thêm một service `content_writer.py` là đủ.

**Bắt buộc**: nội dung AI sinh ra phải qua **duyệt của người** trước khi hiện
công khai (`draft` → `published`). Đây là lĩnh vực y tế — AI viết "cam kết khỏi
100%" là vi phạm quảng cáo dịch vụ khám chữa bệnh. Nên tái dùng `AISafetyRule`
để chặn từ ngữ cam kết/chữa khỏi ngay khi sinh.

## 3.2. Tuỳ biến giao diện

- `theme_json` trên Clinic: màu chủ đạo, font, bo góc
- Chọn thứ tự/ẩn hiện từng khối (hero, cơ sở, dịch vụ, bác sĩ, FAQ, gallery)
- 2-3 preset sẵn thay vì bảng màu tự do — khách chọn nhanh, và không tự làm xấu trang

## 3.3. Blog / tin tức

Model `Article` (clinic_id, slug qua **slug_registry đã có**, title, body_md,
cover, status, published_at). URL `/book/<brand>/tin-tuc/<slug>`.

Đây là thứ kéo SEO dài hạn, nhưng **chỉ có giá trị nếu đăng đều** — cân nhắc kỹ
trước khi làm, vì phần lớn phòng khám sẽ đăng 3 bài rồi bỏ. AI sinh bài + lịch
đăng tự động sẽ hợp lý hơn là chỉ đưa cái CMS trống.

## 3.4. Miền riêng (đáng cân nhắc hơn blog)

Cho khách trỏ `phongkham.vn` về hệ thống thay vì dùng `/book/<brand>`.
Đây là thứ khách chịu **trả thêm tiền**, và về kỹ thuật là: bảng `custom_domains`
+ resolve theo `Host` header + cấp SSL tự động (Caddy/Traefik làm sẵn).

Giá trị thương mại có khi cao hơn cả blog lẫn page builder.

---

## Ước lượng thô

| Hạng mục | Quy mô |
|---|---|
| 2.4 Nợ kỹ thuật | nhỏ–vừa |
| 2.1 + 2.2 Nội dung + SEO | vừa |
| 2.3 Chuyển đổi + tracking | nhỏ–vừa |
| 2.5 Gallery + đồng ý bệnh nhân | vừa (phần pháp lý mới là khó) |
| 3.1 AI sinh nội dung | vừa |
| 3.2 Theme | nhỏ |
| 3.3 Blog | vừa–lớn |
| 3.4 Miền riêng | vừa, cần thay đổi hạ tầng |

## Khuyến nghị nếu phải chọn ít

Làm **2.4 → 2.1 → 2.3 → 3.1**, bỏ qua blog và page builder.
Được: landing có nội dung thật, đo được chuyển đổi từ quảng cáo, và AI viết hộ
nội dung. Đó là bộ tính năng bán được, không phải bộ tính năng nhiều nút nhất.
