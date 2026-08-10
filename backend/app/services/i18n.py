"""Locale resolution and safe translation fallback for public chat content."""
from typing import Any, Dict, Iterable, Optional

SUPPORTED_LOCALES = {"vi", "ja", "en"}
FALLBACK_LOCALE = {"vi": "en", "ja": "en", "en": "en"}


def say(locale: str, vi: str, en: str, ja: str) -> str:
    """Pick one of three hand-written strings. For short operational sentences
    that do not belong in the LANDING_TEXT/BOOKING_TEXT tables."""
    return {"vi": vi, "en": en, "ja": ja}.get(locale, en)


def normalize_locale(locale: Optional[str], default: str = "vi") -> str:
    value = (locale or default or "vi").lower().split("-", 1)[0]
    return value if value in SUPPORTED_LOCALES else (default if default in SUPPORTED_LOCALES else "vi")


def translation_for(
    localized_content: Optional[Dict[str, Dict[str, Any]]], locale: str
) -> Dict[str, Any]:
    """Return requested translation, then its explicit fallback, then an empty map."""
    content = localized_content or {}
    normalized = normalize_locale(locale)
    return content.get(normalized) or content.get(FALLBACK_LOCALE[normalized]) or {}


def missing_translation_locales(
    localized_content: Optional[Dict[str, Dict[str, Any]]], required: Iterable[str] = ("vi", "ja", "en")
) -> list[str]:
    content = localized_content or {}
    return [locale for locale in required if not content.get(locale)]


BOOKING_TEXT = {
    "vi": {
        "confirm": "Vui lòng xác nhận yêu cầu đặt lịch: trả lời 'đồng ý' để gửi yêu cầu, hoặc 'hủy' để chỉnh sửa.",
        "requested": "Yêu cầu đặt lịch của bạn đã được gửi. Đây chưa phải là lịch hẹn chính thức; lễ tân sẽ liên hệ xác nhận.",
    },
    "en": {
        "confirm": "Please confirm your booking request: reply 'yes' to submit it, or 'cancel' to make changes.",
        "requested": "Your booking request has been sent. This is not a confirmed appointment; our reception team will contact you.",
    },
    "ja": {
        "confirm": "予約リクエストを確認してください。送信するには「はい」、修正するには「キャンセル」と返信してください。",
        "requested": "予約リクエストを受け付けました。正式な予約ではありません。受付から確認のご連絡をします。",
    },
}


def booking_text(locale: str, key: str) -> str:
    resolved = normalize_locale(locale)
    return BOOKING_TEXT.get(resolved, BOOKING_TEXT["en"]).get(key, BOOKING_TEXT["en"][key])


def service_content(service: Any, locale: str) -> Dict[str, Any]:
    """Return a service's translated fields while safely retaining legacy values."""
    translated = translation_for(getattr(service, "localized_content", None), locale)
    return {
        "name": translated.get("name") or service.name,
        "description": translated.get("description") or service.description or "",
        "preparation_instructions": translated.get("preparation_instructions")
        or service.preparation_instructions
        or "",
        "faq": translated.get("faq") or service.faq_data or [],
    }


