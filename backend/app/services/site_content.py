"""Editable copy for the public site, with defaults that already read well.

Two rules shaped this module.

**Every key ships with real Vietnamese copy.** A CMS whose defaults are empty
produces a clinic site full of "Lorem ipsum" and empty sections on day one,
because the clinic signed up to get bookings, not to write a website. The
defaults below are what a dermatology/aesthetics clinic would plausibly say, so
the page is presentable before anyone edits a word — and editing becomes an
improvement rather than a prerequisite.

**Only copy lives here.** Services, doctors, before/after photos and reviews come
from their own tables. They are operational records the site displays; asking a
clinic to maintain them twice is how the two versions start disagreeing.
"""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.app.models.models import SiteContent


@dataclass(frozen=True)
class ContentKey:
    key: str
    label: str          # what the admin screen calls it
    kind: str           # text | textarea | list | stats
    default: Any
    hint: str = ""


#: Declared, not free-form: an admin screen can render the right input for each,
#: and a typo in a template surfaces as a missing key rather than silent blank.
CONTENT_KEYS: List[ContentKey] = [
    ContentKey(
        "hero_title", "Tiêu đề lớn ngoài trang chủ", "text",
        "Vẻ đẹp tự nhiên, được hoàn thiện bằng khoa học.",
        "Câu đầu tiên khách đọc. Nói về kết quả của khách, đừng nói về phòng khám.",
    ),
    ContentKey(
        "hero_subtitle", "Câu mô tả dưới tiêu đề", "textarea",
        "Phác đồ thẩm mỹ cá nhân hoá, xây dựng bởi đội ngũ bác sĩ chuyên khoa "
        "và công nghệ được kiểm chứng.",
    ),
    ContentKey(
        "hero_cta", "Chữ trên nút đặt lịch", "text", "Đặt lịch tư vấn",
        "Ngắn, là một hành động. 'Đặt lịch tư vấn' hiệu quả hơn 'Liên hệ'.",
    ),
    ContentKey(
        "stats", "Ba con số tạo niềm tin", "stats",
        [{"value": "10+", "label": "năm kinh nghiệm"},
         {"value": "20.000+", "label": "khách hàng"},
         {"value": "4.9★", "label": "đánh giá trung bình"}],
        "Chỉ điền con số THẬT. Một con số bị khách phát hiện sai làm hỏng toàn bộ trang.",
    ),
    ContentKey(
        "philosophy", "Câu tuyên ngôn", "textarea",
        "Không thay đổi bạn. Chỉ hoàn thiện phiên bản đẹp nhất của chính bạn.",
    ),
    ContentKey(
        "philosophy_eyebrow", "Chữ nhỏ phía trên tuyên ngôn", "text",
        "Beauty, backed by science",
    ),
    ContentKey(
        "services_title", "Tiêu đề mục dịch vụ", "text", "Dịch vụ nổi bật",
    ),
    ContentKey(
        "doctors_title", "Tiêu đề mục bác sĩ", "text", "Chuyên môn tạo nên khác biệt",
    ),
    ContentKey(
        "doctors_intro", "Mô tả mục bác sĩ", "textarea",
        "Mỗi phác đồ đều do bác sĩ chuyên khoa trực tiếp thăm khám và theo dõi.",
    ),
    ContentKey(
        "showcase_title", "Tiêu đề mục kết quả", "text", "Kết quả thật, khách hàng thật",
    ),
    ContentKey(
        "showcase_note", "Ghi chú dưới mục kết quả", "textarea",
        "Hình ảnh được đăng khi có sự đồng ý của khách hàng. "
        "Kết quả có thể khác nhau tuỳ cơ địa từng người.",
        "Nên giữ câu này: vừa trung thực, vừa bảo vệ phòng khám.",
    ),
    ContentKey(
        "journey_title", "Tiêu đề mục quy trình", "text", "Hành trình của bạn",
    ),
    ContentKey(
        "journey", "Ba bước trong quy trình", "list",
        [{"title": "Tư vấn chuyên sâu",
          "body": "Bác sĩ soi da, nghe mong muốn của bạn và đánh giá tình trạng thực tế."},
         {"title": "Phác đồ riêng cho bạn",
          "body": "Không có liệu trình dùng chung. Kế hoạch được xây theo đúng làn da của bạn."},
         {"title": "Điều trị & theo dõi",
          "body": "Theo sát từng buổi, chụp ảnh đối chiếu và điều chỉnh khi cần."}],
    ),
    ContentKey(
        "space_title", "Tiêu đề mục không gian", "text",
        "Không gian được thiết kế cho sự riêng tư",
    ),
    ContentKey(
        "space_body", "Mô tả không gian", "textarea",
        "Phòng điều trị riêng biệt, thiết bị được vệ sinh theo quy trình y tế, "
        "và một nơi bạn có thể thư giãn thay vì chờ đợi.",
    ),
    ContentKey(
        "space_image", "Ảnh không gian phòng khám (URL)", "text", "",
        "Ảnh thật của phòng khám thuyết phục hơn ảnh mẫu rất nhiều.",
    ),
    ContentKey(
        "hero_image", "Ảnh lớn ngoài trang chủ (URL)", "text", "",
    ),
    ContentKey(
        "closing_title", "Tiêu đề mục đặt lịch cuối trang", "text",
        "Bắt đầu hành trình của bạn",
    ),
    ContentKey(
        "closing_body", "Mô tả mục đặt lịch cuối trang", "textarea",
        "Để lại thông tin, phòng khám sẽ liên hệ trong giờ làm việc để sắp xếp "
        "buổi tư vấn phù hợp với bạn.",
    ),
]

_BY_KEY: Dict[str, ContentKey] = {c.key: c for c in CONTENT_KEYS}


def defaults() -> Dict[str, Any]:
    return {c.key: c.default for c in CONTENT_KEYS}


def load(db: Session, clinic_id: Optional[int]) -> Dict[str, Any]:
    """Every declared key, clinic overrides applied over the defaults.

    Returns a complete map on purpose: templates should never have to guard for
    a missing key, and a clinic that has edited nothing still gets a full page.
    """
    content = defaults()
    if not clinic_id:
        return content

    for row in db.query(SiteContent).filter(SiteContent.clinic_id == clinic_id).all():
        if row.key in content and row.value not in (None, "", [], {}):
            content[row.key] = row.value
    return content


def save(db: Session, clinic_id: int, key: str, value: Any,
         user_id: Optional[int] = None) -> None:
    if key not in _BY_KEY:
        raise ValueError(f"Khoá nội dung không hợp lệ: {key}")

    row = db.query(SiteContent).filter(
        SiteContent.clinic_id == clinic_id, SiteContent.key == key
    ).first()
    if row:
        row.value = value
        row.updated_by = user_id
    else:
        db.add(SiteContent(clinic_id=clinic_id, key=key, value=value,
                           updated_by=user_id))
        # Flush so a second save of the same key inside one request finds this
        # row instead of inserting a duplicate and hitting the unique index.
        # The session is autoflush=False, so the query above would not see it.
        db.flush()


def schema() -> List[Dict[str, Any]]:
    """What the admin screen renders, including each field's default so the
    editor can show "đang dùng mặc định" rather than an empty box."""
    return [
        {"key": c.key, "label": c.label, "kind": c.kind,
         "default": c.default, "hint": c.hint}
        for c in CONTENT_KEYS
    ]