UI_TEXT = {
    "vi": {
        "title": "Lễ tân ảo CareDesk AI", "active": "Hoạt động 24/7",
        "consent_intro": "Vui lòng cung cấp thông tin để trợ lý ảo hỗ trợ bạn đặt lịch hẹn và tư vấn dịch vụ.",
        "name": "Họ và tên *", "phone": "Số điện thoại *", "email": "Email (Nhận nhắc lịch)",
        "referral": "Mã giới thiệu (nếu có)", "consent": "Tôi đồng ý cho phép CareDesk AI lưu trữ thông tin liên hệ để đặt lịch khám.",
        "start": "Bắt đầu trò chuyện", "connecting": "Đang kết nối...", "placeholder": "Nhập tin nhắn...",
        "welcome": "Chào bạn {name}, tôi là trợ lý ảo CareDesk AI. Tôi có thể giúp bạn giải đáp dịch vụ, bảng giá phòng khám hoặc hỗ trợ gửi yêu cầu đặt lịch. Bạn đang quan tâm dịch vụ nào ạ?",
        "connection_error": "Lỗi kết nối đến máy chủ. Vui lòng thử lại sau.", "send_error": "Rất tiếc, đã xảy ra lỗi kết nối. Vui lòng gửi lại.",
        "handoff": "Đang chuyển tiếp thông tin cho lễ tân hỗ trợ...", "agent_placeholder": "Lễ tân sẽ trả lời bạn ngay tại đây...",
    },
    "en": {
        "title": "CareDesk AI Virtual Receptionist", "active": "Available 24/7",
        "consent_intro": "Please provide your details so our virtual assistant can help with services and booking requests.",
        "name": "Full name *", "phone": "Phone number *", "email": "Email (for reminders)",
        "referral": "Referral code (optional)", "consent": "I consent to CareDesk AI storing my contact details for booking support.",
        "start": "Start chat", "connecting": "Connecting...", "placeholder": "Type a message...",
        "welcome": "Hello {name}, I am the CareDesk AI assistant. I can help with services, prices, clinic information, or a booking request. Which service are you interested in?",
        "connection_error": "Could not connect to the server. Please try again.", "send_error": "Sorry, a connection error occurred. Please send your message again.",
        "handoff": "Your information is being transferred to our reception team...", "agent_placeholder": "Our receptionist will reply here shortly...",
    },
    "ja": {
        "title": "CareDesk AI 受付アシスタント", "active": "24時間対応",
        "consent_intro": "サービスのご案内や予約リクエストのために、お客様情報をご入力ください。",
        "name": "お名前 *", "phone": "電話番号 *", "email": "メールアドレス（予約リマインダー用）",
        "referral": "紹介コード（任意）", "consent": "予約サポートのため、CareDesk AIが連絡先情報を保存することに同意します。",
        "start": "チャットを開始", "connecting": "接続中...", "placeholder": "メッセージを入力...",
        "welcome": "{name}様、こんにちは。CareDesk AIアシスタントです。サービス、料金、クリニック情報、予約リクエストをお手伝いします。ご希望のサービスはありますか？",
        "connection_error": "サーバーに接続できませんでした。もう一度お試しください。", "send_error": "接続エラーが発生しました。もう一度メッセージを送信してください。",
        "handoff": "受付スタッフへ情報を引き継いでいます...", "agent_placeholder": "受付スタッフがこちらで返信します...",
    },
}


def ui_text(locale: str, key: str, **values: Any) -> str:
    """Localized widget copy with English as the safe final fallback."""
    text = UI_TEXT.get(normalize_locale(locale), UI_TEXT["en"]).get(key, UI_TEXT["en"].get(key, key))
    return text.format(**values)


# Server-rendered landing pages (/book/*). Kept apart from UI_TEXT because these
# strings are also what crawlers index, not just what a widget shows.
LANDING_TEXT = {
    "vi": {
        "book_cta": "Đặt lịch với trợ lý ảo", "call": "Gọi hotline",
        "locations": "Các cơ sở", "services": "Dịch vụ & bảng giá",
        "doctors": "Đội ngũ bác sĩ", "book_here": "Đặt lịch cơ sở này",
        "details": "Xem chi tiết", "book_title": "Đặt lịch khám",
        "book_body": "Trò chuyện với trợ lý ảo để được tư vấn dịch vụ và giữ chỗ khung giờ phù hợp.",
        "book_start": "Bắt đầu đặt lịch", "hours": "Giờ làm việc",
        "branch_info": "Thông tin cơ sở", "directions": "Chỉ đường",
        "book_at_branch": "Đặt lịch tại cơ sở này", "call_branch": "Gọi cơ sở",
        "other_branches": "Cơ sở khác", "back_to": "Về trang {name}",
        "minutes": "phút", "branch_count": "{n} cơ sở",
        "meta_desc": "{name}{where}. {branches} cơ sở, {services} dịch vụ. Đặt lịch khám trực tuyến với trợ lý ảo 24/7.",
        "meta_branch_desc": "{brand} — cơ sở {name}, {address}. {hours}Đặt lịch khám trực tuyến với trợ lý ảo 24/7.",
        "meta_hours": "Giờ làm việc {hours}. ", "title_suffix": "Đặt lịch khám",
        "powered": "Được vận hành bởi CareDesk AI", "not_found": "Không tìm thấy trang",
        "not_found_body": "Phòng khám hoặc cơ sở này không tồn tại, đã đổi liên kết hoặc đang tạm ngưng.",
    },
    "en": {
        "book_cta": "Book with the virtual assistant", "call": "Call hotline",
        "locations": "Locations", "services": "Services & pricing",
        "doctors": "Our doctors", "book_here": "Book at this location",
        "details": "View details", "book_title": "Book an appointment",
        "book_body": "Chat with our virtual assistant for advice and to hold a time slot.",
        "book_start": "Start booking", "hours": "Opening hours",
        "branch_info": "Location details", "directions": "Directions",
        "book_at_branch": "Book at this location", "call_branch": "Call this location",
        "other_branches": "Other locations", "back_to": "Back to {name}",
        "minutes": "min", "branch_count": "{n} locations",
        "meta_desc": "{name}{where}. {branches} locations, {services} services. Book online with our 24/7 virtual assistant.",
        "meta_branch_desc": "{brand} — {name}, {address}. {hours}Book online with our 24/7 virtual assistant.",
        "meta_hours": "Open {hours}. ", "title_suffix": "Book an appointment",
        "powered": "Powered by CareDesk AI", "not_found": "Page not found",
        "not_found_body": "This clinic or location does not exist, has moved, or is temporarily unavailable.",
    },
    "ja": {
        "book_cta": "バーチャルアシスタントで予約", "call": "ホットラインに電話",
        "locations": "店舗一覧", "services": "サービスと料金",
        "doctors": "医師紹介", "book_here": "この店舗を予約",
        "details": "詳細を見る", "book_title": "診察を予約する",
        "book_body": "バーチャルアシスタントに相談し、ご希望の時間を確保できます。",
        "book_start": "予約を開始", "hours": "営業時間",
        "branch_info": "店舗情報", "directions": "道順",
        "book_at_branch": "この店舗を予約", "call_branch": "この店舗に電話",
        "other_branches": "他の店舗", "back_to": "{name}に戻る",
        "minutes": "分", "branch_count": "{n}店舗",
        "meta_desc": "{name}{where}。{branches}店舗、{services}サービス。24時間対応のバーチャルアシスタントでオンライン予約。",
        "meta_branch_desc": "{brand} — {name}、{address}。{hours}24時間対応のバーチャルアシスタントでオンライン予約。",
        "meta_hours": "営業時間 {hours}。", "title_suffix": "診察予約",
        "powered": "CareDesk AI 提供", "not_found": "ページが見つかりません",
        "not_found_body": "このクリニックまたは店舗は存在しないか、リンクが変更されたか、一時的に利用できません。",
    },
}


def landing_text(locale: str, key: str, **values: Any) -> str:
    """Localized landing-page copy with English as the safe final fallback."""
    table = LANDING_TEXT.get(normalize_locale(locale), LANDING_TEXT["en"])
    text = table.get(key, LANDING_TEXT["en"].get(key, key))
    return text.format(**values) if values else text


def locale_for_conversation(conversation: Any, clinic: Optional[Any]) -> str:
    return normalize_locale(
        getattr(conversation, "locale", None), getattr(clinic, "default_locale", "vi") if clinic else "vi"
    )
